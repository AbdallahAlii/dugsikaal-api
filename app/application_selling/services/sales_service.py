# app/application_selling/services/sales_service.py
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Tuple, Set, Any
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, BadRequest

from app.application_reports.hook.invalidation import invalidate_financial_reports_for_company, \
    invalidate_all_core_reports_for_company
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope
from app.business_validation import item_validation as V
from app.application_stock.stock_models import DocStatusEnum, StockLedgerEntry
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.sle_writer import append_sle
from app.application_stock.engine.bin_derive import derive_bin
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.engine.errors import PostingValidationError, IdempotencyError
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum, JournalEntryTypeEnum
from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
from app.common.timezone.service import get_company_timezone
from app.business_validation.posting_date_validation import PostingDateValidator
from app.application_selling.repository.sales_repo import SalesRepository
from app.application_selling.schemas import (
    DeliveryNoteCreate, DeliveryNoteUpdate,
    SalesInvoiceCreate, SalesInvoiceUpdate,
    SalesCreditNoteCreate
)
from app.application_selling.models import SalesDeliveryNote, SalesDeliveryNoteItem, SalesInvoice, SalesInvoiceItem
from  app.application_accounting.chart_of_accounts.models import JournalEntry
# Stock handlers
from app.application_stock.engine.handlers.sales import (
    build_intents_for_delivery_note,
    build_intents_for_sales_invoice_stock,
    sum_cogs_from_intents,
    build_gl_context_for_sales_invoice_finance_only,
    build_gl_context_for_sales_invoice_with_stock,
    build_gl_context_for_delivery_note,
)

logger = logging.getLogger(__name__)


class SalesService:
    DN_PREFIX = "SDN"
    SI_PREFIX = "SINV"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = SalesRepository(self.s)

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------
    def _generate_or_validate_code(self, prefix: str, company_id: int, branch_id: int, manual: Optional[str], exists_fn) -> str:
        if manual:
            code = manual.strip()
            if exists_fn(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=prefix, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=prefix, company_id=company_id, branch_id=branch_id)

    def _validate_party_and_warehouses(self, *, company_id: int, branch_id: int, customer_id: int, warehouse_ids: List[int]) -> None:
        ok_customers = self.repo.get_valid_customer_ids(company_id, [customer_id])
        V.validate_customer_is_active(customer_id in ok_customers)
        if warehouse_ids:
            ok_whs = self.repo.get_transactional_warehouse_ids(company_id, branch_id, warehouse_ids)
            for wid in warehouse_ids:
                if wid not in ok_whs:
                    raise V.BizValidationError("Invalid or non-transactional warehouse in payload.")

    def _resolve_income_account_id(
            self,
            company_id: int,
            item_detail: Dict,
            group_defaults: Dict,
            explicit_income_account_id: Optional[int],
    ) -> int:
        if explicit_income_account_id:
            return int(explicit_income_account_id)

        # 1) Item Group default
        grp_id = item_detail.get("item_group_id")
        if grp_id and grp_id in group_defaults:
            acc = group_defaults[grp_id].get("default_income_account_id")
            if acc:
                return int(acc)

        # 2) Fallback by item type
        is_stock = False
        if "is_stock_item" in item_detail:
            is_stock = bool(item_detail.get("is_stock_item"))
        elif "item_type" in item_detail:
            it = str(item_detail.get("item_type") or "").lower()
            is_stock = it in {"stock", "stock_item"}

        code = "4101" if is_stock else "4102"  # Sales Income / Service Income
        aid = self.repo.get_account_id_by_code(company_id, code)
        if not aid:
            from app.business_validation import item_validation as V
            raise V.BizValidationError(f"Default income account {code} not found.")
        return int(aid)

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.repo.get_doc_type_id(code)
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt

    def _detect_backdated(self, company_id: int, pairs: Set[Tuple[int, int]], posting_dt: datetime) -> bool:
        def _has_future_sle(item_id: int, wh_id: int) -> bool:
            q = self.s.execute(
                select(func.count()).select_from(StockLedgerEntry).where(
                    StockLedgerEntry.company_id == company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                        (StockLedgerEntry.posting_date > posting_dt.date()) |
                        and_(StockLedgerEntry.posting_date == posting_dt.date(), StockLedgerEntry.posting_time > posting_dt)
                    ),
                    StockLedgerEntry.is_cancelled == False,
                )
            ).scalar()
            return (q or 0) > 0
        return any(_has_future_sle(i, w) for (i, w) in pairs)

    def _coerce_signed_paid_for_return(self, is_return: bool, paid_amount: Decimal) -> Decimal:
        """
        Enforce sign on paid amount:
          - normal invoice: paid >= 0
          - return: paid <= 0 (refund)
        """
        paid = Decimal(str(paid_amount or 0))
        if is_return and paid > 0:
            raise V.BizValidationError("Paid amount must be negative for returns (refund to customer).")
        if not is_return and paid < 0:
            raise V.BizValidationError("Paid amount cannot be negative for normal invoices.")
        return paid

    def _validate_paid_and_writeoff(self, *, total_amount: Decimal, paid_amount: Decimal, write_off_amount: Decimal):
        # ERPNext-style combined ceiling, sign-aware:
        V.validate_paid_writeoff_ceiling(
            grand_total=total_amount, paid_amount=paid_amount, write_off_amount=write_off_amount
        )

    # ------------------------------------------------------------------------
    # Delivery Note (Create / Update / Submit)
    # ------------------------------------------------------------------------
    def create_delivery_note(self, *, payload: DeliveryNoteCreate, context: AffiliationContext) -> SalesDeliveryNote:
        # Resolve company/branch with scope checks
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        # ✅ Normalize & validate posting datetime right now (create-time)
        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s, payload.posting_date, company_id, created_at=None, treat_midnight_as_date=True
        )

        # Party & warehouse validation
        wh_ids = [ln.warehouse_id for ln in payload.items]
        self._validate_party_and_warehouses(
            company_id=company_id, branch_id=branch_id, customer_id=payload.customer_id, warehouse_ids=wh_ids
        )

        # Items active
        item_ids = [ln.item_id for ln in payload.items]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

        # UOM compatibility (only for stock items)
        uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
        if uom_pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
            for item_id, uom_id in uom_pairs:
                if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                    raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

        code = self._generate_or_validate_code(self.DN_PREFIX, company_id, branch_id, payload.code,
                                               self.repo.code_exists_dn)

        dn_items = [
            SalesDeliveryNoteItem(
                item_id=ln.item_id,
                uom_id=ln.uom_id,
                warehouse_id=ln.warehouse_id,
                delivered_qty=ln.delivered_qty,
                unit_price=ln.unit_price,
                remarks=ln.remarks,
            )
            for ln in payload.items
        ]

        dn = SalesDeliveryNote(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=context.user_id,
            customer_id=payload.customer_id,
            code=code,
            posting_date=norm_dt,  # ← normalized company-TZ datetime
            doc_status=DocStatusEnum.DRAFT,
            is_return=False,
            remarks=payload.remarks,
            total_amount=Decimal("0"),
            items=dn_items,
        )
        self.repo.save(dn)
        self.s.commit()
        return dn

    def update_delivery_note(self, *, dn_id: int, payload: DeliveryNoteUpdate,
                             context: AffiliationContext) -> SalesDeliveryNote:
        dn = self.repo.get_dn(dn_id, for_update=True)
        if not dn:
            raise NotFound("Delivery Note not found.")
        ensure_scope_by_ids(context=context, target_company_id=dn.company_id, target_branch_id=dn.branch_id)
        V.guard_draft_only(dn.doc_status)

        # ✅ Normalize & validate if client sent a new posting date
        if payload.posting_date:
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s, payload.posting_date, dn.company_id, created_at=dn.created_at, treat_midnight_as_date=True
            )
            dn.posting_date = norm_dt

        if payload.customer_id:
            self._validate_party_and_warehouses(
                company_id=dn.company_id,
                branch_id=dn.branch_id,
                customer_id=payload.customer_id,
                warehouse_ids=[l.warehouse_id for l in dn.items],
            )
            dn.customer_id = payload.customer_id

        if payload.remarks is not None:
            dn.remarks = payload.remarks

        if payload.items is not None:
            item_ids = [ln.item_id for ln in payload.items]
            details = self.repo.get_item_details_batch(dn.company_id, item_ids)
            V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

            uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
            if uom_pairs:
                compat = self.repo.get_compatible_uom_pairs(dn.company_id, uom_pairs)
                for item_id, uom_id in uom_pairs:
                    if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                        raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

            lines = [
                dict(
                    id=ln.id,
                    item_id=ln.item_id,
                    uom_id=ln.uom_id,
                    warehouse_id=ln.warehouse_id,
                    delivered_qty=ln.delivered_qty,
                    unit_price=ln.unit_price,
                    remarks=ln.remarks,
                )
                for ln in payload.items
            ]
            self.repo.sync_dn_lines(dn, lines)

        self.repo.save(dn)
        self.s.commit()
        return dn

    def submit_delivery_note(self, *, dn_id: int, context: AffiliationContext) -> SalesDeliveryNote:
        dn = self.repo.get_dn(dn_id, for_update=False)
        if not dn:
            raise NotFound("Delivery Note not found.")
        ensure_scope_by_ids(context=context, target_company_id=dn.company_id, target_branch_id=dn.branch_id)
        V.guard_submittable_state(dn.doc_status)

        tz = get_company_timezone(self.s, dn.company_id)
        posting_dt = resolve_posting_dt(dn.posting_date.date(), created_at=dn.created_at, tz=tz,
                                        treat_midnight_as_date=True)
        dt_id = self._get_doc_type_id_or_400("DELIVERY_NOTE")

        # Build SLE intents (only stock items will be yielded by handler)
        intents = build_intents_for_delivery_note(
            company_id=dn.company_id, branch_id=dn.branch_id, posting_dt=posting_dt,
            doc_type_id=dt_id, doc_id=dn.id, is_return=dn.is_return,
            lines=[{
                "item_id": it.item_id, "warehouse_id": it.warehouse_id, "delivered_qty": it.delivered_qty,
                "uom_id": it.uom_id, "base_uom_id": None, "doc_row_id": it.id
            } for it in dn.items], session=self.s,
        )

        pairs = {(i.item_id, i.warehouse_id) for i in intents}
        is_backdated = self._detect_backdated(dn.company_id, pairs, posting_dt)

        with self.s.begin_nested():
            dn_locked = self.repo.get_dn(dn_id, for_update=True)
            V.guard_submittable_state(dn_locked.doc_status)

            with lock_pairs(self.s, pairs):
                for idx, intent in enumerate(intents):
                    append_sle(self.s, intent, created_at_hint=dn_locked.created_at, tz_hint=tz, batch_index=idx)

            if is_backdated:
                for item_id, wh_id in pairs:
                    # ✅ keyword-only call
                    repost_from(
                        s=self.s,
                        company_id=dn_locked.company_id,
                        item_id=item_id,
                        warehouse_id=wh_id,
                        start_dt=posting_dt,
                        exclude_doc_types=set(),
                    )

            for item_id, wh_id in pairs:
                derive_bin(self.s, dn_locked.company_id, item_id, wh_id)

            cogs_val = sum_cogs_from_intents(intents)
            payload = build_gl_context_for_delivery_note(cogs_total=cogs_val, is_return=dn_locked.is_return)
            ctx = PostingContext(
                company_id=dn_locked.company_id, branch_id=dn_locked.branch_id,
                source_doctype_id=dt_id, source_doc_id=dn_locked.id,
                posting_date=posting_dt, created_by_id=context.user_id,
                is_auto_generated=True, entry_type=None,
                remarks=f"Delivery Note {dn_locked.code}",
                template_code="DELIVERY_NOTE_COGS", payload=payload,
                runtime_accounts={}, party_id=dn_locked.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                dynamic_account_context={}
            )
            PostingService(self.s).post(ctx)

            dn_locked.doc_status = DocStatusEnum.SUBMITTED
            self.repo.save(dn_locked)

        self.s.commit()
        return dn

    # ------------------------------------------------------------------------
    # Sales Invoice (Create / Update / Submit)
    # ------------------------------------------------------------------------
    @staticmethod
    def _compute_vat_amount(subtotal: Decimal, vat_rate: Optional[Decimal]) -> Decimal:
        """
        Rate beats amount: if vat_rate is provided, compute VAT as subtotal * rate/100.
        Round HALF_UP to 0.01 like typical sales tax.
        """
        if vat_rate is None:
            return Decimal("0.00")
        return (
            Decimal(subtotal) * Decimal(vat_rate) / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    def _validate_return_refund_against_original(
        self,
        *,
        original_si: SalesInvoice,
        new_refund: Decimal,
        current_return_id: Optional[int] = None,
    ) -> None:
        """
        Ensure inline refund on a return invoice does not exceed
        the amount actually paid on the original invoice.
        """
        # Only care when money is going OUT (negative paid_amount on return)
        if new_refund >= Decimal("0"):
            return

        orig_paid = Decimal(str(original_si.paid_amount or 0))
        if orig_paid <= Decimal("0"):
            # Original invoice not paid → allow credit note but no cash refund
            raise V.BizValidationError(
                "Cannot refund: the original invoice has no recorded payments."
            )

        # Sum existing refunds (paid_amount is negative on returns)
        SI = SalesInvoice
        stmt = (
            select(func.coalesce(func.sum(SI.paid_amount), 0))
            .where(
                SI.return_against_id == original_si.id,
                SI.is_return.is_(True),
                SI.doc_status != DocStatusEnum.CANCELLED,
            )
        )
        if current_return_id is not None:
            stmt = stmt.where(SI.id != current_return_id)

        existing = self.s.execute(stmt).scalar() or Decimal("0")
        already_refunded = abs(Decimal(str(existing)))  # existing refunds are negative

        requested_refund = abs(new_refund)

        # Do not allow refunds > original paid
        if requested_refund + already_refunded > orig_paid:
            raise V.BizValidationError(
                "Refund amount exceeds payments on the original invoice."
            )

    # ---- Sales Invoice (Create / Update) ------------------------------------


    def create_sales_invoice(
        self, *, payload: SalesInvoiceCreate, context: AffiliationContext
    ) -> SalesInvoice:
        # 1) Resolve company/branch with scope checks
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        # 2) Normalize/validate posting datetime
        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s,
            payload.posting_date,
            company_id,
            created_at=None,
            treat_midnight_as_date=True,
        )

        # 3) If this is a RETURN, load original invoice and enforce rules
        original_si = None
        if payload.is_return:
            if not payload.return_against_id:
                raise V.BizValidationError(
                    "Return Against is required for a return Sales Invoice."
                )

            original_si = self.repo.get_si_with_items(payload.return_against_id)
            if not original_si:
                raise V.BizValidationError(
                    "Original Sales Invoice not found or not eligible for return."
                )

            # Do not allow return against a return
            if original_si.is_return:
                raise V.BizValidationError(
                    "Cannot create a return against a return invoice."
                )

            # Allowed statuses for making a return
            allowed_statuses = {
                DocStatusEnum.UNPAID,
                DocStatusEnum.PARTIALLY_PAID,
                DocStatusEnum.PAID,
            }
            if original_si.doc_status not in allowed_statuses:
                raise V.BizValidationError(
                    f"Original Sales Invoice not eligible for return (status = {original_si.doc_status.name})."
                )

            # Posting date relative to original
            PostingDateValidator.validate_return_against_original(
                s=self.s,
                current_posting_date=payload.posting_date,
                original_document_date=original_si.posting_date,
                company_id=original_si.company_id,
            )

            # Same company check
            if company_id != original_si.company_id:
                raise V.BizValidationError(
                    "Return must belong to the same company as the original invoice."
                )

            # Branch must also belong to the same company
            branch_company = self.repo.get_branch_company_id(branch_id)
            if branch_company != original_si.company_id:
                raise V.BizValidationError(
                    "Branch must belong to the same company as the original invoice."
                )

            # Ensure user has scope on the original invoice branch as well
            ensure_scope_by_ids(
                context=context,
                target_company_id=original_si.company_id,
                target_branch_id=original_si.branch_id,
            )

        # 4) Party + warehouse checks
        self._validate_party_and_warehouses(
            company_id=company_id,
            branch_id=branch_id,
            customer_id=payload.customer_id,
            warehouse_ids=[ln.warehouse_id for ln in payload.items if ln.warehouse_id],
        )

        # 5) Items activity + UOM compat
        item_ids = [ln.item_id for ln in payload.items]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        V.validate_items_are_active(
            [
                (iid, details.get(iid, {}).get("is_active", False))
                for iid in item_ids
            ]
        )

        uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
        if uom_pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
            for item_id, uom_id in uom_pairs:
                if (
                    details.get(item_id, {}).get("is_stock_item", False)
                    and (item_id, uom_id) not in compat
                ):
                    raise V.BizValidationError(
                        f"UOM not compatible for item_id={item_id}"
                    )

        # 6) ERPNext-style: enforce sign of quantities for normal vs return
        V.validate_items_quantity_direction(
            payload.is_return,
            [{"quantity": ln.quantity} for ln in payload.items],
        )

        # 7) High-level return requirements
        V.validate_return_requirements(
            is_return=payload.is_return,
            return_against_id=payload.return_against_id,
        )

        # 8) Over-return protection (if this is a RETURN)
        if payload.is_return and original_si is not None:
            orig_lines_map = {it.id: it for it in original_si.items}
            returned_map = self._get_already_returned_quantities(
                list(orig_lines_map.keys())
            )

            for idx, ln in enumerate(payload.items, start=1):
                orig_line_id = getattr(ln, "return_against_item_id", None)
                if not orig_line_id or orig_line_id not in orig_lines_map:
                    raise V.BizValidationError(
                        f"Row #{idx}: Return Against Item is required and must reference an original invoice row."
                    )

                orig_line = orig_lines_map[orig_line_id]
                already = returned_map.get(orig_line_id, Decimal("0"))
                orig_qty = Decimal(str(orig_line.quantity))  # original is positive
                remaining = orig_qty - already

                if remaining <= Decimal("0"):
                    item_label = getattr(
                        getattr(orig_line, "item", None),
                        "name",
                        str(orig_line.item_id),
                    )
                    raise V.BizValidationError(
                        f"Row #{idx}: Item {item_label} has already been fully returned."
                    )

                requested_abs = abs(Decimal(str(ln.quantity)))  # ln.quantity is negative
                if requested_abs > remaining:
                    item_label = getattr(
                        getattr(orig_line, "item", None),
                        "name",
                        str(orig_line.item_id),
                    )
                    raise V.BizValidationError(
                        f"Row #{idx}: Cannot return more than {remaining} for Item {item_label}."
                    )

        # 9) Income account fallback per line
        group_defaults = self.repo.get_item_group_defaults(
            list(
                {
                    details[i]["item_group_id"]
                    for i in item_ids
                    if details.get(i)
                }
            )
        )

        invoice_items: List[SalesInvoiceItem] = []
        subtotal = Decimal("0")
        for ln in payload.items:
            det = details.get(ln.item_id, {})
            income_acc = self._resolve_income_account_id(
                company_id, det, group_defaults, ln.income_account_id
            )

            if payload.update_stock and det.get("is_stock_item", False) and not ln.warehouse_id:
                raise V.BizValidationError(
                    "Warehouse is required for stock items when 'Update Stock' is enabled."
                )

            qty_dec = Decimal(str(ln.quantity))
            rate_dec = Decimal(str(ln.rate))
            line_total = qty_dec * rate_dec

            invoice_items.append(
                SalesInvoiceItem(
                    item_id=ln.item_id,
                    uom_id=ln.uom_id,
                    quantity=ln.quantity,
                    rate=ln.rate,
                    warehouse_id=(
                        ln.warehouse_id
                        if payload.update_stock and det.get("is_stock_item", False)
                        else None
                    ),
                    income_account_id=income_acc,
                    delivery_note_item_id=(
                        ln.delivery_note_item_id if payload.delivery_note_id else None
                    ),
                    return_against_item_id=getattr(
                        ln, "return_against_item_id", None
                    )
                    if payload.is_return
                    else None,
                    remarks=ln.remarks,
                )
            )
            subtotal += line_total

        # 10) VAT: rate beats amount
        vat_amount = (
            self._compute_vat_amount(subtotal, payload.vat_rate)
            if payload.vat_rate is not None
            else (payload.vat_amount or Decimal("0"))
        )
        if vat_amount != 0 and not payload.vat_account_id:
            raise V.BizValidationError("Add a VAT account to book taxes.")

        total_amount = subtotal + vat_amount

        # 11) Paid & write-off rules
        paid_amount = self._coerce_signed_paid_for_return(
            payload.is_return, payload.paid_amount
        )
        V.validate_payment_consistency(
            paid_amount, payload.mode_of_payment_id, payload.cash_bank_account_id
        )
        self._validate_paid_and_writeoff(
            total_amount=total_amount,
            paid_amount=paid_amount,
            write_off_amount=(payload.write_off_amount or Decimal("0")),
        )

        # 12) Debit To (A/R) default
        debit_to = (
            payload.debit_to_account_id
            or self.repo.get_default_receivable_account(company_id)
        )

        # 13) Code generation
        code = self._generate_or_validate_code(
            self.SI_PREFIX,
            company_id,
            branch_id,
            payload.code,
            self.repo.code_exists_si,
        )

        # 14) Build & save invoice
        si = SalesInvoice(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=context.user_id,
            customer_id=payload.customer_id,
            debit_to_account_id=debit_to,
            code=code,
            posting_date=norm_dt,
            doc_status=DocStatusEnum.DRAFT,
            update_stock=payload.update_stock,
            is_return=payload.is_return,
            return_against_id=(
                payload.return_against_id if payload.is_return else None
            ),
            vat_account_id=payload.vat_account_id,
            vat_rate=payload.vat_rate,
            vat_amount=vat_amount,
            total_amount=total_amount,
            paid_amount=paid_amount,
            outstanding_amount=total_amount - paid_amount,
            due_date=payload.due_date,
            remarks=payload.remarks,
            mode_of_payment_id=payload.mode_of_payment_id,
            cash_bank_account_id=payload.cash_bank_account_id,
            items=invoice_items,
        )
        self.repo.save(si)
        self.s.commit()
        return si


    def build_sales_invoice_return_template(
            self, *, original_si_id: int, context: AffiliationContext
    ) -> dict:
        """
        ERPNext-style mapped doc for Sales Invoice Return (Credit Note):

        - Load original Sales Invoice (with items + key relations).
        - Build a RETURN draft payload (NOT saved).
        - Quantities are NEGATIVE.
        - is_return = True, return_against_id = original.id.

        The result is structured for UI:

        {
          "header": { ...fields for NEW return SI... },
          "items":  [ ...negative qty lines... ],
          "original_invoice": { ...summary of original... },
          "original_payment": { ...MOP + bank info from original... }
        }
        """
        si: SalesInvoice = self.repo.get_si_with_items(original_si_id)
        if not si:
            raise NotFound("Original Sales Invoice not found.")

        # Scope checks
        ensure_scope_by_ids(
            context=context,
            target_company_id=si.company_id,
            target_branch_id=si.branch_id,
        )

        # Optional: only allow returns against submitted invoices
        # if si.doc_status != DocStatusEnum.SUBMITTED:
        #     raise BadRequest("You can only create a return against a submitted Sales Invoice.")

        if si.is_return:
            raise BadRequest("Cannot create a return against a return invoice.")

        # ------------------------------------------------------------------
        # 1) Build header for NEW return SI (what frontend will POST later)
        # ------------------------------------------------------------------
        today_str = datetime.now(timezone.utc).date().isoformat()

        header: Dict[str, Any] = {
            "company_id": si.company_id,
            "branch_id": si.branch_id,
            "branch_name": getattr(getattr(si, "branch", None), "name", None),
            "customer_id": si.customer_id,
            "customer_name": getattr(getattr(si, "customer", None), "name", None),
            "posting_date": today_str,
            "due_date": None,
            "update_stock": si.update_stock,
            "is_return": True,
            "return_against_id": si.id,
            "remarks": f"Return against invoice {si.code}",
        }

        # VAT: carry same settings; UI can change
        header["vat_account_id"] = si.vat_account_id or None
        header["vat_rate"] = float(si.vat_rate) if si.vat_rate is not None else None

        # Payment on the RETURN starts as unpaid (no refund yet).
        # UI may later set a NEGATIVE paid_amount + MOP + cash_bank_account_id.
        header["paid_amount"] = "0.00"
        header["mode_of_payment_id"] = None
        header["cash_bank_account_id"] = None

        # ------------------------------------------------------------------
        # 2) Map items with NEGATIVE quantities
        # ------------------------------------------------------------------
        lines: List[Dict[str, Any]] = []
        for it in si.items:
            qty = Decimal(str(it.quantity))
            rate = Decimal(str(it.rate))

            lines.append(
                {
                    "item_id": it.item_id,
                    "uom_id": it.uom_id,
                    "warehouse_id": it.warehouse_id,
                    "quantity": str(-qty),  # NEGATIVE for return
                    "rate": str(rate),
                    "delivery_note_item_id": it.delivery_note_item_id,
                    "return_against_item_id": it.id,
                    "remarks": it.remarks,
                }
            )

        # ------------------------------------------------------------------
        # 3) Original invoice summary (read-only info for UI)
        # ------------------------------------------------------------------
        original_invoice = {
            "id": si.id,
            "code": si.code,
            "posting_date": si.posting_date.date().isoformat()
            if si.posting_date
            else None,
            "total_amount": str(si.total_amount or Decimal("0")),
            "paid_amount": str(si.paid_amount or Decimal("0")),
            "outstanding_amount": str(si.outstanding_amount or Decimal("0")),
            "update_stock": bool(si.update_stock),
            "doc_status": si.doc_status.name if si.doc_status else None,
        }

        # ------------------------------------------------------------------
        # 4) Original payment details (for display / suggestions)
        # ------------------------------------------------------------------
        mop = getattr(si, "mode_of_payment", None)
        bank_acc = getattr(si, "cash_bank_account", None)

        original_payment = {
            "mode_of_payment_id": si.mode_of_payment_id,
            "mode_of_payment_name": getattr(mop, "name", None),
            "cash_bank_account_id": si.cash_bank_account_id,
            "cash_bank_account_name": getattr(bank_acc, "name", None),
            "cash_bank_account_code": getattr(bank_acc, "code", None),
        }

        return {
            "header": header,
            "items": lines,
            "original_invoice": original_invoice,
            "original_payment": original_payment,
        }


    def update_sales_invoice(self, *, si_id: int, payload: SalesInvoiceUpdate,
                             context: AffiliationContext) -> SalesInvoice:
        si = self.repo.get_si(si_id, for_update=True)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        V.guard_draft_only(si.doc_status)

        # For safety: do not allow switching a normal invoice into a return or vice-versa after creation.
        if payload.is_return is not None and bool(payload.is_return) != bool(si.is_return):
            raise V.BizValidationError("Cannot change 'is_return' after creation.")
        if payload.return_against_id is not None and payload.return_against_id != getattr(si, "return_against_id",
                                                                                          None):
            raise V.BizValidationError("Cannot change 'return_against_id' after creation.")

        # Posting date
        if payload.posting_date:
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s, payload.posting_date, si.company_id, created_at=si.created_at, treat_midnight_as_date=True
            )
            si.posting_date = norm_dt

        # Party
        if payload.customer_id:
            self._validate_party_and_warehouses(
                company_id=si.company_id, branch_id=si.branch_id, customer_id=payload.customer_id,
                warehouse_ids=[l.warehouse_id for l in si.items if l.warehouse_id]
            )
            si.customer_id = payload.customer_id

        # Debit To (allowed in draft)
        if payload.debit_to_account_id is not None:
            si.debit_to_account_id = payload.debit_to_account_id

        if payload.remarks is not None:
            si.remarks = payload.remarks
        if payload.due_date is not None:
            si.due_date = payload.due_date

        # update_stock toggle BEFORE touching lines
        if payload.update_stock is not None and payload.update_stock != si.update_stock:
            if getattr(si, "delivery_note_id", None) and payload.update_stock:
                raise V.BizValidationError(
                    "Cannot enable 'Update Stock' for an invoice created against a Delivery Note.")
            if payload.update_stock:
                # turning ON → existing stock lines must have warehouses
                item_ids = [ln.item_id for ln in si.items]
                details = self.repo.get_item_details_batch(si.company_id, item_ids)
                for ln in si.items:
                    det = details.get(ln.item_id, {})
                    if det.get("is_stock_item", False) and not ln.warehouse_id:
                        raise V.BizValidationError(
                            "Warehouse is required for stock items when 'Update Stock' is enabled.")
                si.update_stock = True
            else:
                for it in si.items:
                    it.warehouse_id = None
                si.update_stock = False

        # Replace lines if provided
        if payload.items is not None:
            item_ids = [ln.item_id for ln in payload.items]
            details = self.repo.get_item_details_batch(si.company_id, item_ids)
            V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

            # ERPNext-style sign enforcement for return vs normal
            V.validate_items_quantity_direction(si.is_return, [{"quantity": ln.quantity} for ln in payload.items])

            uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
            if uom_pairs:
                compat = self.repo.get_compatible_uom_pairs(si.company_id, uom_pairs)
                for item_id, uom_id in uom_pairs:
                    if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                        raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

            group_defaults = self.repo.get_item_group_defaults(
                list({details[i]["item_group_id"] for i in item_ids if details.get(i)})
            )

            lines: List[Dict] = []
            subtotal = Decimal("0")
            for ln in payload.items:
                det = details.get(ln.item_id, {})
                inc = self._resolve_income_account_id(si.company_id, det, group_defaults, ln.income_account_id)

                if si.update_stock and det.get("is_stock_item", False) and not ln.warehouse_id:
                    raise V.BizValidationError("Warehouse is required for stock items when 'Update Stock' is enabled.")

                line_amount = Decimal(str(ln.quantity)) * Decimal(str(ln.rate))
                lines.append(dict(
                    id=ln.id,
                    item_id=ln.item_id,
                    uom_id=ln.uom_id,
                    quantity=ln.quantity,
                    rate=ln.rate,
                    warehouse_id=ln.warehouse_id if (si.update_stock and det.get("is_stock_item", False)) else None,
                    income_account_id=inc,
                    remarks=ln.remarks
                ))
                subtotal += line_amount

            self.repo.sync_si_lines(si, lines)

            # VAT & totals (lines changed)
            vat_rate_effective = payload.vat_rate if payload.vat_rate is not None else si.vat_rate
            vat_amount = self._compute_vat_amount(subtotal, vat_rate_effective) if vat_rate_effective is not None \
                else (payload.vat_amount if payload.vat_amount is not None else si.vat_amount)

            if vat_amount > 0 and not (payload.vat_account_id or si.vat_account_id):
                raise V.BizValidationError("Add a VAT account to book taxes.")

            if payload.vat_rate is not None:
                si.vat_rate = payload.vat_rate
            if payload.vat_account_id is not None:
                si.vat_account_id = payload.vat_account_id
            si.vat_amount = vat_amount
            si.total_amount = subtotal + vat_amount

        else:
            # Lines unchanged; allow VAT edits
            if payload.vat_rate is not None or payload.vat_amount is not None or payload.vat_account_id is not None:
                subtotal = sum(Decimal(str(it.quantity)) * Decimal(str(it.rate)) for it in si.items)
                vat_rate_effective = payload.vat_rate if payload.vat_rate is not None else si.vat_rate
                vat_amount = self._compute_vat_amount(subtotal, vat_rate_effective) if vat_rate_effective is not None \
                    else (payload.vat_amount if payload.vat_amount is not None else si.vat_amount)
                if vat_amount > 0 and not (payload.vat_account_id or si.vat_account_id):
                    raise V.BizValidationError("Add a VAT account to book taxes.")
                if payload.vat_rate is not None:
                    si.vat_rate = payload.vat_rate
                if payload.vat_account_id is not None:
                    si.vat_account_id = payload.vat_account_id
                si.vat_amount = vat_amount
                si.total_amount = subtotal + vat_amount

        # Payment edits (draft only) — sign-aware for returns
        if (payload.paid_amount is not None) or (payload.mode_of_payment_id is not None) or (
                payload.cash_bank_account_id is not None):
            paid_amount = self._coerce_signed_paid_for_return(si.is_return,
                                                              payload.paid_amount if payload.paid_amount is not None else si.paid_amount)
            mop_id = payload.mode_of_payment_id if payload.mode_of_payment_id is not None else getattr(si,
                                                                                                       "mode_of_payment_id",
                                                                                                       None)
            cash_bank_id = payload.cash_bank_account_id if payload.cash_bank_account_id is not None else getattr(si,
                                                                                                                 "cash_bank_account_id",
                                                                                                                 None)

            V.validate_payment_consistency(paid_amount, mop_id, cash_bank_id)
            # optional write-off validation input
            woff = payload.write_off_amount if payload.write_off_amount is not None else Decimal("0")
            self._validate_paid_and_writeoff(total_amount=si.total_amount, paid_amount=paid_amount,
                                             write_off_amount=woff)

            si.paid_amount = paid_amount
            si.mode_of_payment_id = mop_id
            si.cash_bank_account_id = cash_bank_id

        si.outstanding_amount = si.total_amount - si.paid_amount

        self.repo.save(si)
        self.s.commit()
        return si

    def submit_sales_invoice(self, *, si_id: int, context: AffiliationContext) -> SalesInvoice:
        """
        ERPNext-style submit:
          - Normal: revenue(+), AR(+), optional stock/COGS
          - Return: revenue(-), AR(-), optional restock/COGS reversal
          - Inline receipt if paid_amount != 0 (refund for returns is negative paid)
        """
        from sqlalchemy import select
        from app.application_accounting.chart_of_accounts.models import JournalEntry, JournalEntryTypeEnum
        from decimal import Decimal as Dec, ROUND_HALF_UP

        def _D(x) -> Dec:
            return Dec(str(x or 0)).quantize(Dec("0.0001"), rounding=ROUND_HALF_UP)

        def _derive_status_after_submit(si_obj) -> DocStatusEnum:
            # Returns are always marked as RETURNED (credit note semantics)
            if si_obj.is_return:
                return DocStatusEnum.RETURNED
            paid = _D(si_obj.paid_amount)
            total = _D(si_obj.total_amount)
            if paid <= _D("0"):
                return DocStatusEnum.UNPAID
            if paid + _D("0") >= total:
                return DocStatusEnum.PAID
            return DocStatusEnum.PARTIALLY_PAID

        def _auto_je_exists(company_id: int, doctype_id: int, doc_id: int) -> bool:
            stmt = (
                select(JournalEntry.id)
                .where(
                    JournalEntry.company_id == company_id,
                    JournalEntry.source_doctype_id == doctype_id,
                    JournalEntry.source_doc_id == doc_id,
                    JournalEntry.is_auto_generated == True,
                    JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
                    JournalEntry.entry_type == JournalEntryTypeEnum.AUTO,
                )
                .limit(1)
            )
            return bool(self.s.execute(stmt).scalar_one_or_none())

        # 1) Read
        si = self.repo.get_si(si_id, for_update=False)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        V.guard_submittable_state(si.doc_status)
        if not si.items:
            raise V.BizValidationError("No items to submit.")

        # If this is a return, load original SI for extra refund checks
        original_si = None
        if si.is_return and si.return_against_id:
            original_si = self.repo.get_si(si.return_against_id, for_update=False)
            if not original_si:
                raise V.BizValidationError("Original Sales Invoice not found for this return.")

        # Sign rules on submit too (defense in depth)
        V.validate_items_quantity_direction(si.is_return, [{"quantity": it.quantity} for it in si.items])
        V.validate_return_requirements(is_return=si.is_return, return_against_id=si.return_against_id)
        # ceiling on (total, paid, write_off) – sign aware
        self._validate_paid_and_writeoff(
            total_amount=si.total_amount,
            paid_amount=si.paid_amount,
            write_off_amount=Decimal("0"),
        )
        # Extra: for returns, do not refund more than original payments
        if si.is_return and original_si is not None:
            self._validate_return_refund_against_original(
                original_si=original_si,
                new_refund=Decimal(str(si.paid_amount or 0)),
                current_return_id=si.id,
            )

        tz = get_company_timezone(self.s, si.company_id)
        posting_dt = resolve_posting_dt(si.posting_date.date(), created_at=si.created_at, tz=tz,
                                        treat_midnight_as_date=True)
        dt_id_si = self._get_doc_type_id_or_400("SALES_INVOICE")

        total_amount = _D(si.total_amount)
        paid_amount = _D(si.paid_amount)
        vat_amount = _D(si.vat_amount)
        subtotal = _D(sum(_D(it.amount) for it in si.items))

        income_splits: Dict[int, Dec] = {}
        for it in si.items:
            acc_id = int(it.income_account_id)
            income_splits[acc_id] = income_splits.get(acc_id, _D("0")) + _D(it.amount)

        # 2) Stock path
        if si.update_stock:
            stock_lines = [
                {
                    "item_id": it.item_id,
                    "uom_id": it.uom_id,
                    "base_uom_id": None,
                    "quantity": it.quantity,  # already negative for returns
                    "doc_row_id": it.id,
                    "warehouse_id": it.warehouse_id,
                }
                for it in si.items if it.warehouse_id
            ]
            intents = build_intents_for_sales_invoice_stock(
                company_id=si.company_id,
                branch_id=si.branch_id,
                posting_dt=posting_dt,
                doc_type_id=dt_id_si,
                doc_id=si.id,
                is_return=si.is_return,
                lines=stock_lines,
                session=self.s,
            )
            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            is_backdated = self._detect_backdated(si.company_id, pairs, posting_dt)

            with self.s.begin_nested():
                si_locked = self.repo.get_si(si_id, for_update=True)
                V.guard_submittable_state(si_locked.doc_status)

                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(self.s, intent, created_at_hint=si_locked.created_at, tz_hint=tz, batch_index=idx)

                if is_backdated:
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=si_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set(),
                        )

                for item_id, wh_id in pairs:
                    derive_bin(self.s, si_locked.company_id, item_id, wh_id)

                cogs_val = sum_cogs_from_intents(intents)

                payload = build_gl_context_for_sales_invoice_with_stock(
                    debit_to_account_id=si_locked.debit_to_account_id,
                    vat_account_id=si_locked.vat_account_id,
                    total_amount=si_locked.total_amount,
                    vat_amount=si_locked.vat_amount,
                    lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si_locked.items],
                    cogs_total=cogs_val,
                    is_return=si_locked.is_return,
                    discount_amount=Dec("0"),
                    round_off_positive=Dec("0"),
                    round_off_negative=Dec("0"),
                    default_ar_account_id=None,
                )
                payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
                payload["document_subtotal"] = subtotal
                payload["document_total"] = total_amount
                payload["tax_amount"] = vat_amount

                dyn_ctx = {
                    "accounts_receivable_account_id": si_locked.debit_to_account_id,
                    "tax_account_id": si_locked.vat_account_id,
                }
                if paid_amount != _D("0"):
                    # For returns: paid_amount is negative (refund), same logic applies
                    if not si_locked.mode_of_payment_id or not si_locked.cash_bank_account_id:
                        raise V.BizValidationError(
                            "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                        )
                    # NOTE: negative for refund → templates flip DR/CR effectively
                    payload["AMOUNT_RECEIVED"] = float(paid_amount)
                    dyn_ctx.update({
                        "cash_bank_account_id": si_locked.cash_bank_account_id,
                        # A/R ledger (customer) – DR on payment, CR on refund via sign
                        "party_ledger_account_id": si_locked.debit_to_account_id,
                    })

                ctx = PostingContext(
                    company_id=si_locked.company_id,
                    branch_id=si_locked.branch_id,
                    source_doctype_id=dt_id_si,
                    source_doc_id=si_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=JournalEntryTypeEnum.AUTO,
                    remarks=f"Sales Invoice {si_locked.code} ({'return' if si_locked.is_return else 'with stock'})",
                    template_code="SALES_INV_WITH_STOCK",
                    payload=payload,
                    runtime_accounts={},
                    party_id=si_locked.customer_id,
                    party_type=PartyTypeEnum.CUSTOMER,
                    dynamic_account_context=dyn_ctx,
                )
                if not _auto_je_exists(si_locked.company_id, dt_id_si, si_locked.id):
                    PostingService(self.s).post(ctx)
                else:
                    logger.info("Skip invoice GL: already posted for SI %s", si_locked.id)

                si_locked.outstanding_amount = _D(si_locked.total_amount) - _D(si_locked.paid_amount)
                si_locked.doc_status = _derive_status_after_submit(si_locked)
                self.repo.save(si_locked)

            self.s.commit()
            invalidate_all_core_reports_for_company(si.company_id, include_stock=True)
            return si

        # 3) Finance-only path
        payload = build_gl_context_for_sales_invoice_finance_only(
            debit_to_account_id=si.debit_to_account_id,
            vat_account_id=si.vat_account_id,
            total_amount=si.total_amount,
            vat_amount=si.vat_amount,
            lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si.items],
            discount_amount=Dec("0"),
            round_off_positive=Dec("0"),
            round_off_negative=Dec("0"),
            default_ar_account_id=None,
            # NOTE: builder uses signs from amounts; si.is_return guarantees negative lines/total when necessary
        )
        payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
        payload["document_subtotal"] = subtotal
        payload["document_total"] = total_amount
        payload["tax_amount"] = vat_amount

        dyn_ctx = {
            "accounts_receivable_account_id": si.debit_to_account_id,
            "tax_account_id": si.vat_account_id,
        }
        if paid_amount != _D("0"):
            if not si.mode_of_payment_id or not si.cash_bank_account_id:
                raise V.BizValidationError(
                    "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                )
            payload["AMOUNT_RECEIVED"] = float(paid_amount)
            dyn_ctx.update({
                "cash_bank_account_id": si.cash_bank_account_id,
                "party_ledger_account_id": si.debit_to_account_id,
            })

        ctx = PostingContext(
            company_id=si.company_id,
            branch_id=si.branch_id,
            source_doctype_id=dt_id_si,
            source_doc_id=si.id,
            posting_date=posting_dt,
            created_by_id=context.user_id,
            is_auto_generated=True,
            entry_type=JournalEntryTypeEnum.AUTO,
            remarks=f"Sales Invoice {si.code}" + (" (return)" if si.is_return else ""),
            template_code="SALES_INV_AR",
            payload=payload,
            runtime_accounts={},
            party_id=si.customer_id,
            party_type=PartyTypeEnum.CUSTOMER,
            dynamic_account_context=dyn_ctx,
        )
        if not _auto_je_exists(si.company_id, dt_id_si, si.id):
            PostingService(self.s).post(ctx)
        else:
            logger.info("Skip invoice GL: already posted for SI %s", si.id)

        with self.s.begin_nested():
            si_locked = self.repo.get_si(si_id, for_update=True)
            V.guard_submittable_state(si_locked.doc_status)
            si_locked.outstanding_amount = _D(si_locked.total_amount) - _D(si_locked.paid_amount)
            si_locked.doc_status = _derive_status_after_submit(si_locked)
            self.repo.save(si_locked)

        self.s.commit()
        invalidate_financial_reports_for_company(si.company_id)
        return si

    # def submit_sales_invoice(self, *, si_id: int, context: AffiliationContext) -> SalesInvoice:
    #     """
    #     ERPNext-style submit:
    #       - Normal: revenue(+), AR(+), optional stock/COGS
    #       - Return: revenue(-), AR(-), optional restock/COGS reversal
    #       - Inline receipt if paid_amount != 0 (refund for returns is negative paid)
    #     """
    #     from sqlalchemy import select
    #     from app.application_accounting.chart_of_accounts.models import JournalEntry, JournalEntryTypeEnum
    #     from decimal import Decimal as Dec, ROUND_HALF_UP
    #
    #     def _D(x) -> Dec:
    #         return Dec(str(x or 0)).quantize(Dec("0.0001"), rounding=ROUND_HALF_UP)
    #
    #     def _derive_status_after_submit(si_obj) -> DocStatusEnum:
    #         if si_obj.is_return:
    #             return DocStatusEnum.RETURNED
    #         paid = _D(si_obj.paid_amount)
    #         total = _D(si_obj.total_amount)
    #         if paid <= _D("0"):
    #             return DocStatusEnum.UNPAID
    #         if paid + _D("0") >= total:
    #             return DocStatusEnum.PAID
    #         return DocStatusEnum.PARTIALLY_PAID
    #
    #     def _auto_je_exists(company_id: int, doctype_id: int, doc_id: int) -> bool:
    #         stmt = (
    #             select(JournalEntry.id)
    #             .where(
    #                 JournalEntry.company_id == company_id,
    #                 JournalEntry.source_doctype_id == doctype_id,
    #                 JournalEntry.source_doc_id == doc_id,
    #                 JournalEntry.is_auto_generated == True,
    #                 JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
    #                 JournalEntry.entry_type == JournalEntryTypeEnum.AUTO,
    #             )
    #             .limit(1)
    #         )
    #         return bool(self.s.execute(stmt).scalar_one_or_none())
    #
    #     # 1) Read
    #     si = self.repo.get_si(si_id, for_update=False)
    #     if not si:
    #         raise NotFound("Sales Invoice not found.")
    #     ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
    #     V.guard_submittable_state(si.doc_status)
    #     if not si.items:
    #         raise V.BizValidationError("No items to submit.")
    #
    #     # Sign rules on submit too (defense in depth)
    #     V.validate_items_quantity_direction(si.is_return, [{"quantity": it.quantity} for it in si.items])
    #     V.validate_return_requirements(is_return=si.is_return, return_against_id=si.return_against_id)
    #     self._validate_paid_and_writeoff(total_amount=si.total_amount, paid_amount=si.paid_amount,
    #                                      write_off_amount=Decimal("0"))
    #
    #     tz = get_company_timezone(self.s, si.company_id)
    #     posting_dt = resolve_posting_dt(si.posting_date.date(), created_at=si.created_at, tz=tz,
    #                                     treat_midnight_as_date=True)
    #     dt_id_si = self._get_doc_type_id_or_400("SALES_INVOICE")
    #
    #     total_amount = _D(si.total_amount)
    #     paid_amount = _D(si.paid_amount)
    #     vat_amount = _D(si.vat_amount)
    #     subtotal = _D(sum(_D(it.amount) for it in si.items))
    #
    #     income_splits: Dict[int, Dec] = {}
    #     for it in si.items:
    #         acc_id = int(it.income_account_id)
    #         income_splits[acc_id] = income_splits.get(acc_id, _D("0")) + _D(it.amount)
    #
    #     # 2) Stock path
    #     if si.update_stock:
    #         stock_lines = [
    #             {
    #                 "item_id": it.item_id,
    #                 "uom_id": it.uom_id,
    #                 "base_uom_id": None,
    #                 "quantity": it.quantity,  # already negative for returns
    #                 "doc_row_id": it.id,
    #                 "warehouse_id": it.warehouse_id,
    #             }
    #             for it in si.items if it.warehouse_id
    #         ]
    #         intents = build_intents_for_sales_invoice_stock(
    #             company_id=si.company_id,
    #             branch_id=si.branch_id,
    #             posting_dt=posting_dt,
    #             doc_type_id=dt_id_si,
    #             doc_id=si.id,
    #             is_return=si.is_return,
    #             lines=stock_lines,
    #             session=self.s,
    #         )
    #         pairs = {(i.item_id, i.warehouse_id) for i in intents}
    #         is_backdated = self._detect_backdated(si.company_id, pairs, posting_dt)
    #
    #         with self.s.begin_nested():
    #             si_locked = self.repo.get_si(si_id, for_update=True)
    #             V.guard_submittable_state(si_locked.doc_status)
    #
    #             with lock_pairs(self.s, pairs):
    #                 for idx, intent in enumerate(intents):
    #                     append_sle(self.s, intent, created_at_hint=si_locked.created_at, tz_hint=tz, batch_index=idx)
    #
    #             if is_backdated:
    #                 for item_id, wh_id in pairs:
    #                     repost_from(
    #                         s=self.s,
    #                         company_id=si_locked.company_id,
    #                         item_id=item_id,
    #                         warehouse_id=wh_id,
    #                         start_dt=posting_dt,
    #                         exclude_doc_types=set(),
    #                     )
    #
    #             for item_id, wh_id in pairs:
    #                 derive_bin(self.s, si_locked.company_id, item_id, wh_id)
    #
    #             cogs_val = sum_cogs_from_intents(intents)
    #
    #             payload = build_gl_context_for_sales_invoice_with_stock(
    #                 debit_to_account_id=si_locked.debit_to_account_id,
    #                 vat_account_id=si_locked.vat_account_id,
    #                 total_amount=si_locked.total_amount,
    #                 vat_amount=si_locked.vat_amount,
    #                 lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si_locked.items],
    #                 cogs_total=cogs_val,
    #                 is_return=si_locked.is_return,
    #                 discount_amount=Dec("0"),
    #                 round_off_positive=Dec("0"),
    #                 round_off_negative=Dec("0"),
    #                 default_ar_account_id=None,
    #             )
    #             payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
    #             payload["document_subtotal"] = subtotal
    #             payload["document_total"] = total_amount
    #             payload["tax_amount"] = vat_amount
    #
    #             dyn_ctx = {
    #                 "accounts_receivable_account_id": si_locked.debit_to_account_id,
    #                 "tax_account_id": si_locked.vat_account_id,
    #             }
    #             if paid_amount != _D("0"):
    #                 # for returns: paid_amount is negative (refund), same logic applies
    #                 if not si_locked.mode_of_payment_id or not si_locked.cash_bank_account_id:
    #                     raise V.BizValidationError(
    #                         "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing.")
    #                 payload["AMOUNT_RECEIVED"] = float(paid_amount)
    #                 dyn_ctx.update({
    #                     "cash_bank_account_id": si_locked.cash_bank_account_id,
    #                     # DR when positive / CR when negative handled by template
    #                     "party_ledger_account_id": si_locked.debit_to_account_id,
    #                 })
    #
    #             ctx = PostingContext(
    #                 company_id=si_locked.company_id,
    #                 branch_id=si_locked.branch_id,
    #                 source_doctype_id=dt_id_si,
    #                 source_doc_id=si_locked.id,
    #                 posting_date=posting_dt,
    #                 created_by_id=context.user_id,
    #                 is_auto_generated=True,
    #                 entry_type=JournalEntryTypeEnum.AUTO,
    #                 remarks=f"Sales Invoice {si_locked.code} ({'return' if si_locked.is_return else 'with stock'})",
    #                 template_code="SALES_INV_WITH_STOCK",
    #                 payload=payload,
    #                 runtime_accounts={},
    #                 party_id=si_locked.customer_id,
    #                 party_type=PartyTypeEnum.CUSTOMER,
    #                 dynamic_account_context=dyn_ctx,
    #             )
    #             if not _auto_je_exists(si_locked.company_id, dt_id_si, si_locked.id):
    #                 PostingService(self.s).post(ctx)
    #             else:
    #                 logger.info("Skip invoice GL: already posted for SI %s", si_locked.id)
    #
    #             si_locked.outstanding_amount = _D(si_locked.total_amount) - _D(si_locked.paid_amount)
    #             si_locked.doc_status = _derive_status_after_submit(si_locked)
    #             self.repo.save(si_locked)
    #
    #         self.s.commit()
    #         invalidate_all_core_reports_for_company(si.company_id, include_stock=True)
    #         return si
    #
    #     # 3) Finance-only path
    #     payload = build_gl_context_for_sales_invoice_finance_only(
    #         debit_to_account_id=si.debit_to_account_id,
    #         vat_account_id=si.vat_account_id,
    #         total_amount=si.total_amount,
    #         vat_amount=si.vat_amount,
    #         lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si.items],
    #         discount_amount=Dec("0"),
    #         round_off_positive=Dec("0"),
    #         round_off_negative=Dec("0"),
    #         default_ar_account_id=None,
    #         # NOTE: builder uses signs from amounts; si.is_return guarantees negative lines/total when necessary
    #     )
    #     payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
    #     payload["document_subtotal"] = subtotal
    #     payload["document_total"] = total_amount
    #     payload["tax_amount"] = vat_amount
    #
    #     dyn_ctx = {
    #         "accounts_receivable_account_id": si.debit_to_account_id,
    #         "tax_account_id": si.vat_account_id,
    #     }
    #     if paid_amount != _D("0"):
    #         if not si.mode_of_payment_id or not si.cash_bank_account_id:
    #             raise V.BizValidationError(
    #                 "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing.")
    #         payload["AMOUNT_RECEIVED"] = float(paid_amount)
    #         dyn_ctx.update({
    #             "cash_bank_account_id": si.cash_bank_account_id,
    #             "party_ledger_account_id": si.debit_to_account_id,
    #         })
    #
    #     ctx = PostingContext(
    #         company_id=si.company_id,
    #         branch_id=si.branch_id,
    #         source_doctype_id=dt_id_si,
    #         source_doc_id=si.id,
    #         posting_date=posting_dt,
    #         created_by_id=context.user_id,
    #         is_auto_generated=True,
    #         entry_type=JournalEntryTypeEnum.AUTO,
    #         remarks=f"Sales Invoice {si.code}" + (" (return)" if si.is_return else ""),
    #         template_code="SALES_INV_AR",
    #         payload=payload,
    #         runtime_accounts={},
    #         party_id=si.customer_id,
    #         party_type=PartyTypeEnum.CUSTOMER,
    #         dynamic_account_context=dyn_ctx,
    #     )
    #     if not _auto_je_exists(si.company_id, dt_id_si, si.id):
    #         PostingService(self.s).post(ctx)
    #     else:
    #         logger.info("Skip invoice GL: already posted for SI %s", si.id)
    #
    #     with self.s.begin_nested():
    #         si_locked = self.repo.get_si(si_id, for_update=True)
    #         V.guard_submittable_state(si_locked.doc_status)
    #         si_locked.outstanding_amount = _D(si_locked.total_amount) - _D(si_locked.paid_amount)
    #         si_locked.doc_status = _derive_status_after_submit(si_locked)
    #         self.repo.save(si_locked)
    #
    #     self.s.commit()
    #     invalidate_financial_reports_for_company(si.company_id)
    #     return si

    def cancel_sales_invoice(self, *, si_id: int, context: AffiliationContext) -> SalesInvoice:
        """
        Cancel a submitted Sales Invoice by reversing stock (when update_stock=True)
        and cancelling the original auto Journal Entry. Safe for backdated postings.
        Blocks if any linked return/credit notes exist and are not cancelled.
        """
        from sqlalchemy import select, func
        from decimal import Decimal

        from app.application_stock.stock_models import DocStatusEnum
        from app.common.timezone.service import get_company_timezone
        from app.application_stock.engine.posting_clock import resolve_posting_dt
        from app.application_stock.engine.handlers.sales import build_intents_for_sales_invoice_stock
        from app.application_stock.engine.sle_writer import append_sle
        from app.application_stock.engine.replay import repost_from
        from app.application_stock.engine.bin_derive import derive_bin
        from app.application_stock.engine.locks import lock_pairs
        from app.application_accounting.engine.posting_service import PostingService, PostingContext
        from app.application_accounting.engine.errors import PostingValidationError
        from app.application_accounting.chart_of_accounts.models import JournalEntryTypeEnum, PartyTypeEnum

        # 1) Load & guard
        si = self.repo.get_si(si_id, for_update=False)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        V.guard_cancellable_state(si.doc_status)

        # Block if any non-cancelled returns exist against this invoice
        # (i.e., any SI with is_return=True linked to this SI that is not CANCELLED)
        has_active_returns = (self.s.execute(
            select(func.count()).select_from(SalesInvoice).where(
                SalesInvoice.return_against_id == si.id,
                SalesInvoice.is_return.is_(True),
                SalesInvoice.doc_status != DocStatusEnum.CANCELLED,
            )
        ).scalar() or 0) > 0
        if has_active_returns:
            raise V.BizValidationError("Cannot cancel: one or more Credit Notes/Returns exist against this invoice.")

        # 2) Compute the business posting instant (same rule used on submit)
        tz = get_company_timezone(self.s, si.company_id)
        posting_dt = resolve_posting_dt(
            si.posting_date.date(),  # treat as date if it was a midnight dt
            created_at=si.created_at,
            tz=tz,
            treat_midnight_as_date=True,
        )
        dt_id_si = self._get_doc_type_id_or_400("SALES_INVOICE")

        # 3) Prepare a small helper to cancel GL via PostingService.cancel with a fallback
        def _cancel_gl_or_fallback(_si_locked: SalesInvoice) -> None:
            ps = PostingService(self.s)
            ctx = PostingContext(
                company_id=_si_locked.company_id,
                branch_id=_si_locked.branch_id,
                source_doctype_id=dt_id_si,
                source_doc_id=_si_locked.id,
                posting_date=posting_dt,  # cancel() uses the original JE's date; this is just context
                created_by_id=context.user_id,
                is_auto_generated=True,
                entry_type=JournalEntryTypeEnum.AUTO,
                remarks=f"Cancellation of Sales Invoice {_si_locked.code}",
                # template_code/payload not needed for cancel()
            )
            try:
                ps.cancel(ctx)  # preferred: mirror reversal of the original AUTO JE
            except PostingValidationError:
                # No submitted auto journal found to cancel (e.g., legacy data or templates disabled)
                # Fallback: synthesize a reversal using finance-only template.
                # Note: If your original SI posted with-stock template, the cancel() path above is strongly preferred.
                rev_lines = [{"amount": -Decimal(str(it.amount)), "income_account_id": it.income_account_id} for it in
                             _si_locked.items]
                payload = {
                    "DOCUMENT_TOTAL": -Decimal(str(_si_locked.total_amount or 0)),
                    "DOCUMENT_SUBTOTAL": sum((Decimal(str(ln["amount"])) for ln in rev_lines), Decimal("0")),
                    "TAX_AMOUNT": -Decimal(str(_si_locked.vat_amount or 0)),
                    "income_splits": {int(ln["income_account_id"]): Decimal(str(ln["amount"])) for ln in rev_lines},
                }
                dyn_ctx = {
                    "accounts_receivable_account_id": _si_locked.debit_to_account_id,
                    "tax_account_id": _si_locked.vat_account_id,
                }
                # If the original had an inline receipt inside the same JE, cancel() would have reversed it.
                # In this fallback, include a negative AMOUNT_RECEIVED only if you know it was posted in the same JE.
                if Decimal(str(_si_locked.paid_amount or 0)) != Decimal(
                        "0") and _si_locked.mode_of_payment_id and _si_locked.cash_bank_account_id:
                    payload["AMOUNT_RECEIVED"] = -Decimal(str(_si_locked.paid_amount))
                    dyn_ctx.update({
                        "cash_bank_account_id": _si_locked.cash_bank_account_id,
                        "party_ledger_account_id": _si_locked.debit_to_account_id,
                    })

                ps.post(PostingContext(
                    company_id=_si_locked.company_id,
                    branch_id=_si_locked.branch_id,
                    source_doctype_id=dt_id_si,
                    source_doc_id=_si_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=JournalEntryTypeEnum.AUTO,
                    remarks=f"Fallback reversal for Sales Invoice {_si_locked.code}",
                    template_code="SALES_INV_AR",
                    payload=payload,
                    runtime_accounts={},
                    party_id=_si_locked.customer_id,
                    party_type=PartyTypeEnum.CUSTOMER,
                    dynamic_account_context=dyn_ctx,
                ))

        # 4) STOCK path (update_stock=True): reverse SLEs, replay if backdated, then cancel GL
        if si.update_stock:
            stock_lines = [{
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "base_uom_id": None,
                # reversal = receipt of the delivered quantity; pass positive magnitude (builder applies sign)
                "quantity": Decimal(str(abs(Decimal(str(it.quantity))))),
                "doc_row_id": it.id,
                "warehouse_id": it.warehouse_id,
            } for it in si.items if it.warehouse_id]

            intents = build_intents_for_sales_invoice_stock(
                company_id=si.company_id,
                branch_id=si.branch_id,
                posting_dt=posting_dt,
                doc_type_id=dt_id_si,
                doc_id=si.id,
                is_return=True,  # reversal → receipt
                lines=stock_lines,
                session=self.s,
            )

            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            is_backdated = self._detect_backdated(si.company_id, pairs, posting_dt)

            with self.s.begin_nested():
                # lock the SI row (double-check state) and the (item,wh) pairs during mutation
                si_locked = self.repo.get_si(si_id, for_update=True)
                V.guard_cancellable_state(si_locked.doc_status)

                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(self.s, intent, created_at_hint=si_locked.created_at, tz_hint=tz, batch_index=idx)

                if is_backdated:
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=si_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set(),
                        )

                for item_id, wh_id in pairs:
                    derive_bin(self.s, si_locked.company_id, item_id, wh_id)

                # Cancel the original JE (or fallback)
                _cancel_gl_or_fallback(si_locked)

                si_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(si_locked)

            self.s.commit()
            invalidate_all_core_reports_for_company(si.company_id, include_stock=True)
            return si

        # 5) Finance-only path (no stock): just cancel GL then mark cancelled
        with self.s.begin_nested():
            si_locked = self.repo.get_si(si_id, for_update=True)
            V.guard_cancellable_state(si_locked.doc_status)

            _cancel_gl_or_fallback(si_locked)

            si_locked.doc_status = DocStatusEnum.CANCELLED
            self.repo.save(si_locked)

        self.s.commit()
        invalidate_financial_reports_for_company(si.company_id)
        return si

    def create_credit_note(self, *, original_si_id: int, payload: SalesCreditNoteCreate, context: AffiliationContext) -> SalesInvoice:
        """ERPNext-style Credit Note (negative quantities; optional restock)."""
        try:
            # Fetch original
            original = self.repo.get_si_with_items(original_si_id)
            if not original or original.doc_status != DocStatusEnum.SUBMITTED or original.is_return:
                raise V.BizValidationError("Original Sales Invoice not found or not eligible.")

            # Date rule
            from app.business_validation.posting_date_validation import PostingDateValidator
            PostingDateValidator.validate_return_against_original(
                s=self.s, current_posting_date=payload.posting_date, original_document_date=original.posting_date,
                company_id=original.company_id,
            )

            # Branch/company scope
            if payload.branch_id is not None:
                branch_id = payload.branch_id
                company_id = self.repo.get_branch_company_id(branch_id)
                if company_id != original.company_id:
                    raise V.BizValidationError("Branch must belong to original invoice company.")
            else:
                branch_id = original.branch_id
                company_id = original.company_id
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            # Build lines using original rate and income account; negative qty
            orig_map = {it.id: it for it in original.items}
            # Prevent over-returns
            returned_map = self._get_already_returned_quantities([it.id for it in original.items])

            cn_items: List[SalesInvoiceItem] = []
            total_amount = Decimal("0")
            for ln in payload.items:
                orig = orig_map.get(ln.original_item_id)
                if not orig:
                    raise V.BizValidationError(f"Original item {ln.original_item_id} not found.")

                already = returned_map.get(ln.original_item_id, Decimal("0"))
                balance = Decimal(str(orig.quantity)) - already
                if Decimal(str(ln.return_qty)) > balance:
                    raise V.BizValidationError(f"Return qty exceeds remaining balance for item {orig.item_id}.")

                neg_qty = -abs(Decimal(str(ln.return_qty)))
                line_total = neg_qty * Decimal(str(orig.rate))
                total_amount += line_total

                cn_items.append(SalesInvoiceItem(
                    item_id=orig.item_id,
                    uom_id=orig.uom_id,
                    quantity=neg_qty,
                    rate=orig.rate,
                    warehouse_id=orig.warehouse_id if payload.update_stock else None,
                    income_account_id=orig.income_account_id,
                    return_against_item_id=orig.id,
                    remarks=ln.remarks
                ))

            code = self._generate_or_validate_code(self.SI_PREFIX, company_id, branch_id, payload.code, self.repo.code_exists_si)

            cn = SalesInvoice(
                company_id=company_id, branch_id=branch_id, created_by_id=context.user_id,
                customer_id=original.customer_id,
                debit_to_account_id=original.debit_to_account_id,
                code=code, posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT, update_stock=payload.update_stock, is_return=True,
                return_against_id=original.id,
                vat_account_id=original.vat_account_id, vat_rate=original.vat_rate, vat_amount=Decimal("0"),
                total_amount=total_amount, paid_amount=Decimal("0"), outstanding_amount=total_amount,
                remarks=payload.remarks, items=cn_items
            )
            self.repo.save(cn); self.s.commit()
            return cn

        except Exception:
            self.s.rollback()
            raise

    def submit_credit_note(self, *, cn_id: int, context: AffiliationContext) -> SalesInvoice:
        try:
            cn = self.repo.get_si(cn_id, for_update=False)
            if not cn or not cn.is_return:
                raise NotFound("Credit Note not found.")
            ensure_scope_by_ids(context=context, target_company_id=cn.company_id, target_branch_id=cn.branch_id)
            V.guard_submittable_state(cn.doc_status)

            tz = get_company_timezone(self.s, cn.company_id)
            posting_dt = resolve_posting_dt(cn.posting_date.date(), created_at=cn.created_at, tz=tz,
                                            treat_midnight_as_date=True)

            dt_id = self._get_doc_type_id_or_400("SALES_INVOICE")

            cogs_val = Decimal("0")
            if cn.update_stock:
                intents = build_intents_for_sales_invoice_stock(
                    company_id=cn.company_id, branch_id=cn.branch_id, posting_dt=posting_dt,
                    doc_type_id=dt_id, doc_id=cn.id, is_return=True,
                    lines=[{
                        "item_id": it.item_id, "uom_id": it.uom_id, "base_uom_id": None,
                        "quantity": it.quantity, "doc_row_id": it.id, "warehouse_id": it.warehouse_id
                    } for it in cn.items], session=self.s,
                )
                pairs = {(i.item_id, i.warehouse_id) for i in intents}
                is_backdated = self._detect_backdated(cn.company_id, pairs, posting_dt)

                with self.s.begin_nested():
                    cn_locked = self.repo.get_si(cn_id, for_update=True)
                    V.guard_submittable_state(cn_locked.doc_status)

                    with lock_pairs(self.s, pairs):
                        for idx, intent in enumerate(intents):
                            append_sle(self.s, intent, created_at_hint=cn_locked.created_at, tz_hint=tz,
                                       batch_index=idx)

                    if is_backdated:
                        for item_id, wh_id in pairs:
                            repost_from(self.s, cn_locked.company_id, item_id, wh_id, start_dt=posting_dt,
                                        exclude_doc_types=set())

                    for item_id, wh_id in pairs:
                        derive_bin(self.s, cn_locked.company_id, item_id, wh_id)

                    cogs_val = sum_cogs_from_intents(intents)

                    payload = build_gl_context_for_sales_invoice_with_stock(
                        debit_to_account_id=cn_locked.debit_to_account_id,
                        vat_account_id=cn_locked.vat_account_id,
                        total_amount=cn_locked.total_amount,
                        vat_amount=cn_locked.vat_amount,
                        lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in
                               cn_locked.items],
                        cogs_total=cogs_val,
                        is_return=True,
                        discount_amount=Decimal("0"),
                        round_off_positive=Decimal("0"),
                        round_off_negative=Decimal("0"),
                        default_ar_account_id=None,
                    )
                    ctx = PostingContext(
                        company_id=cn_locked.company_id, branch_id=cn_locked.branch_id,
                        source_doctype_id=dt_id, source_doc_id=cn_locked.id,
                        posting_date=posting_dt, created_by_id=context.user_id,
                        is_auto_generated=True, entry_type=None,
                        remarks=f"Sales Credit Note {cn_locked.code} (with restock)",
                        template_code="SALES_RETURN_CREDIT", payload=payload,
                        runtime_accounts={}, party_id=cn_locked.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                        dynamic_account_context={}
                    )
                    PostingService(self.s).post(ctx)

                    cn_locked.doc_status = DocStatusEnum.RETURNED
                    self.repo.save(cn_locked)
                self.s.commit()
                return cn

            # finance-only credit note (no restock)
            else:
                payload = build_gl_context_for_sales_invoice_finance_only(
                    debit_to_account_id=cn.debit_to_account_id,
                    vat_account_id=cn.vat_account_id,
                    total_amount=cn.total_amount,
                    vat_amount=cn.vat_amount,
                    lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in cn.items],
                )
                ctx = PostingContext(
                    company_id=cn.company_id, branch_id=cn.branch_id,
                    source_doctype_id=dt_id, source_doc_id=cn.id,
                    posting_date=posting_dt, created_by_id=context.user_id,
                    is_auto_generated=True, entry_type=None,
                    remarks=f"Sales Credit Note {cn.code}",
                    template_code="SALES_RETURN_CREDIT", payload=payload,
                    runtime_accounts={}, party_id=cn.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                    dynamic_account_context={}
                )
                PostingService(self.s).post(ctx)

                with self.s.begin_nested():
                    cn_locked = self.repo.get_si(cn_id, for_update=True)
                    V.guard_submittable_state(cn_locked.doc_status)
                    cn_locked.doc_status = DocStatusEnum.RETURNED
                    self.repo.save(cn_locked)
                self.s.commit()
                return cn

        except PostingValidationError as e:
            self.s.rollback()
            raise V.BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback()
            raise

    # ---------- helpers ----------
    def _get_already_returned_quantities(self, original_item_ids: List[int]) -> Dict[int, Decimal]:
        if not original_item_ids:
            return {}
        SI = SalesInvoice
        SII = SalesInvoiceItem
        stmt = (
            select(
                SII.return_against_item_id,
                func.sum(SII.quantity).label("total_returned")
            )
            .join(SI, SI.id == SII.invoice_id)
            .where(
                SII.return_against_item_id.in_(original_item_ids),
                SI.doc_status == DocStatusEnum.RETURNED,
                SI.is_return == True
            )
            .group_by(SII.return_against_item_id)
        )
        rows = self.s.execute(stmt).all()
        return {r.return_against_item_id: abs(Decimal(str(r.total_returned or 0))) for r in rows}
