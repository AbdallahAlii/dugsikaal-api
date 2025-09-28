# app/application_buying/services.py
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import and_, select
from typing import Optional, List, Dict
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine.sle_writer import append_sle
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

from app.application_buying.repository.invoice_repo import PurchaseInvoiceRepository
from app.application_buying.repository.receipt_repo import PurchaseReceiptRepository

from app.application_buying.schemas import PurchaseInvoiceCreate
from app.application_buying.models import PurchaseInvoice, PurchaseInvoiceItem, PurchaseReceipt

import app.business_validation.item_validation as V


class PurchaseInvoiceService:
    """Service layer for managing Purchase Invoices with dual functionality."""
    PREFIX = "PINV"  # matches your config table (branch-scoped, yearly)

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseInvoiceRepository(self.s)
        # Reuse PR repo for master lookups & receipt-based validations
        self.pr_repo = PurchaseReceiptRepository(self.s)

    # ---------------------------- internals ----------------------------

    def _get_validated_invoice(
        self, invoice_id: int, context: AffiliationContext, for_update: bool = False
    ) -> PurchaseInvoice:
        pi = self.repo.get_by_id(invoice_id, for_update=for_update)
        if not pi:
            raise NotFound("Purchase Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=pi.company_id, target_branch_id=pi.branch_id)
        return pi

    def _generate_or_validate_code(self, company_id: int, branch_id: int, manual_code: Optional[str]) -> str:
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_direct_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        """Validations for direct (stock or non-stock) invoices."""
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.pr_repo.get_item_details_batch(company_id, item_ids)
        normalized = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized])
        V.validate_no_service_items(normalized)  # ensures stock-only where needed
        V.validate_uom_present_for_stock_items(normalized)

        uom_ids = [ln["uom_id"] for ln in normalized if ln.get("uom_id")]
        if uom_ids:
            existing_uoms = self.pr_repo.get_existing_uom_ids(company_id, uom_ids)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized if ln.get("uom_id")]
        compat = self.pr_repo.get_compatible_uom_pairs(company_id, pairs)
        for ln in normalized:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compat
        V.validate_item_uom_compatibility(normalized)

        for ln in normalized:
            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln["rate"])

        return normalized

    def _validate_receipt_based_lines(
        self,
        receipt: PurchaseReceipt,
        billed_quantities: Dict[int, Decimal],
        lines: List[Dict],
    ) -> None:
        """Validates invoice lines that reference a submitted receipt."""
        receipt_items_map = {it.id: it for it in receipt.items}
        for ln in lines:
            rid = ln.get("receipt_item_id")
            if not rid:
                raise V.BizValidationError("Each item must include 'receipt_item_id' when billing a receipt.")
            r_item = receipt_items_map.get(rid)
            if not r_item:
                raise V.BizValidationError(f"Receipt Item ID {rid} not found on the specified receipt.")

            if r_item.item_id != ln["item_id"]:
                raise V.BizValidationError(
                    f"Item mismatch for receipt line {rid}. Expected item {r_item.item_id}, got {ln['item_id']}."
                )

            billed_qty = billed_quantities.get(rid, Decimal(0))
            billable_qty = Decimal(str(r_item.accepted_qty)) - billed_qty

            if Decimal(str(ln["quantity"])) > billable_qty:
                raise V.BizValidationError(
                    f"Over-billing item {ln['item_id']}. Max billable quantity is {billable_qty}."
                )

            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln["rate"])

    def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
        return sum(Decimal(str(ln["quantity"])) * Decimal(str(ln["rate"])) for ln in lines)

    # ----------------------------- create -----------------------------

    def create_purchase_invoice(self, *, payload: PurchaseInvoiceCreate, context: AffiliationContext) -> PurchaseInvoice:
        """
        Two modes:
          • From submitted Purchase Receipt (payload.receipt_id present):
              - Canonicalize from the receipt’s (company_id, branch_id)
              - enforce scope via ensure_scope_by_ids
              - validate supplier & lines against receipt
          • Direct Invoice:
              - Canonicalize via resolve_company_branch_and_scope (Way B)
              - validate supplier active, optional warehouse if update_stock
        """
        # Normalize line dicts once
        lines_data = [ln.model_dump() for ln in payload.items]

        # ------------------ Mode 1: From Purchase Receipt ------------------
        if payload.receipt_id:
            status = self.repo.get_receipt_billable_status(payload.receipt_id)
            if not status or not status.get("receipt"):
                raise V.BizValidationError(f"Submitted Purchase Receipt with ID {payload.receipt_id} not found.")

            receipt: PurchaseReceipt = status["receipt"]
            if receipt.doc_status != DocStatusEnum.SUBMITTED:
                raise V.BizValidationError("Only a SUBMITTED Purchase Receipt can be billed.")

            company_id = receipt.company_id
            branch_id = receipt.branch_id

            # Enforce user scope on the canonical pair (from the receipt)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            # If caller sent company/branch, they must match the receipt's canonical values
            if payload.company_id is not None and payload.company_id != company_id:
                raise Forbidden("Out of scope. Receipt does not belong to the target company.")
            if payload.branch_id is not None and payload.branch_id != branch_id:
                raise Forbidden("Out of scope. Receipt does not belong to the target branch.")

            # Supplier must match the receipt’s supplier
            if payload.supplier_id != receipt.supplier_id:
                raise V.BizValidationError("Supplier must match the source Purchase Receipt.")

            # Validate lines against the receipt
            billed_quantities: Dict[int, Decimal] = status["billed_quantities"]
            self._validate_receipt_based_lines(receipt, billed_quantities, lines_data)

            # For receipt-mode: update_stock must be False; warehouse_id must be None
            if payload.update_stock:
                raise BadRequest("Cannot set 'update_stock' when billing from a Purchase Receipt.")
            if payload.warehouse_id:
                raise BadRequest("Do not pass 'warehouse_id' when billing from a Purchase Receipt.")

        # ------------------ Mode 2: Direct Invoice ------------------
        else:
            # Canonicalize (company_id, branch_id) via Way B and enforce scope
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=payload.branch_id or getattr(context, "branch_id", None),
                get_branch_company_id=self.pr_repo.get_branch_company_id,
                require_branch=True,
            )

            # Validate supplier active in company
            valid_suppliers = self.pr_repo.get_valid_supplier_ids(company_id, [payload.supplier_id])
            V.validate_supplier_is_active(payload.supplier_id in valid_suppliers)

            # If this is a stock-updating invoice, warehouse must be valid (leaf, active)
            if payload.update_stock:
                if not payload.warehouse_id:
                    # Should already be enforced by schema, but guard here as well
                    raise BadRequest("'warehouse_id' is required when 'update_stock' is True.")
                valid_whs = self.pr_repo.get_transactional_warehouse_ids(company_id, branch_id, [payload.warehouse_id])
                V.validate_warehouse_is_transactional(payload.warehouse_id in valid_whs)

            # Validate direct-mode lines (items/UOM/qty/rate)
            self._validate_direct_lines(company_id, lines_data)

        # ------------------ Common persistance (both modes) ------------------
        try:
            # At this point, company_id & branch_id are set in both modes
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(lines_data)

            pi = PurchaseInvoice(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=payload.supplier_id,
                warehouse_id=payload.warehouse_id,  # None for receipt-mode, optional for direct
                code=code,
                posting_date=payload.posting_date,
                due_date=payload.due_date,
                doc_status=DocStatusEnum.DRAFT,
                update_stock=bool(payload.update_stock),
                total_amount=total_amount,
                balance_due=total_amount,
                remarks=payload.remarks,
                items=[PurchaseInvoiceItem(**ln) for ln in lines_data],
            )
            self.repo.save(pi)
            self.s.commit()
            return pi

        except Exception:
            self.s.rollback()
            raise

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
        return dt

    # ----------------------------- actions -----------------------------

    def submit_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        try:
            logging.info("PI submit: start invoice_id=%s", invoice_id)

            # -------- 1) READ-ONLY PHASE (NO for_update) --------
            pi = self._get_validated_invoice(invoice_id, context, for_update=False)
            V.guard_submittable_state(pi.doc_status)
            V.validate_list_not_empty(pi.items, "items for submission")

            # If this invoice does NOT update stock, we just flip status — no SLE/Bin.
            if not pi.update_stock:
                logging.info("PI submit: update_stock=False -> status flip only")
                with self.s.begin():
                    pi_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                    V.guard_submittable_state(pi_locked.doc_status)
                    pi_locked.doc_status = DocStatusEnum.SUBMITTED
                    self.repo.save(pi_locked)
                logging.info("PI submit: success id=%s code=%s", pi.id, pi.code)
                return pi

            # ---- Direct mode with stock effects ----
            logging.debug(
                "PI submit (direct): company=%s branch=%s supplier=%s wh=%s posting=%s",
                pi.company_id, pi.branch_id, pi.supplier_id, pi.warehouse_id, pi.posting_date
            )

            if not pi.warehouse_id:
                raise V.BizValidationError("'warehouse_id' is required when update_stock=True.")

            # Build a *validated snapshot* of lines from the persisted items
            # (You already validated at create; we re-check basic invariants.)
            lines_data = [{
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "quantity": it.quantity,
                "rate": it.rate,
                "doc_row_id": it.id,
            } for it in pi.items]
            # Minimal revalidation (reuse your direct-line validator):
            self._validate_direct_lines(pi.company_id, lines_data)

            # Resolve DocumentType id for PURCHASE_INVOICE
            doc_type_id = self._get_doc_type_id_or_400("PURCHASE_INVOICE")
            logging.debug("PI submit: doc_type_id=%s", doc_type_id)

            # posting_dt as *naive* datetime to match your validator (avoid tz mismatch)
            posting_dt: datetime = (
                pi.posting_date if isinstance(pi.posting_date, datetime)
                else datetime.combine(pi.posting_date, datetime.min.time())
            )
            logging.debug("PI submit: posting_dt=%s", posting_dt)

            # Build SLE intents (like PR, but using invoice fields).
            # Treat each invoice line as a *receipt* (qty>0) with incoming_rate=rate.
            intents: list[SLEIntent] = []
            for ln in lines_data:
                intents.append(SLEIntent(
                    company_id=pi.company_id,
                    branch_id=pi.branch_id,
                    item_id=ln["item_id"],
                    warehouse_id=pi.warehouse_id,
                    posting_dt=posting_dt,
                    actual_qty=Decimal(str(ln["quantity"])),
                    incoming_rate=Decimal(str(ln["rate"])),
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=pi.id,
                    doc_row_id=ln["doc_row_id"],
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={}
                ))
            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            logging.debug("PI submit: intents_count=%s pairs=%s", len(intents), list(pairs))

            # Backdated scan (read-only)
            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(StockLedgerEntry.id).filter(
                    StockLedgerEntry.company_id == pi.company_id,
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
            logging.info("PI submit: backdated=%s", is_backdated)

            # Close any implicit read tx before the write phase
            self.s.rollback()

            # -------- 2) ATOMIC WRITE PHASE --------
            with self.s.begin():
                pi_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                V.guard_submittable_state(pi_locked.doc_status)

                pi_locked.doc_status = DocStatusEnum.SUBMITTED
                self.repo.save(pi_locked)

                with lock_pairs(pairs):
                    for intent in intents:
                        try:
                            logging.debug("PI submit: append_sle intent=%s", intent)
                            append_sle(intent)  # uses Moving Average by default
                        except Exception:
                            logging.exception("append_sle failed", extra={"intent": repr(intent)})
                            raise

            # -------- 3) POST-COMMIT --------
            if is_backdated:
                for item_id, wh_id in pairs:
                    try:
                        with self.s.begin():
                            logging.info("PI submit: repost_from item=%s wh=%s start=%s", item_id, wh_id, posting_dt)
                            repost_from(company_id=pi.company_id, item_id=item_id, warehouse_id=wh_id,
                                        start_dt=posting_dt)
                    except Exception:
                        logging.exception("repost_from failed", extra={"item_id": item_id, "warehouse_id": wh_id})
                        raise
            else:
                for item_id, wh_id in pairs:
                    try:
                        with self.s.begin():
                            logging.info("PI submit: derive_bin item=%s wh=%s", item_id, wh_id)
                            derive_bin(item_id, wh_id)
                    except Exception:
                        logging.exception("derive_bin failed", extra={"item_id": item_id, "warehouse_id": wh_id})
                        raise

            logging.info("PI submit: success id=%s code=%s", pi.id, pi.code)
            return pi

        except Exception:
            logging.exception("PI submit: FAILED", extra={"invoice_id": invoice_id})
            self.s.rollback()
            raise

    def cancel_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        try:
            pi = self._get_validated_invoice(invoice_id, context, for_update=True)
            V.guard_cancellable_state(pi.doc_status)

            pi.doc_status = DocStatusEnum.CANCELLED
            # Reverse stock/GL entries here if you created them on submit.

            self.repo.save(pi)
            self.s.commit()
            return pi
        except Exception:
            self.s.rollback()
            raise
