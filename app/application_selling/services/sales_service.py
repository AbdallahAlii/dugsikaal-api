# app/application_selling/services/sales_service.py
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
from datetime import datetime

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict

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
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
from app.common.timezone.service import get_company_timezone

from app.application_selling.repository.sales_repo import SalesRepository
from app.application_selling.schemas import (
    DeliveryNoteCreate, DeliveryNoteUpdate,
    SalesInvoiceCreate, SalesInvoiceUpdate,
    SalesCreditNoteCreate
)
from app.application_selling.models import SalesDeliveryNote, SalesDeliveryNoteItem, SalesInvoice, SalesInvoiceItem

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

    # ------------------------------------------------------------------------
    # Delivery Note (Create / Update / Submit)
    # ------------------------------------------------------------------------
    def create_delivery_note(self, *, payload: DeliveryNoteCreate, context: AffiliationContext) -> SalesDeliveryNote:
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        # Posting date
        from app.business_validation.posting_date_validation import PostingDateValidator
        PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, company_id)

        # Basic validation
        wh_ids = [ln.warehouse_id for ln in payload.items]
        self._validate_party_and_warehouses(company_id=company_id, branch_id=branch_id, customer_id=payload.customer_id, warehouse_ids=wh_ids)

        # Item validation
        item_ids = [ln.item_id for ln in payload.items]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

        # UOM checks only for stock items; services never require UOM
        uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
        if uom_pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
            for item_id, uom_id in uom_pairs:
                if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                    raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

        code = self._generate_or_validate_code(self.DN_PREFIX, company_id, branch_id, payload.code, self.repo.code_exists_dn)

        dn_items = [SalesDeliveryNoteItem(
            item_id=ln.item_id, uom_id=ln.uom_id, warehouse_id=ln.warehouse_id,
            delivered_qty=ln.delivered_qty, unit_price=ln.unit_price, remarks=ln.remarks
        ) for ln in payload.items]

        dn = SalesDeliveryNote(
            company_id=company_id, branch_id=branch_id, created_by_id=context.user_id,
            customer_id=payload.customer_id,
            code=code, posting_date=payload.posting_date,
            doc_status=DocStatusEnum.DRAFT, is_return=False,
            remarks=payload.remarks, total_amount=Decimal("0"), items=dn_items
        )
        self.repo.save(dn); self.s.commit()
        return dn

    def update_delivery_note(self, *, dn_id: int, payload: DeliveryNoteUpdate, context: AffiliationContext) -> SalesDeliveryNote:
        dn = self.repo.get_dn(dn_id, for_update=True)
        if not dn:
            raise NotFound("Delivery Note not found.")
        ensure_scope_by_ids(context=context, target_company_id=dn.company_id, target_branch_id=dn.branch_id)
        V.guard_draft_only(dn.doc_status)

        if payload.posting_date:
            from app.business_validation.posting_date_validation import PostingDateValidator
            PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, dn.company_id)
            dn.posting_date = payload.posting_date

        if payload.customer_id:
            self._validate_party_and_warehouses(
                company_id=dn.company_id, branch_id=dn.branch_id,
                customer_id=payload.customer_id, warehouse_ids=[l.warehouse_id for l in dn.items]
            )
            dn.customer_id = payload.customer_id

        if payload.remarks is not None:
            dn.remarks = payload.remarks

        if payload.items is not None:
            # Re-validate lines
            item_ids = [ln.item_id for ln in payload.items]
            details = self.repo.get_item_details_batch(dn.company_id, item_ids)
            V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

            uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
            if uom_pairs:
                compat = self.repo.get_compatible_uom_pairs(dn.company_id, uom_pairs)
                for item_id, uom_id in uom_pairs:
                    if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                        raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

            lines = [dict(
                id=ln.id,
                item_id=ln.item_id,
                uom_id=ln.uom_id,
                warehouse_id=ln.warehouse_id,
                delivered_qty=ln.delivered_qty,
                unit_price=ln.unit_price,
                remarks=ln.remarks
            ) for ln in payload.items]
            self.repo.sync_dn_lines(dn, lines)

        self.repo.save(dn); self.s.commit()
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
    def create_sales_invoice(self, *, payload: SalesInvoiceCreate, context: AffiliationContext) -> SalesInvoice:
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        from app.business_validation.posting_date_validation import PostingDateValidator
        PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, company_id)

        # Party & wh validation (wh only for lines that set it)
        self._validate_party_and_warehouses(
            company_id=company_id, branch_id=branch_id, customer_id=payload.customer_id,
            warehouse_ids=[ln.warehouse_id for ln in payload.items if ln.warehouse_id]
        )

        item_ids = [ln.item_id for ln in payload.items]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

        # UOM compatibility only for stock items (services do not require UOM at all)
        uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
        if uom_pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
            for item_id, uom_id in uom_pairs:
                if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                    raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

        # Resolve line income accounts
        group_defaults = self.repo.get_item_group_defaults(list({details[i]["item_group_id"] for i in item_ids if details.get(i)}))
        invoice_items: List[SalesInvoiceItem] = []
        subtotal = Decimal("0")
        for ln in payload.items:
            det = details.get(ln.item_id, {})
            income_acc = self._resolve_income_account_id(company_id, det, group_defaults, ln.income_account_id)

            # If update_stock=True, require warehouse only for STOCK items
            warehouse_id = ln.warehouse_id
            if payload.update_stock and det.get("is_stock_item", False) and not warehouse_id:
                raise V.BizValidationError("Stock items require warehouse_id when update_stock=True.")

            inv_line = SalesInvoiceItem(
                item_id=ln.item_id, uom_id=ln.uom_id,
                quantity=ln.quantity, rate=ln.rate,
                warehouse_id=warehouse_id if payload.update_stock and det.get("is_stock_item", False) else None,
                income_account_id=income_acc,
                delivery_note_item_id=ln.delivery_note_item_id if payload.delivery_note_id else None,
                remarks=ln.remarks
            )
            invoice_items.append(inv_line)
            subtotal += Decimal(str(ln.quantity)) * Decimal(str(ln.rate))

        debit_to = payload.debit_to_account_id or self.repo.get_default_receivable_account(company_id)
        code = self._generate_or_validate_code(self.SI_PREFIX, company_id, branch_id, payload.code, self.repo.code_exists_si)

        total_amount = subtotal + (payload.vat_amount or Decimal("0"))

        si = SalesInvoice(
            company_id=company_id, branch_id=branch_id, created_by_id=context.user_id,
            customer_id=payload.customer_id,
            debit_to_account_id=debit_to,
            code=code, posting_date=payload.posting_date,
            doc_status=DocStatusEnum.DRAFT, update_stock=payload.update_stock, is_return=False,
            vat_account_id=payload.vat_account_id, vat_rate=payload.vat_rate, vat_amount=payload.vat_amount or Decimal("0"),
            total_amount=total_amount, paid_amount=Decimal("0"), outstanding_amount=total_amount,
            due_date=payload.due_date, remarks=payload.remarks,
            items=invoice_items
        )
        self.repo.save(si); self.s.commit()
        return si

    def update_sales_invoice(self, *, si_id: int, payload: SalesInvoiceUpdate, context: AffiliationContext) -> SalesInvoice:
        si = self.repo.get_si(si_id, for_update=True)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        if si.doc_status != DocStatusEnum.DRAFT:
            raise V.BizValidationError("Only draft Sales Invoices can be updated.")

        if payload.posting_date:
            from app.business_validation.posting_date_validation import PostingDateValidator
            PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, si.company_id)
            si.posting_date = payload.posting_date

        if payload.customer_id:
            self._validate_party_and_warehouses(
                company_id=si.company_id, branch_id=si.branch_id,
                customer_id=payload.customer_id, warehouse_ids=[l.warehouse_id for l in si.items if l.warehouse_id]
            )
            si.customer_id = payload.customer_id

        if payload.debit_to_account_id is not None:
            si.debit_to_account_id = payload.debit_to_account_id

        if payload.vat_account_id is not None:
            si.vat_account_id = payload.vat_account_id
        if payload.vat_rate is not None:
            si.vat_rate = payload.vat_rate
        if payload.vat_amount is not None:
            if payload.vat_amount > 0 and not si.vat_account_id:
                raise V.BizValidationError("VAT account is required when VAT amount > 0.")
            si.vat_amount = payload.vat_amount

        if payload.due_date is not None:
            si.due_date = payload.due_date
        if payload.remarks is not None:
            si.remarks = payload.remarks

        # Replace lines if provided
        if payload.items is not None:
            item_ids = [ln.item_id for ln in payload.items]
            details = self.repo.get_item_details_batch(si.company_id, item_ids)
            V.validate_items_are_active([(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids])

            # UOM checks only for stock items
            uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
            if uom_pairs:
                compat = self.repo.get_compatible_uom_pairs(si.company_id, uom_pairs)
                for item_id, uom_id in uom_pairs:
                    if details.get(item_id, {}).get("is_stock_item", False) and (item_id, uom_id) not in compat:
                        raise V.BizValidationError(f"UOM not compatible for item_id={item_id}")

            # Resolve income accounts again
            group_defaults = self.repo.get_item_group_defaults(list({details[i]["item_group_id"] for i in item_ids if details.get(i)}))

            lines: List[Dict] = []
            subtotal = Decimal("0")
            for ln in payload.items:
                det = details.get(ln.item_id, {})
                inc = self._resolve_income_account_id(si.company_id, det, group_defaults, ln.income_account_id)

                w = ln.warehouse_id
                if si.update_stock and det.get("is_stock_item", False) and not w:
                    raise V.BizValidationError("Stock items require warehouse_id when update_stock=True.")

                lines.append(dict(
                    id=ln.id, item_id=ln.item_id, uom_id=ln.uom_id,
                    quantity=ln.quantity, rate=ln.rate, amount=Decimal(str(ln.quantity))*Decimal(str(ln.rate)),
                    warehouse_id=w if si.update_stock and det.get("is_stock_item", False) else None,
                    income_account_id=inc, remarks=ln.remarks
                ))
                subtotal += Decimal(str(ln.quantity)) * Decimal(str(ln.rate))

            self.repo.sync_si_lines(si, lines)

            # recompute totals
            si.total_amount = subtotal + (si.vat_amount or Decimal("0"))
            si.outstanding_amount = si.total_amount - si.paid_amount

        self.repo.save(si); self.s.commit()
        return si

    def submit_sales_invoice(self, *, si_id: int, context: AffiliationContext) -> SalesInvoice:
        """
        Submit a Sales Invoice (ERP style).
        - If update_stock=True: issues stock (COGS) and income.
        - If paid_amount>0: auto-posts a Receipt Entry (DR bank/cash, CR A/R).
        - Sets doc_status to UNPAID / PARTIALLY_PAID / PAID accordingly.
        """
        from decimal import Decimal as D, ROUND_HALF_UP

        def _D(x) -> D:
            return D(str(x or 0)).quantize(D("0.0001"), rounding=ROUND_HALF_UP)

        def _derive_payment_status(total: D, paid: D) -> DocStatusEnum:
            if paid <= D("0.0000"):
                return DocStatusEnum.UNPAID
            if paid + D("0.0000") >= total:
                return DocStatusEnum.PAID
            return DocStatusEnum.PARTIALLY_PAID

        # ---- 1) READ (no locks) --------------------------------------------------
        si = self.repo.get_si(si_id, for_update=False)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        V.guard_submittable_state(si.doc_status)
        if not si.items:
            raise V.BizValidationError("No items to submit.")

        tz = get_company_timezone(self.s, si.company_id)
        posting_dt = resolve_posting_dt(
            si.posting_date.date(), created_at=si.created_at, tz=tz, treat_midnight_as_date=True
        )
        dt_id_si = self._get_doc_type_id_or_400("SALES_INVOICE")

        # Money figures
        total_amount = _D(si.total_amount)
        paid_amount = _D(si.paid_amount)
        vat_amount = _D(si.vat_amount)
        subtotal = _D(sum(Decimal(str(it.amount)) for it in si.items))

        # Income splits (per income account)
        income_splits: Dict[int, D] = {}
        for it in si.items:
            acc_id = int(it.income_account_id)
            income_splits[acc_id] = income_splits.get(acc_id, D("0")) + _D(it.amount)

        # ---- 2) STOCK (if update_stock) ------------------------------------------
        if si.update_stock:
            # Only stock lines have a warehouse_id; service lines must not
            stock_lines = [{
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "base_uom_id": None,
                "quantity": it.quantity,
                "doc_row_id": it.id,
                "warehouse_id": it.warehouse_id
            } for it in si.items if it.warehouse_id]

            intents = build_intents_for_sales_invoice_stock(
                company_id=si.company_id,
                branch_id=si.branch_id,
                posting_dt=posting_dt,
                doc_type_id=dt_id_si,
                doc_id=si.id,
                is_return=False,
                lines=stock_lines,
                session=self.s
            )
            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            is_backdated = self._detect_backdated(si.company_id, pairs, posting_dt)

            with self.s.begin_nested():
                si_locked = self.repo.get_si(si_id, for_update=True)
                V.guard_submittable_state(si_locked.doc_status)

                # Append SLEs
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(
                            self.s, intent, created_at_hint=si_locked.created_at, tz_hint=tz, batch_index=idx
                        )

                # Repost forward if backdated
                if is_backdated:
                    for item_id, wh_id in pairs:
                        repost_from(
                            self.s, si_locked.company_id, item_id, wh_id, start_dt=posting_dt, exclude_doc_types=set()
                        )

                # Refresh BIN
                for item_id, wh_id in pairs:
                    derive_bin(self.s, si_locked.company_id, item_id, wh_id)

                # COGS value from intents
                cogs_val = sum_cogs_from_intents(intents)

                # ---- 3) GL for SI (with stock) ------------------------------------
                payload = build_gl_context_for_sales_invoice_with_stock(
                    debit_to_account_id=si_locked.debit_to_account_id,
                    vat_account_id=si_locked.vat_account_id,
                    total_amount=si_locked.total_amount,
                    vat_amount=si_locked.vat_amount,
                    lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si_locked.items],
                    cogs_total=cogs_val,
                    is_return=False,
                    discount_amount=Decimal("0"),
                    round_off_positive=Decimal("0"),
                    round_off_negative=Decimal("0"),
                    default_ar_account_id=None,
                )
                payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
                payload["document_subtotal"] = subtotal
                payload["document_total"] = total_amount
                payload["tax_amount"] = vat_amount

                ctx = PostingContext(
                    company_id=si_locked.company_id, branch_id=si_locked.branch_id,
                    source_doctype_id=dt_id_si, source_doc_id=si_locked.id,
                    posting_date=posting_dt, created_by_id=context.user_id,
                    is_auto_generated=True, entry_type=None,
                    remarks=f"Sales Invoice {si_locked.code} (with stock)",
                    template_code="SALES_INV_WITH_STOCK",
                    payload=payload,
                    runtime_accounts={},
                    party_id=si_locked.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                    # provide AR account for template dynamic account
                    dynamic_account_context={"accounts_receivable_account_id": si_locked.debit_to_account_id}
                )
                PostingService(self.s).post(ctx)

                # ---- 4) Auto-Receipt (if paid_amount > 0) -------------------------
                if paid_amount > Decimal("0"):
                    if not si_locked.mode_of_payment_id or not si_locked.cash_bank_account_id:
                        raise V.BizValidationError(
                            "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                        )
                    # ✅ Corrected to match GL templates you seeded
                    dt_id_payment = self._get_doc_type_id_or_400("PAYMENT_ENTRY")
                    receipt_payload = {
                        "AMOUNT_RECEIVED": float(paid_amount)  # PostingService also accepts amount sources overlay
                    }
                    ctx_rcpt = PostingContext(
                        company_id=si_locked.company_id, branch_id=si_locked.branch_id,
                        source_doctype_id=dt_id_payment, source_doc_id=si_locked.id,  # linked to SI
                        posting_date=posting_dt, created_by_id=context.user_id,
                        is_auto_generated=True, entry_type=None,
                        remarks=f"Receipt on {si_locked.code}",
                        template_code="PAYMENT_RECEIVE",
                        payload=receipt_payload,
                        runtime_accounts={},
                        party_id=si_locked.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                        dynamic_account_context={
                            "cash_bank_account_id": si_locked.cash_bank_account_id,   # DR
                            "party_ledger_account_id": si_locked.debit_to_account_id  # CR (A/R)
                        }
                    )
                    PostingService(self.s).post(ctx_rcpt)

                # ---- 5) Set status (UNPAID / PARTIALLY_PAID / PAID) ---------------
                new_status = _derive_payment_status(total_amount, paid_amount)
                si_locked.doc_status = new_status
                self.repo.save(si_locked)

            self.s.commit()
            return si

        # ---- Finance-only path (no stock) ----------------------------------------
        payload = build_gl_context_for_sales_invoice_finance_only(
            debit_to_account_id=si.debit_to_account_id,
            vat_account_id=si.vat_account_id,
            total_amount=si.total_amount,
            vat_amount=si.vat_amount,
            lines=[{"amount": it.amount, "income_account_id": it.income_account_id} for it in si.items],
            discount_amount=Decimal("0"),
            round_off_positive=Decimal("0"),
            round_off_negative=Decimal("0"),
            default_ar_account_id=None,
        )
        payload["income_splits"] = {int(k): _D(v) for k, v in income_splits.items()}
        payload["document_subtotal"] = subtotal
        payload["document_total"] = total_amount
        payload["tax_amount"] = vat_amount

        ctx = PostingContext(
            company_id=si.company_id, branch_id=si.branch_id,
            source_doctype_id=dt_id_si, source_doc_id=si.id,
            posting_date=posting_dt, created_by_id=context.user_id,
            is_auto_generated=True, entry_type=None,
            remarks=f"Sales Invoice {si.code}",
            template_code="SALES_INV_AR",
            payload=payload,
            runtime_accounts={},
            party_id=si.customer_id, party_type=PartyTypeEnum.CUSTOMER,
            dynamic_account_context={"accounts_receivable_account_id": si.debit_to_account_id}
        )
        PostingService(self.s).post(ctx)

        with self.s.begin_nested():
            si_locked = self.repo.get_si(si_id, for_update=True)
            V.guard_submittable_state(si_locked.doc_status)

            # Auto-Receipt if paid now
            if _D(si_locked.paid_amount) > Decimal("0"):
                if not si_locked.mode_of_payment_id or not si_locked.cash_bank_account_id:
                    raise V.BizValidationError(
                        "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                    )
                dt_id_payment = self._get_doc_type_id_or_400("PAYMENT_ENTRY")
                receipt_payload = {"AMOUNT_RECEIVED": float(_D(si_locked.paid_amount))}
                ctx_rcpt = PostingContext(
                    company_id=si_locked.company_id, branch_id=si_locked.branch_id,
                    source_doctype_id=dt_id_payment, source_doc_id=si_locked.id,
                    posting_date=posting_dt, created_by_id=context.user_id,
                    is_auto_generated=True, entry_type=None,
                    remarks=f"Receipt on {si_locked.code}",
                    template_code="PAYMENT_RECEIVE",
                    payload=receipt_payload,
                    runtime_accounts={},
                    party_id=si_locked.customer_id, party_type=PartyTypeEnum.CUSTOMER,
                    dynamic_account_context={
                        "cash_bank_account_id": si_locked.cash_bank_account_id,   # DR
                        "party_ledger_account_id": si_locked.debit_to_account_id  # CR (A/R)
                    }
                )
                PostingService(self.s).post(ctx_rcpt)

            # Status based on paid vs total
            new_status = _derive_payment_status(_D(si_locked.total_amount), _D(si_locked.paid_amount))
            si_locked.doc_status = new_status
            self.repo.save(si_locked)

        self.s.commit()
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
