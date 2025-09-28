# app/application_sales/services/invoice_service.py
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import and_, select
from typing import Optional, List, Dict
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest

from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.locks import lock_pairs
import app.business_validation.item_validation as V
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,                 # for persisted docs
    resolve_company_branch_and_scope,    # Way B: canonicalize + scope
)

# Business Logic
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum, StockLedgerEntry, DocumentType

from app.application_sales.repository.invoice_repo import SalesInvoiceRepository
from app.application_sales.repository.delivery_note_repo import SalesDeliveryNoteRepository  # <-- use SALES lookups

from app.application_sales.schemas import SalesInvoiceCreate
from app.application_sales.models import SalesInvoice, SalesInvoiceItem, SalesDeliveryNote


class SalesInvoiceService:
    """Service layer for managing Sales Invoices with dual functionality."""
    PREFIX = "SINV"  # matches your config table (branch-scoped, yearly)

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = SalesInvoiceRepository(self.s)
        # Reuse SDN repo for master lookups & delivery-based validations (parallels PR repo in buying)
        self.dn_repo = SalesDeliveryNoteRepository(self.s)

    # ---------------------------- internals ----------------------------

    def _get_validated_invoice(
        self, invoice_id: int, context: AffiliationContext, for_update: bool = False
    ) -> SalesInvoice:
        si = self.repo.get_by_id(invoice_id, for_update=for_update)
        if not si:
            raise NotFound("Sales Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=si.company_id, target_branch_id=si.branch_id)
        return si

    def _generate_or_validate_code(self, company_id: int, branch_id: int, manual_code: Optional[str]) -> str:
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_direct_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        """Validations for direct (stock or non-stock) invoices (same pattern as purchase)."""
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.dn_repo.get_item_details_batch(company_id, item_ids)
        normalized = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized])
        V.validate_no_service_items(normalized)               # ensures stock-only where needed
        V.validate_uom_present_for_stock_items(normalized)

        uom_ids = [ln["uom_id"] for ln in normalized if ln.get("uom_id")]
        if uom_ids:
            existing_uoms = self.dn_repo.get_existing_uom_ids(company_id, uom_ids)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized if ln.get("uom_id")]
        compat = self.dn_repo.get_compatible_uom_pairs(company_id, pairs)
        for ln in normalized:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compat
        V.validate_item_uom_compatibility(normalized)

        for ln in normalized:
            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln["rate"])

        return normalized

    def _validate_delivery_note_based_lines(
        self,
        delivery_note: SalesDeliveryNote,
        billed_quantities: Dict[int, Decimal],
        lines: List[Dict],
    ) -> None:
        """Validates invoice lines that reference a submitted delivery note."""
        dn_items_map = {it.id: it for it in delivery_note.items}
        for ln in lines:
            dnid = ln.get("delivery_note_item_id")
            if not dnid:
                raise V.BizValidationError("Each item must include 'delivery_note_item_id' when billing a delivery note.")
            dn_item = dn_items_map.get(dnid)
            if not dn_item:
                raise V.BizValidationError(f"Delivery Note Item ID {dnid} not found on the specified delivery note.")
            if dn_item.item_id != ln["item_id"]:
                raise V.BizValidationError(
                    f"Item mismatch for delivery note line {dnid}. Expected item {dn_item.item_id}, got {ln['item_id']}."
                )

            billed_qty = billed_quantities.get(dnid, Decimal(0))
            billable_qty = Decimal(str(dn_item.delivered_qty)) - billed_qty

            if Decimal(str(ln["quantity"])) > billable_qty:
                raise V.BizValidationError(
                    f"Over-billing item {ln['item_id']}. Max billable quantity is {billable_qty}."
                )

            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln["rate"])

    def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
        return sum(Decimal(str(ln["quantity"])) * Decimal(str(ln["rate"])) for ln in lines)

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
        return dt

    # ----------------------------- create -----------------------------

    def create_sales_invoice(self, *, payload: SalesInvoiceCreate, context: AffiliationContext) -> SalesInvoice:
        """
        Two modes:
          • From submitted Sales Delivery Note (payload.delivery_note_id present)
          • Direct Invoice
        """
        # Normalize line dicts once
        lines_data = [ln.model_dump() for ln in payload.items]

        # ------------------ Mode 1: From Sales Delivery Note ------------------
        if payload.delivery_note_id:
            status = self.repo.get_delivery_note_billable_status(payload.delivery_note_id)
            if not status or not status.get("delivery_note"):
                raise V.BizValidationError(f"Submitted Sales Delivery Note with ID {payload.delivery_note_id} not found.")

            delivery_note: SalesDeliveryNote = status["delivery_note"]
            if delivery_note.doc_status != DocStatusEnum.SUBMITTED:
                raise V.BizValidationError("Only a SUBMITTED Sales Delivery Note can be billed.")

            company_id = delivery_note.company_id
            branch_id = delivery_note.branch_id

            # Enforce user scope on the canonical pair (from the delivery note)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            # If caller sent company/branch, they must match the delivery note's canonical values
            if payload.company_id is not None and payload.company_id != company_id:
                raise Forbidden("Out of scope. Delivery note does not belong to the target company.")
            if payload.branch_id is not None and payload.branch_id != branch_id:
                raise Forbidden("Out of scope. Delivery note does not belong to the target branch.")

            # Customer must match the delivery note’s customer
            if payload.customer_id != delivery_note.customer_id:
                raise V.BizValidationError("Customer must match the source Sales Delivery Note.")

            # Validate lines against the delivery note
            billed_quantities: Dict[int, Decimal] = status["billed_quantities"]
            self._validate_delivery_note_based_lines(delivery_note, billed_quantities, lines_data)

            # For delivery-note-mode: update_stock must be False; warehouse_id must be None
            if payload.update_stock:
                raise BadRequest("Cannot set 'update_stock' when billing from a Sales Delivery Note.")
            if payload.warehouse_id:
                raise BadRequest("Do not pass 'warehouse_id' when billing from a Sales Delivery Note.")

        # ------------------ Mode 2: Direct Invoice ------------------
        else:
            # Canonicalize (company_id, branch_id) via Way B and enforce scope
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=payload.branch_id or getattr(context, "branch_id", None),
                get_branch_company_id=self.dn_repo.get_branch_company_id,
                require_branch=True,
            )

            # Validate customer active in company
            valid_customers = self.dn_repo.get_valid_customer_ids(company_id, [payload.customer_id])
            V.validate_customer_is_active(payload.customer_id in valid_customers)

            # If this is a stock-updating invoice, warehouse must be valid (leaf, active)
            if payload.update_stock:
                if not payload.warehouse_id:
                    # Should already be enforced by schema, but guard here as well
                    raise BadRequest("'warehouse_id' is required when 'update_stock' is True.")
                valid_whs = self.dn_repo.get_transactional_warehouse_ids(company_id, branch_id, [payload.warehouse_id])
                V.validate_warehouse_is_transactional(payload.warehouse_id in valid_whs)

            # Validate direct-mode lines (items/UOM/qty/rate)
            self._validate_direct_lines(company_id, lines_data)

        # ------------------ Common persistence (both modes) ------------------
        try:
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(lines_data)

            si = SalesInvoice(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                customer_id=payload.customer_id,
                warehouse_id=payload.warehouse_id,  # None for delivery-note-mode, optional for direct
                code=code,
                posting_date=payload.posting_date,
                due_date=payload.due_date,
                doc_status=DocStatusEnum.DRAFT,
                update_stock=bool(payload.update_stock),
                total_amount=total_amount,
                balance_due=total_amount,
                remarks=payload.remarks,
                items=[SalesInvoiceItem(**ln) for ln in lines_data],
            )
            self.repo.save(si)
            self.s.commit()
            return si

        except Exception:
            self.s.rollback()
            raise

    # ----------------------------- actions -----------------------------

    def submit_sales_invoice(self, *, invoice_id: int, context: AffiliationContext) -> SalesInvoice:
        try:
            logging.info("SI submit: start invoice_id=%s", invoice_id)

            # -------- 1) READ-ONLY PHASE (NO for_update) --------
            si = self._get_validated_invoice(invoice_id, context, for_update=False)
            V.guard_submittable_state(si.doc_status)
            V.validate_list_not_empty(si.items, "items for submission")

            # If this invoice does NOT update stock, we just flip status — no SLE/Bin.
            if not si.update_stock:
                logging.info("SI submit: update_stock=False -> status flip only")
                with self.s.begin():
                    si_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                    V.guard_submittable_state(si_locked.doc_status)
                    si_locked.doc_status = DocStatusEnum.SUBMITTED
                    self.repo.save(si_locked)
                logging.info("SI submit: success id=%s code=%s", si.id, si.code)
                return si

            # ---- Direct mode with stock effects (stock out) ----
            if not si.warehouse_id:
                raise V.BizValidationError("'warehouse_id' is required when update_stock=True.")

            # Build a validated snapshot of lines from the persisted items
            lines_data = [{
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "quantity": it.quantity,
                "rate": it.rate,
                "doc_row_id": it.id,
            } for it in si.items]
            self._validate_direct_lines(si.company_id, lines_data)

            # Resolve DocumentType id for SALES_INVOICE
            doc_type_id = self._get_doc_type_id_or_400("SALES_INVOICE")

            # FIX: Use the new helper to get a precise posting timestamp
            posting_dt: datetime = resolve_posting_dt(
                si.posting_date,
                created_at=getattr(si, "created_at", None),
            )

            # Build SLE intents (stock OUT: negative qty)
            intents: List[SLEIntent] = []
            for ln in lines_data:
                intents.append(SLEIntent(
                    company_id=si.company_id,
                    branch_id=si.branch_id,
                    item_id=ln["item_id"],
                    warehouse_id=si.warehouse_id,
                    posting_dt=posting_dt,
                    actual_qty=Decimal(str(-ln["quantity"])),  # STOCK OUT
                    incoming_rate=None,
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=si.id,
                    doc_row_id=ln["doc_row_id"],
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={}
                ))
            pairs = {(i.item_id, i.warehouse_id) for i in intents}

            # Backdated scan (read-only)
            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(StockLedgerEntry.id).filter(
                    StockLedgerEntry.company_id == si.company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                            (StockLedgerEntry.posting_date > posting_dt.date()) |
                            and_(
                                StockLedgerEntry.posting_date == posting_dt.date(),
                                StockLedgerEntry.posting_time > posting_dt,
                            )
                    ),
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                ).limit(1)
                return self.s.query(q.exists()).scalar()

            is_backdated = any(_has_future_sle(item_id, wh_id) for (item_id, wh_id) in pairs)

            # Close any implicit read tx before the write phase
            self.s.rollback()

            # -------- 2) ATOMIC WRITE PHASE --------
            with self.s.begin():
                si_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                V.guard_submittable_state(si_locked.doc_status)

                si_locked.doc_status = DocStatusEnum.SUBMITTED
                si_locked.posting_date = posting_dt  # Update the document with the real timestamp
                self.repo.save(si_locked)

                with lock_pairs(pairs):
                    for intent in intents:
                        append_sle(intent)  # stock out via negative actual_qty

            # -------- 3) POST-COMMIT --------
            if is_backdated:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        repost_from(company_id=si.company_id, item_id=item_id, warehouse_id=wh_id, start_dt=posting_dt)
            else:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        derive_bin(item_id, wh_id)

            logging.info("SI submit: success id=%s code=%s", si.id, si.code)
            return si

        except Exception:
            logging.exception("SI submit: FAILED", extra={"invoice_id": invoice_id})
            self.s.rollback()
            raise

    def cancel_sales_invoice(self, *, invoice_id: int, context: AffiliationContext) -> SalesInvoice:
        """
        Cancel a submitted Sales Invoice. If the invoice affected stock, this will
        cancel the related SLEs and re-evaluate the stock ledger.
        """
        try:
            logging.info("SI cancel: start invoice_id=%s", invoice_id)

            # -------- 1) READ-ONLY PHASE (NO for_update) --------
            si = self._get_validated_invoice(invoice_id, context, for_update=False)
            V.guard_cancellable_state(si.doc_status)

            # If this invoice does not update stock, we only flip its status.
            if not si.update_stock:
                logging.info("SI cancel: update_stock=False -> status flip only")
                self.s.rollback()  # Close read transaction
                with self.s.begin():
                    si_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                    V.guard_cancellable_state(si_locked.doc_status)
                    si_locked.doc_status = DocStatusEnum.CANCELLED
                    self.repo.save(si_locked)
                logging.info("SI cancel: success (no stock effects) id=%s code=%s", si.id, si.code)
                return si_locked

            # Find the SLEs written by this SI
            doc_type_id = self._get_doc_type_id_or_400("SALES_INVOICE")
            sle_rows = (
                self.s.query(
                    StockLedgerEntry.id,
                    StockLedgerEntry.item_id,
                    StockLedgerEntry.warehouse_id,
                    StockLedgerEntry.posting_time,
                )
                .filter(
                    StockLedgerEntry.company_id == si.company_id,
                    StockLedgerEntry.doc_type_id == doc_type_id,
                    StockLedgerEntry.doc_id == si.id,
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                    StockLedgerEntry.is_reversal == False,
                )
                .order_by(
                    StockLedgerEntry.posting_date.asc(),
                    StockLedgerEntry.posting_time.asc(),
                    StockLedgerEntry.id.asc(),
                )
                .all()
            )

            if not sle_rows:
                logging.info("SI cancel: no SLE to reverse for SI id=%s.", si.id)
                self.s.rollback()
                with self.s.begin():
                    si_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                    V.guard_cancellable_state(si_locked.doc_status)
                    si_locked.doc_status = DocStatusEnum.CANCELLED
                    self.repo.save(si_locked)
                logging.info("SI cancel: success (no stock effects) id=%s code=%s", si.id, si.code)
                return si_locked

            pairs = {(r.item_id, r.warehouse_id) for r in sle_rows}
            start_dt = min(r.posting_time for r in sle_rows)
            is_backdated = self.repo.has_future_sle(si.company_id, start_dt, pairs)
            logging.info("SI cancel: backdated=%s, pairs=%s", is_backdated, list(pairs))

            self.s.rollback()  # Close implicit read transaction

            # -------- 2) ATOMIC WRITE PHASE --------
            with self.s.begin():
                si_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                V.guard_cancellable_state(si_locked.doc_status)

                si_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(si_locked)

                with lock_pairs(pairs):
                    originals = (
                        self.s.query(StockLedgerEntry)
                        .filter(
                            StockLedgerEntry.company_id == si_locked.company_id,
                            StockLedgerEntry.doc_type_id == doc_type_id,
                            StockLedgerEntry.doc_id == si_locked.id,
                            StockLedgerEntry.is_cancelled == False,  # noqa: E712
                            StockLedgerEntry.is_reversal == False,
                        )
                        .order_by(
                            StockLedgerEntry.posting_date.asc(),
                            StockLedgerEntry.posting_time.asc(),
                            StockLedgerEntry.id.asc(),
                        )
                        .all()
                    )

                    for original in originals:
                        cancel_sle(original)

            # -------- 3) POST-COMMIT ACTIONS --------
            if is_backdated:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        repost_from(company_id=si.company_id, item_id=item_id, warehouse_id=wh_id, start_dt=start_dt)
            else:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        derive_bin(item_id, wh_id)

            logging.info("SI cancel: success id=%s code=%s", si.id, si.code)
            return si

        except Exception:
            logging.exception("SI cancel: FAILED", extra={"invoice_id": invoice_id})
            self.s.rollback()
            raise