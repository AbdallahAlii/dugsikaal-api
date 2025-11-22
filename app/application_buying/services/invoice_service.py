# app/application_buying/invoice_service.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set, Any
from decimal import Decimal
from datetime import datetime, timezone
import logging

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, BadRequest, Forbidden

from config.database import db
from app.application_buying.schemas import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceUpdate,
)
from app.application_buying.repository.invoice_repo import PurchaseInvoiceRepository
from app.application_buying.models import PurchaseInvoice, PurchaseInvoiceItem, PurchaseReceipt
from app.application_stock.stock_models import DocStatusEnum, DocumentType, StockLedgerEntry
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.handlers.purchase import (
    build_intents_for_receipt,
    build_intents_for_return,
)
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.bin_derive import derive_bin
from app.application_accounting.chart_of_accounts.models import FiscalYear
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation import item_validation as V

from app.security.rbac_guards import resolve_company_branch_and_scope, ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext

logger = logging.getLogger(__name__)


class PurchaseInvoiceService:
    PREFIX = "PINV"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseInvoiceRepository(self.s)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _generate_or_validate_code(self, company_id: int, branch_id: int, code: Optional[str]) -> str:
        from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump

        if code:
            c = code.strip()
            if self.repo.code_exists(company_id, branch_id, c):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=c
            )
            return c
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(
        self,
        company_id: int,
        branch_id: int,
        supplier_id: int,
        header_wh_id: Optional[int],
        update_stock: bool,
    ) -> None:
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)

        if update_stock and header_wh_id:
            valid = self.repo.get_transactional_warehouse_ids(
                company_id, branch_id, [header_wh_id]
            )
            V.validate_warehouse_is_transactional(header_wh_id in valid)

    def _autofill_line_warehouse(
        self, header_wh_id: Optional[int], update_stock: bool, lines: List[Dict]
    ) -> None:
        if not update_stock or not header_wh_id:
            return
        for ln in lines:
            if ln.get("warehouse_id") is None:
                ln["warehouse_id"] = header_wh_id

    def _validate_and_normalize_lines(
        self, company_id: int, lines: List[Dict], is_return: bool
    ) -> List[Dict]:
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        work = [{**ln, **details.get(ln["item_id"], {})} for ln in lines]
        V.validate_items_are_active(
            [(ln["item_id"], ln.get("is_active", False)) for ln in work]
        )

        # Stock validation only needed if later we decide update_stock=True
        uoms = [ln["uom_id"] for ln in work if ln.get("uom_id")]
        if uoms:
            existing = self.repo.get_existing_uom_ids(company_id, uoms)
            V.validate_uoms_exist([(u, u in existing) for u in uoms])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in work if ln.get("uom_id")]
        if pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, pairs)
            for ln in work:
                if ln.get("uom_id"):
                    ln["uom_ok"] = (ln["item_id"], ln["uom_id"]) in compat
            # Only stock items need compatibility check
            V.validate_item_uom_compatibility(
                [ln for ln in work if ln.get("is_stock_item", False)]
            )

        for ln in work:
            if is_return:
                if Decimal(str(ln["quantity"])) >= 0:
                    raise V.BizValidationError(
                        "Return lines must have negative quantity."
                    )
            else:
                V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln.get("rate"))
            V.validate_positive_price(ln.get("rate"))

        out: List[Dict] = []
        for ln in work:
            x = {
                "item_id": ln["item_id"],
                "uom_id": ln.get("uom_id"),
                "quantity": ln["quantity"],
                "rate": ln["rate"],
                "remarks": ln.get("remarks"),
                "receipt_item_id": ln.get("receipt_item_id"),
                "warehouse_id": ln.get("warehouse_id"),
                "return_against_item_id": ln.get("return_against_item_id"),
            }
            out.append(x)
        return out

    def _calculate_total(self, company_id: int, lines: List[Dict]) -> Decimal:
        from app.application_nventory.services.uom_math import (
            to_base_qty,
            UOMFactorMissing,
        )

        total = Decimal("0")
        for ln in lines:
            rate = Decimal(str(ln["rate"]))
            qty = Decimal(str(ln["quantity"]))
            item_id = ln["item_id"]
            uom_id = ln.get("uom_id")
            detail = self.repo.get_item_details_batch(company_id, [item_id]).get(
                item_id, {}
            )
            base = detail.get("base_uom_id")
            is_stock = detail.get("is_stock_item", False)

            if not is_stock or not base or not uom_id or uom_id == base:
                total += qty * rate
            else:
                try:
                    base_qty_float, _ = to_base_qty(
                        qty=abs(qty),
                        item_id=item_id,
                        uom_id=uom_id,
                        base_uom_id=base,
                        strict=True,
                    )
                    base_qty = Decimal(str(base_qty_float))
                    if qty < 0:
                        base_qty = -base_qty
                    total += base_qty * rate
                except UOMFactorMissing:
                    total += qty * rate
        return total

    def _enforce_line_warehouses_if_stock(
        self, update_stock: bool, lines: List[Dict], header_wh_id: Optional[int]
    ) -> None:
        if not update_stock:
            return
        for ln in lines:
            if ln.get("warehouse_id") is None:
                # try header fallback
                if header_wh_id:
                    ln["warehouse_id"] = header_wh_id
            if ln.get("warehouse_id") is None:
                raise V.BizValidationError(
                    "Warehouse is required on each stock line before submit (update_stock=True)."
                )

    def _coerce_signed_paid_for_return(
        self, is_return: bool, raw_paid: Optional[Decimal]
    ) -> Decimal:
        """
        ERPNext-style sign convention:

        - Normal PI: paid_amount >= 0 (we pay supplier).
        - Return PI (debit note): paid_amount <= 0 (supplier pays/refunds us).

        If caller passes wrong sign, we coerce to the correct one.
        """
        paid = Decimal(str(raw_paid or 0))
        zero = Decimal("0")

        if not is_return:
            # normal invoice: never negative
            if paid < zero:
                paid = -paid
            return paid

        # return / debit note: never positive
        if paid > zero:
            paid = -paid
        return paid

    def _get_already_returned_quantities(
        self, original_item_ids: List[int]
    ) -> Dict[int, Decimal]:
        """
        Sum of already-returned quantities per original PurchaseInvoiceItem.id.

        Returns a dict: {original_item_id: abs(returned_qty)}
        """
        if not original_item_ids:
            return {}

        rows = (
            self.s.execute(
                select(
                    PurchaseInvoiceItem.return_against_item_id,
                    func.sum(PurchaseInvoiceItem.quantity),
                )
                .join(
                    PurchaseInvoice,
                    PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id,
                )
                .where(
                    PurchaseInvoiceItem.return_against_item_id.in_(original_item_ids),
                    PurchaseInvoice.is_return == True,  # noqa: E712
                    PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED,
                )
                .group_by(PurchaseInvoiceItem.return_against_item_id)
            ).all()
        )

        out: Dict[int, Decimal] = {}
        for orig_id, qty_sum in rows:
            if orig_id is None:
                continue
            qty_dec = Decimal(str(qty_sum or 0))
            out[orig_id] = abs(qty_dec)
        return out

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------
    def create_purchase_invoice(
        self, *, payload: PurchaseInvoiceCreate, context: AffiliationContext
    ) -> PurchaseInvoice:
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
        original_pi: Optional[PurchaseInvoice] = None
        if payload.is_return:
            if not payload.return_against_id:
                raise V.BizValidationError(
                    "Return Against is required for a return Purchase Invoice."
                )

            original_pi = self.repo.get_original_for_return(payload.return_against_id)
            if not original_pi:
                raise V.BizValidationError(
                    "Original Purchase Invoice not found or not eligible for return."
                )

            if original_pi.is_return:
                raise V.BizValidationError(
                    "Cannot create a return against a return Purchase Invoice."
                )

            # Posting date relative to original
            PostingDateValidator.validate_return_against_original(
                s=self.s,
                current_posting_date=payload.posting_date,
                original_document_date=original_pi.posting_date,
                company_id=original_pi.company_id,
            )

            # Same company
            if company_id != original_pi.company_id:
                raise V.BizValidationError(
                    "Return must belong to the same company as the original Purchase Invoice."
                )

            # Same branch company
            branch_company = self.repo.get_branch_company_id(branch_id)
            if branch_company != original_pi.company_id:
                raise V.BizValidationError(
                    "Branch must belong to the same company as the original Purchase Invoice."
                )

            # Supplier must match
            if payload.supplier_id != original_pi.supplier_id:
                raise V.BizValidationError(
                    "Return supplier must match the original Purchase Invoice supplier."
                )

            # Scope on original branch as well
            ensure_scope_by_ids(
                context=context,
                target_company_id=original_pi.company_id,
                target_branch_id=original_pi.branch_id,
            )

        # 4) Header checks (supplier + header warehouse)
        self._validate_header(
            company_id,
            branch_id,
            payload.supplier_id,
            payload.warehouse_id,
            payload.update_stock,
        )

        # 5) Lines basic validation + UOM compat + direction (via is_return)
        lines = [ln.model_dump() for ln in payload.items]
        self._autofill_line_warehouse(payload.warehouse_id, payload.update_stock, lines)
        norm_lines = self._validate_and_normalize_lines(
            company_id, lines, is_return=payload.is_return
        )

        # 6) If against receipt (normal PI only), enforce rate and quantity limits
        if payload.receipt_id and not payload.is_return:
            receipt = self.repo.get_receipt_with_items(payload.receipt_id)
            if not receipt:
                raise V.BizValidationError(
                    "Purchase Receipt not found or not submitted."
                )
            if receipt.company_id != company_id or receipt.branch_id != branch_id:
                raise V.BizValidationError(
                    "Receipt belongs to a different company/branch."
                )
            if receipt.supplier_id != payload.supplier_id:
                raise V.BizValidationError(
                    "Invoice supplier must match the receipt supplier."
                )

            valid_receipt_items = {it.id for it in receipt.items}
            rec_map = {it.id: it for it in receipt.items}

            # compute already billed for each receipt_item_id (excluding CANCELLED)
            rows = (
                self.s.execute(
                    select(
                        PurchaseInvoiceItem.receipt_item_id,
                        func.sum(PurchaseInvoiceItem.quantity),
                    )
                    .join(
                        PurchaseInvoice,
                        PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id,
                    )
                    .where(
                        PurchaseInvoiceItem.receipt_item_id.in_(valid_receipt_items),
                        PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED,
                    )
                    .group_by(PurchaseInvoiceItem.receipt_item_id)
                ).all()
            )
            billed_map: Dict[int, Decimal] = {
                rid: Decimal(str(qty or 0)) for rid, qty in rows
            }

            for ln in norm_lines:
                rid = ln.get("receipt_item_id")
                if rid:
                    if rid not in valid_receipt_items:
                        raise V.BizValidationError(
                            f"receipt_item_id {rid} does not belong to receipt {payload.receipt_id}."
                        )
                    rec_it = rec_map[rid]
                    # Rate must match PR rate
                    if Decimal(str(ln["rate"])) != Decimal(
                        str(rec_it.unit_price or 0)
                    ):
                        raise V.BizValidationError(
                            "When billing against receipt, item rate must match the receipt item rate."
                        )
                    # Quantity cannot exceed accepted - already billed
                    already = billed_map.get(rid, Decimal("0"))
                    available = Decimal(str(rec_it.accepted_qty)) - already
                    if Decimal(str(ln["quantity"])) > available:
                        raise V.BizValidationError(
                            f"Over-billing: {ln['quantity']} > available {available} for receipt item {rid}."
                        )

        # 7) Over-return protection (if this is a RETURN)
        if payload.is_return and original_pi is not None:
            orig_lines_map = {it.id: it for it in original_pi.items}
            returned_map = self._get_already_returned_quantities(
                list(orig_lines_map.keys())
            )

            for idx, ln in enumerate(norm_lines, start=1):
                orig_line_id = ln.get("return_against_item_id")
                if not orig_line_id or orig_line_id not in orig_lines_map:
                    raise V.BizValidationError(
                        f"Row #{idx}: return_against_item_id is required and must reference an original invoice row."
                    )

                orig_line = orig_lines_map[orig_line_id]
                already = returned_map.get(orig_line_id, Decimal("0"))
                orig_qty = Decimal(str(orig_line.quantity))  # original is positive
                remaining = orig_qty - already

                if remaining <= Decimal("0"):
                    item_label = getattr(
                        getattr(orig_line, "item", None), "name", str(orig_line.item_id)
                    )
                    raise V.BizValidationError(
                        f"Row #{idx}: Item {item_label} has already been fully returned."
                    )

                requested_abs = abs(Decimal(str(ln["quantity"])))  # ln["quantity"] is negative
                if requested_abs > remaining:
                    item_label = getattr(
                        getattr(orig_line, "item", None), "name", str(orig_line.item_id)
                    )
                    raise V.BizValidationError(
                        f"Row #{idx}: Cannot return more than {remaining} for Item {item_label}."
                    )

        # 8) Code, totals, payment
        code = self._generate_or_validate_code(company_id, branch_id, payload.code)
        total = self._calculate_total(company_id, norm_lines)

        paid_amount = self._coerce_signed_paid_for_return(
            payload.is_return, payload.paid_amount
        )
        V.validate_payment_consistency(
            paid_amount,
            payload.mode_of_payment_id,
            payload.cash_bank_account_id,
        )

        pi_items = [PurchaseInvoiceItem(**ln) for ln in norm_lines]

        pi = PurchaseInvoice(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=context.user_id,
            supplier_id=payload.supplier_id,
            warehouse_id=payload.warehouse_id if payload.update_stock else None,
            code=code,
            posting_date=norm_dt,
            doc_status=DocStatusEnum.DRAFT,
            is_return=payload.is_return,
            return_against_id=payload.return_against_id if payload.is_return else None,
            update_stock=payload.update_stock,
            payable_account_id=payload.payable_account_id,
            mode_of_payment_id=payload.mode_of_payment_id,
            cash_bank_account_id=payload.cash_bank_account_id,
            due_date=payload.due_date,
            receipt_id=payload.receipt_id if not payload.is_return else None,
            total_amount=total,
            paid_amount=paid_amount,
            outstanding_amount=total - paid_amount,
            remarks=payload.remarks,
            items=pi_items,
        )
        self.repo.save(pi)
        self.s.commit()
        return pi

    # -------------------------------------------------------------------------
    # UPDATE
    # -------------------------------------------------------------------------
    def update_purchase_invoice(
        self, *, invoice_id: int, payload: PurchaseInvoiceUpdate, context: AffiliationContext
    ) -> PurchaseInvoice:
        pi = self.repo.get_by_id(invoice_id, for_update=True)
        if not pi:
            raise NotFound("Purchase Invoice not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=pi.company_id,
            target_branch_id=pi.branch_id,
        )

        # Only DRAFT updatable
        from app.business_validation.item_validation import guard_updatable_state

        guard_updatable_state(pi.doc_status)

        # Header updates
        if payload.posting_date is not None:
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s,
                payload.posting_date,
                pi.company_id,
                created_at=None,
                treat_midnight_as_date=True,
            )
            pi.posting_date = norm_dt

        if payload.supplier_id is not None and payload.supplier_id != pi.supplier_id:
            # For safety, do not allow changing supplier on a return
            if pi.is_return:
                raise V.BizValidationError(
                    "Cannot change supplier on a return Purchase Invoice."
                )
            valid = self.repo.get_valid_supplier_ids(pi.company_id, [payload.supplier_id])
            V.validate_supplier_is_active(payload.supplier_id in valid)
            pi.supplier_id = payload.supplier_id

        if payload.update_stock is not None:
            # You can toggle while draft, but if it becomes True we'll enforce warehouses at submit.
            pi.update_stock = bool(payload.update_stock)

        if payload.warehouse_id is not None:
            if payload.warehouse_id and pi.update_stock:
                valid_wh = self.repo.get_transactional_warehouse_ids(
                    pi.company_id, pi.branch_id, [payload.warehouse_id]
                )
                V.validate_warehouse_is_transactional(
                    payload.warehouse_id in valid_wh
                )
            pi.warehouse_id = payload.warehouse_id

        if payload.due_date is not None:
            pi.due_date = payload.due_date

        if payload.remarks is not None:
            pi.remarks = payload.remarks

        # Payment fields
        if payload.mode_of_payment_id is not None:
            pi.mode_of_payment_id = payload.mode_of_payment_id
        if payload.cash_bank_account_id is not None:
            pi.cash_bank_account_id = payload.cash_bank_account_id
        if payload.paid_amount is not None:
            pi.paid_amount = self._coerce_signed_paid_for_return(
                pi.is_return, payload.paid_amount
            )

        # Lines
        if payload.items is not None:
            lines_in = [it.model_dump() for it in payload.items]

            # Direction by pi.is_return
            for ln in lines_in:
                q = Decimal(str(ln["quantity"]))
                if pi.is_return:
                    if q >= 0:
                        raise V.BizValidationError(
                            "Return Invoice items must have negative quantity."
                        )
                else:
                    if q <= 0:
                        raise V.BizValidationError(
                            "Normal Invoice items must have positive quantity."
                        )

            V.validate_list_not_empty(lines_in, "items")
            V.validate_unique_items(lines_in, key="item_id")

            details = self.repo.get_item_details_batch(
                pi.company_id, [x["item_id"] for x in lines_in]
            )
            V.validate_items_are_active(
                [
                    (x["item_id"], details.get(x["item_id"], {}).get("is_active", False))
                    for x in lines_in
                ]
            )
            for x in lines_in:
                # magnitude > 0
                V.validate_positive_quantity(abs(Decimal(str(x["quantity"]))))
                V.validate_non_negative_rate(x.get("rate"))
                V.validate_positive_price(x.get("rate"))

            # If this PI is against a receipt, enforce rate=PR rate and qty <= remaining (excluding this PI itself)
            if pi.receipt_id and not pi.is_return:
                r = self.repo.get_receipt_with_items(pi.receipt_id)
                if not r:
                    raise V.BizValidationError(
                        "Linked Purchase Receipt not found or not submitted."
                    )
                rec_map = {it.id: it for it in r.items}
                valid_receipt_items = set(rec_map.keys())

                # sum billed qty on other invoices
                rows = (
                    self.s.execute(
                        select(
                            PurchaseInvoiceItem.receipt_item_id,
                            func.sum(PurchaseInvoiceItem.quantity),
                        )
                        .join(
                            PurchaseInvoice,
                            PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id,
                        )
                        .where(
                            PurchaseInvoiceItem.receipt_item_id.in_(valid_receipt_items),
                            PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED,
                            PurchaseInvoice.id != pi.id,  # exclude self
                        )
                        .group_by(PurchaseInvoiceItem.receipt_item_id)
                    ).all()
                )
                billed_map = {
                    rid: Decimal(str(qty or 0)) for rid, qty in rows
                }

                for ln in lines_in:
                    rid = ln.get("receipt_item_id")
                    if rid:
                        if rid not in valid_receipt_items:
                            raise V.BizValidationError(
                                f"receipt_item_id {rid} does not belong to receipt {pi.receipt_id}."
                            )
                        rec_it = rec_map[rid]
                        if Decimal(str(ln["rate"])) != Decimal(
                            str(rec_it.unit_price or 0)
                        ):
                            raise V.BizValidationError(
                                "When billing against receipt, item rate must match the receipt item rate."
                            )
                        already = billed_map.get(rid, Decimal("0"))
                        available = Decimal(str(rec_it.accepted_qty)) - already
                        if Decimal(str(ln["quantity"])) > available:
                            raise V.BizValidationError(
                                f"Over-billing: {ln['quantity']} > available {available} for receipt item {rid}."
                            )

            # Upsert lines
            self.repo.sync_lines(pi, lines_in)

        # Recalc totals & outstanding (still draft)
        self.repo.recalc_total(pi)

        # Re-validate payment setup after recomputing totals
        V.validate_payment_consistency(
            Decimal(str(pi.paid_amount or 0)),
            pi.mode_of_payment_id,
            pi.cash_bank_account_id,
        )

        self.s.commit()
        return pi

    # -------------------------------------------------------------------------
    # Return template builder (mapped doc)
    # -------------------------------------------------------------------------
    def build_purchase_invoice_return_template(
        self, *, original_pi_id: int, context: AffiliationContext
    ) -> dict:
        """
        ERPNext-style mapped doc for Purchase Invoice Return (Debit Note):

        - Load original Purchase Invoice (with items).
        - Build a RETURN draft payload (NOT saved).
        - Quantities are NEGATIVE.
        - is_return = True, return_against_id = original.id.
        """
        original: PurchaseInvoice = self.repo.get_original_for_return(original_pi_id)
        if not original:
            raise NotFound("Original Purchase Invoice not found or not eligible for return.")

        # Scope checks
        ensure_scope_by_ids(
            context=context,
            target_company_id=original.company_id,
            target_branch_id=original.branch_id,
        )

        if original.is_return:
            raise BadRequest("Cannot create a return against a return Purchase Invoice.")

        today_str = datetime.now(timezone.utc).date().isoformat()

        header: Dict[str, Optional[object]] = {
            "company_id": original.company_id,
            "branch_id": original.branch_id,
            "supplier_id": original.supplier_id,
            "posting_date": today_str,
            "due_date": None,
            "update_stock": original.update_stock,
            "is_return": True,
            "return_against_id": original.id,
            "receipt_id": None,  # returns are against PI, not PR
            "warehouse_id": original.warehouse_id,
            "payable_account_id": original.payable_account_id,
            "remarks": f"Return against Purchase Invoice {original.code}",
            # payment on return starts as no refund booked
            "paid_amount": "0.00",
            "mode_of_payment_id": None,
            "cash_bank_account_id": None,
        }

        # Map items with NEGATIVE quantities
        lines: List[Dict[str, object]] = []
        for it in original.items:
            qty = Decimal(str(it.quantity))
            rate = Decimal(str(it.rate))

            lines.append(
                {
                    "item_id": it.item_id,
                    "uom_id": it.uom_id,
                    "warehouse_id": it.warehouse_id,
                    "quantity": str(-qty),  # NEGATIVE for return
                    "rate": str(rate),
                    "receipt_item_id": None,  # returns map to original PI, not PR
                    "return_against_item_id": it.id,
                    "remarks": it.remarks,
                }
            )

        original_invoice = {
            "id": original.id,
            "code": original.code,
            "posting_date": original.posting_date.date().isoformat()
            if original.posting_date
            else None,
            "total_amount": str(original.total_amount or Decimal("0")),
            "paid_amount": str(original.paid_amount or Decimal("0")),
            "outstanding_amount": str(original.outstanding_amount or Decimal("0")),
            "update_stock": bool(original.update_stock),
            "doc_status": original.doc_status.name if original.doc_status else None,
        }

        mop = getattr(original, "mode_of_payment", None)
        bank_acc = getattr(original, "cash_bank_account", None)

        original_payment = {
            "mode_of_payment_id": original.mode_of_payment_id,
            "mode_of_payment_name": getattr(mop, "name", None),
            "cash_bank_account_id": original.cash_bank_account_id,
            "cash_bank_account_name": getattr(bank_acc, "name", None),
            "cash_bank_account_code": getattr(bank_acc, "code", None),
        }

        return {
            "header": header,
            "items": lines,
            "original_invoice": original_invoice,
            "original_payment": original_payment,
        }

    # -------------------------------------------------------------------------
    # (Your existing submit/cancel/stock posting methods remain below as-is)
    # -------------------------------------------------------------------------

    def _doc_type_id(self, code: str) -> int:
        dt = self.s.execute(
            select(DocumentType.id).where(DocumentType.code == code)
        ).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt

    def _guard_submittable(self, pi: PurchaseInvoice) -> None:
        V.guard_submittable_state(pi.doc_status)
        if pi.is_return and not pi.return_against_id:
            raise V.BizValidationError(
                "Return Invoice must reference original invoice."
            )

    def submit_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        logger.info("🔄 PI submit start | invoice_id=%s", invoice_id)

        pi = self.repo.get_by_id(invoice_id, for_update=False)
        if not pi:
            logger.error("❌ PI submit aborted: not found | invoice_id=%s", invoice_id)
            raise NotFound("Purchase Invoice not found.")

        logger.info(
            "📄 PI=%s | company=%s branch=%s | update_stock=%s is_return=%s",
            pi.code, pi.company_id, pi.branch_id, pi.update_stock, pi.is_return
        )

        ensure_scope_by_ids(context=context, target_company_id=pi.company_id, target_branch_id=pi.branch_id)
        PostingDateValidator.validate_standalone_document(self.s, pi.posting_date, pi.company_id)
        self._guard_submittable(pi)

        # ---------------- COMMON PREP ----------------
        header_wh = pi.warehouse_id
        line_snaps = []
        for idx, it in enumerate(pi.items):
            line_snaps.append(
                {
                    "item_id": it.item_id,
                    "uom_id": it.uom_id,
                    "quantity": it.quantity,
                    "rate": it.rate,
                    "warehouse_id": it.warehouse_id,
                    "doc_row_id": it.id,
                }
            )
            logger.info(
                "  PI line %s | item=%s qty=%s rate=%s wh=%s",
                idx + 1, it.item_id, it.quantity, it.rate, it.warehouse_id
            )

        # Ensure warehouse for stock lines
        self._enforce_line_warehouses_if_stock(pi.update_stock, line_snaps, header_wh)

        # Load item details (stock / non-stock, base_uom, etc.)
        item_ids = [it.item_id for it in pi.items]
        details = self.repo.get_item_details_batch(pi.company_id, item_ids)

        stock_lines = []
        if pi.update_stock:
            for snap in line_snaps:
                item_detail = details.get(snap["item_id"], {})
                if item_detail.get("is_stock_item", False):
                    base = item_detail.get("base_uom_id")
                    stock_lines.append({**snap, "base_uom_id": base})
                    logger.info(
                        "  ✅ Stock item | item=%s base_uom=%s wh=%s",
                        snap["item_id"], base, snap["warehouse_id"]
                    )
                else:
                    logger.info("  ⏭️ Non-stock item | item=%s", snap["item_id"])

        doc_type_id = self._doc_type_id("PURCHASE_RETURN" if pi.is_return else "PURCHASE_INVOICE")
        posting_dt = resolve_posting_dt(pi.posting_date, created_at=pi.created_at, treat_midnight_as_date=True)
        logger.info("📅 PI posting_dt=%s", posting_dt)

        # ======================================================================
        # 1) STOCK PATH: update_stock=True and we actually have stock lines
        # ======================================================================
        if pi.update_stock and stock_lines:
            logger.info("🚀 PI stock path | lines=%s", len(stock_lines))

            if pi.is_return:
                intents = build_intents_for_return(
                    company_id=pi.company_id,
                    branch_id=pi.branch_id,
                    warehouse_id=pi.warehouse_id,
                    posting_dt=posting_dt,
                    doc_type_id=doc_type_id,
                    doc_id=pi.id,
                    lines=[
                        {
                            "uom_id": ln["uom_id"],
                            "item_id": ln["item_id"],
                            "accepted_qty": ln["quantity"],  # sign handled by builder
                            "unit_price": ln["rate"],
                            "doc_row_id": ln["doc_row_id"],
                            "base_uom_id": ln.get("base_uom_id"),
                            "warehouse_id": ln["warehouse_id"],
                        }
                        for ln in stock_lines
                    ],
                    session=self.s,
                )
            else:
                intents = build_intents_for_receipt(
                    company_id=pi.company_id,
                    branch_id=pi.branch_id,
                    warehouse_id=pi.warehouse_id,
                    posting_dt=posting_dt,
                    doc_type_id=doc_type_id,
                    doc_id=pi.id,
                    lines=[
                        {
                            "uom_id": ln["uom_id"],
                            "item_id": ln["item_id"],
                            "accepted_qty": ln["quantity"],
                            "unit_price": ln["rate"],
                            "doc_row_id": ln["doc_row_id"],
                            "base_uom_id": ln.get("base_uom_id"),
                            "warehouse_id": ln["warehouse_id"],
                        }
                        for ln in stock_lines
                    ],
                    session=self.s,
                )

            for idx, it in enumerate(intents):
                if it.warehouse_id is None:
                    logger.error("❌ PI intent missing warehouse | idx=%s item_id=%s", idx, it.item_id)
                    raise V.BizValidationError(
                        "Internal error: PI intent without warehouse. Please check warehouses/UOMs."
                    )

            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            if not pairs:
                logger.error("❌ PI no SLE pairs generated while update_stock=True | invoice_id=%s", invoice_id)
                raise V.BizValidationError(
                    "No stock ledger pairs generated for stock items; check warehouses/UOMs."
                )

            # Backdated check
            def _future_exists(item_id: int, wh: int) -> bool:
                q = (
                        self.s.execute(
                            select(func.count())
                            .select_from(StockLedgerEntry)
                            .where(
                                StockLedgerEntry.company_id == pi.company_id,
                                StockLedgerEntry.item_id == item_id,
                                StockLedgerEntry.warehouse_id == wh,
                                (
                                        (StockLedgerEntry.posting_date > posting_dt.date())
                                        | and_(
                                    StockLedgerEntry.posting_date == posting_dt.date(),
                                    StockLedgerEntry.posting_time > posting_dt,
                                )
                                ),
                                StockLedgerEntry.is_cancelled == False,
                            )
                        ).scalar()
                        or 0
                )
                return q > 0

            is_backdated = any(_future_exists(i, w) for (i, w) in pairs)
            if is_backdated:
                logger.warning("⚠️ PI is backdated; will replay inside TX | invoice_id=%s", invoice_id)

            # Single atomic block (like Sales)
            with self.s.begin_nested():
                pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
                self._guard_submittable(pi_locked)

                # Write SLEs
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(
                            self.s,
                            intent,
                            created_at_hint=pi_locked.created_at,
                            tz_hint=None,
                            batch_index=idx,
                        )

                if is_backdated:
                    for (item_id, wh_id) in pairs:
                        repost_from(
                            s=self.s,
                            company_id=pi_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set(),
                        )

                for (item_id, wh_id) in pairs:
                    derive_bin(self.s, pi_locked.company_id, item_id, wh_id)

                # GL template selection
                has_receipt_items = any(x.receipt_item_id for x in pi_locked.items)
                template = (
                    "PURCHASE_RETURN_INVOICED"
                    if pi_locked.is_return
                    else (
                        "PURCHASE_INVOICE_DIRECT"
                        if pi_locked.update_stock and not has_receipt_items
                        else "PURCHASE_INVOICE_AGAINST_RECEIPT"
                    )
                )

                total_amount = abs(Decimal(str(pi_locked.total_amount or 0)))
                stock_value = Decimal("0")
                service_value = Decimal("0")
                for it in pi_locked.items:
                    val = abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                    if details.get(it.item_id, {}).get("is_stock_item", False) and pi_locked.update_stock:
                        stock_value += val
                    else:
                        service_value += val

                payload = {
                    "invoice_lines": [
                        {"quantity": it.quantity, "rate": it.rate, "item_id": it.item_id}
                        for it in pi_locked.items
                    ],
                    "DOCUMENT_TOTAL": float(total_amount),
                    "update_stock": bool(pi_locked.update_stock),
                }
                if template == "PURCHASE_INVOICE_DIRECT":
                    payload["INVOICE_STOCK_VALUE"] = float(stock_value)
                    payload["INVOICE_SERVICE_VALUE"] = float(service_value)
                if template == "PURCHASE_RETURN_INVOICED":
                    payload["RETURN_STOCK_VALUE"] = float(stock_value)

                # Default AP account if not set
                payable = pi_locked.payable_account_id
                if not payable:
                    from app.application_accounting.chart_of_accounts.models import Account

                    payable = (
                        self.s.execute(
                            select(Account.id).where(
                                Account.company_id == pi_locked.company_id, Account.code == "2111"
                            )
                        ).scalar_one_or_none()
                    )
                    if not payable:
                        logger.error(
                            "❌ PI submit missing AP account 2111 | company=%s", pi_locked.company_id
                        )
                        raise V.BizValidationError("Default Accounts Payable (2111) not found.")

                dyn_ctx = {"accounts_payable_account_id": payable}

                # Inline payment / refund (both normal PI and return)
                if pi_locked.paid_amount and pi_locked.paid_amount != 0:
                    if not pi_locked.mode_of_payment_id or not pi_locked.cash_bank_account_id:
                        raise V.BizValidationError(
                            "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                        )
                    payload["AMOUNT_PAID"] = float(pi_locked.paid_amount)
                    dyn_ctx["cash_bank_account_id"] = pi_locked.cash_bank_account_id

                PostingService(self.s).post(
                    PostingContext(
                        company_id=pi_locked.company_id,
                        branch_id=pi_locked.branch_id,
                        source_doctype_id=doc_type_id,
                        source_doc_id=pi_locked.id,
                        posting_date=posting_dt,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=None,
                        remarks=(
                                    "Purchase Return " if pi_locked.is_return else "Purchase Invoice "
                                )
                                + pi_locked.code,
                        template_code=template,
                        payload=payload,
                        runtime_accounts={},
                        party_id=pi_locked.supplier_id,
                        party_type=PartyTypeEnum.SUPPLIER,
                        # ✅ IMPORTANT: dynamic accounts (AP + Bank) for AMOUNT_PAID rules
                        dynamic_account_context=dyn_ctx,
                    )
                )

                pi_locked.doc_status = (
                    DocStatusEnum.RETURNED if pi_locked.is_return else DocStatusEnum.SUBMITTED
                )
                self.repo.save(pi_locked)

            self.s.commit()
            logger.info("🎉 PI submit done (stock) | %s", pi.code)
            return pi

        # ======================================================================
        # 2) FINANCE-ONLY PATH (no stock)
        # ======================================================================
        logger.info("💳 PI finance-only path | invoice_id=%s", invoice_id)
        with self.s.begin_nested():
            pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
            self._guard_submittable(pi_locked)

            has_receipt_items = any(x.receipt_item_id for x in pi_locked.items)
            template = (
                "PURCHASE_RETURN_INVOICED"
                if pi_locked.is_return
                else (
                    "PURCHASE_INVOICE_AGAINST_RECEIPT"
                    if (pi_locked.receipt_id or has_receipt_items)
                    else "PURCHASE_INVOICE_DIRECT"
                )
            )
            total_amount = abs(Decimal(str(pi_locked.total_amount or 0)))

            details2 = self.repo.get_item_details_batch(
                pi_locked.company_id, [x.item_id for x in pi_locked.items]
            )
            stock_value = Decimal("0")
            service_value = Decimal("0")
            for it in pi_locked.items:
                val = abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                if details2.get(it.item_id, {}).get("is_stock_item", False) and pi_locked.update_stock:
                    stock_value += val
                else:
                    service_value += val

            payload = {
                "invoice_lines": [
                    {"quantity": it.quantity, "rate": it.rate, "item_id": it.item_id}
                    for it in pi_locked.items
                ],
                "DOCUMENT_TOTAL": float(total_amount),
                "update_stock": bool(pi_locked.update_stock),
            }
            if template == "PURCHASE_INVOICE_DIRECT":
                payload["INVOICE_STOCK_VALUE"] = float(stock_value)
                payload["INVOICE_SERVICE_VALUE"] = float(service_value)
            if template == "PURCHASE_RETURN_INVOICED":
                payload["RETURN_STOCK_VALUE"] = float(stock_value)

            payable = pi_locked.payable_account_id
            if not payable:
                from app.application_accounting.chart_of_accounts.models import Account

                payable = (
                    self.s.execute(
                        select(Account.id).where(
                            Account.company_id == pi_locked.company_id, Account.code == "2111"
                        )
                    ).scalar_one_or_none()
                )
                if not payable:
                    logger.error(
                        "❌ PI submit missing AP account 2111 (finance-only) | company=%s",
                        pi_locked.company_id,
                    )
                    raise V.BizValidationError("Default Accounts Payable (2111) not found.")
            dyn_ctx = {"accounts_payable_account_id": payable}

            # Inline payment / refund for finance-only path as well
            if pi_locked.paid_amount and pi_locked.paid_amount != 0:
                if not pi_locked.mode_of_payment_id or not pi_locked.cash_bank_account_id:
                    raise V.BizValidationError(
                        "Paid amount provided but mode_of_payment_id or cash_bank_account_id is missing."
                    )
                payload["AMOUNT_PAID"] = float(pi_locked.paid_amount)
                dyn_ctx["cash_bank_account_id"] = pi_locked.cash_bank_account_id

            PostingService(self.s).post(
                PostingContext(
                    company_id=pi_locked.company_id,
                    branch_id=pi_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=pi_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=(
                                "Purchase Return " if pi_locked.is_return else "Purchase Invoice "
                            )
                            + pi_locked.code,
                    template_code=template,
                    payload=payload,
                    runtime_accounts={},
                    party_id=pi_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                    # ✅ FIX: pass dynamic accounts here as well
                    dynamic_account_context=dyn_ctx,
                )
            )

            pi_locked.doc_status = (
                DocStatusEnum.RETURNED if pi_locked.is_return else DocStatusEnum.SUBMITTED
            )
            self.repo.save(pi_locked)

        self.s.commit()
        logger.info("🎉 PI submit done (finance-only) | %s", pi.code)
        return pi

    def cancel_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        """
        Cancel a submitted Purchase Invoice (or Purchase Return).

        STOCK:
        - Marks its SLEs as cancelled and replays stock from the earliest SLE.
        - Re-derives bins.

        GL:
        - Uses PostingService.cancel(...) to post a proper reversal JE.
        - If no auto JE exists (legacy data), logs a warning but still cancels the PI.

        This mirrors the pattern used for Stock Entry, Stock Reconciliation, Payment Entry, Expense, and PCV.
        """
        from sqlalchemy import select
        from decimal import Decimal
        from app.application_stock.stock_models import StockLedgerEntry
        from app.application_stock.engine.replay import repost_from
        from app.application_stock.engine.bin_derive import derive_bin
        from app.application_stock.engine.locks import lock_pairs
        from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
        from app.application_accounting.engine.posting_service import PostingService, PostingContext
        from app.application_accounting.engine.errors import PostingValidationError

        logger.info("♻️ PI cancel start | invoice_id=%s", invoice_id)

        # 1) Read & guards
        pi = self.repo.get_by_id(invoice_id, for_update=False)
        if not pi:
            raise NotFound("Purchase Invoice not found.")

        ensure_scope_by_ids(
            context=context,
            target_company_id=pi.company_id,
            target_branch_id=pi.branch_id,
        )
        V.guard_cancellable_state(pi.doc_status)

        # IMPORTANT: use the same DocType used on submit (even for returns)
        dt_id = self._doc_type_id("PURCHASE_INVOICE")

        # Normalize/validate posting date for period rules
        cancel_posting_dt = PostingDateValidator.validate_standalone_document(
            s=self.s,
            posting_date_or_dt=pi.posting_date,
            company_id=pi.company_id,
            created_at=pi.created_at,
            treat_midnight_as_date=True,
        )

        # 2) Collect SLEs for this PI
        sle_rows = (
            self.s.execute(
                select(StockLedgerEntry)
                .where(
                    StockLedgerEntry.company_id == pi.company_id,
                    StockLedgerEntry.doc_type_id == dt_id,
                    StockLedgerEntry.doc_id == pi.id,
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                )
                .order_by(
                    StockLedgerEntry.posting_date.asc(),
                    StockLedgerEntry.posting_time.asc(),
                    StockLedgerEntry.id.asc(),
                )
            )
            .scalars()
            .all()
        )

        pairs = {(r.item_id, r.warehouse_id) for r in sle_rows}
        earliest_dt = min(
            (r.posting_time for r in sle_rows),
            default=cancel_posting_dt,
        )

        try:
            with self.s.begin_nested():
                # 3) Lock and re-check state
                pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
                V.guard_cancellable_state(pi_locked.doc_status)

                # 3a) STOCK: cancel SLEs then replay
                if sle_rows:
                    from app.application_stock.engine.locks import lock_pairs as _lock_pairs

                    with _lock_pairs(self.s, pairs):
                        # reload inside lock to avoid stale objects
                        originals = (
                            self.s.execute(
                                select(StockLedgerEntry)
                                .where(
                                    StockLedgerEntry.company_id == pi_locked.company_id,
                                    StockLedgerEntry.doc_type_id == dt_id,
                                    StockLedgerEntry.doc_id == pi_locked.id,
                                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                                )
                                .order_by(
                                    StockLedgerEntry.posting_date.asc(),
                                    StockLedgerEntry.posting_time.asc(),
                                    StockLedgerEntry.id.asc(),
                                )
                            )
                            .scalars()
                            .all()
                        )
                        for sle in originals:
                            sle.is_cancelled = True

                # Replay valuations & re-derive bins
                if pairs:
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=pi_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=earliest_dt,
                            exclude_doc_types=set(),
                        )
                        logger.info(
                            "  🔄 Reposted from %s | item=%s wh=%s",
                            earliest_dt,
                            item_id,
                            wh_id,
                        )

                    for item_id, wh_id in pairs:
                        derive_bin(self.s, pi_locked.company_id, item_id, wh_id)

                # 3b) GL: reverse original auto JE if present
                try:
                    PostingService(self.s).cancel(
                        PostingContext(
                            company_id=pi_locked.company_id,
                            branch_id=pi_locked.branch_id,
                            source_doctype_id=dt_id,
                            source_doc_id=pi_locked.id,
                            posting_date=cancel_posting_dt,  # informational
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            remarks=(
                                f"Cancel "
                                f"{'Purchase Return' if pi_locked.is_return else 'Purchase Invoice'} "
                                f"{pi_locked.code}"
                            ),
                            party_id=pi_locked.supplier_id,
                            party_type=PartyTypeEnum.SUPPLIER,
                        )
                    )
                    logger.info("📘 GL cancel posted for %s", pi_locked.code)
                except PostingValidationError as e:
                    # No auto JE to cancel (legacy / partially migrated data) → just log & continue
                    logger.warning(
                        "PI cancel: no auto journal to cancel for %s (ok for legacy data): %s",
                        pi_locked.code,
                        e,
                    )

                # 3c) Mark PI as CANCELLED
                pi_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(pi_locked)

            self.s.commit()
            logger.info("🎉 PI cancel done | %s", pi_locked.code)
            return pi_locked

        except Exception:
            self.s.rollback()
            logger.exception("❌ PI cancel failed | invoice_id=%s", invoice_id)
            raise
