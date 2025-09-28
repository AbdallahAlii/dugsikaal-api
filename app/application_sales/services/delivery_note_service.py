from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest
from sqlalchemy import and_, select  # and_ used in has_future_sle scan pattern

from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine.sle_writer import append_sle
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.locks import lock_pairs
import app.business_validation.item_validation as V

from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum
from app.application_sales.repository.delivery_note_repo import SalesDeliveryNoteRepository
from app.application_sales.schemas import SalesDeliveryNoteCreate, SalesDeliveryNoteUpdate
from app.application_sales.models import SalesDeliveryNote, SalesDeliveryNoteItem


class SalesDeliveryNoteService:
    """Service layer for managing Sales Delivery Notes."""
    PREFIX = "SDN"  # matches your config table (branch-scoped, yearly)

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        # Use the same repo for document ops and lookups (parallels purchase pattern)
        self.repo = SalesDeliveryNoteRepository(self.s)
        self.lookups = SalesDeliveryNoteRepository(self.s)

    # ---------------------------- internals ----------------------------

    def _get_validated_delivery_note(
        self, sdn_id: int, context: AffiliationContext, for_update: bool = False
    ) -> SalesDeliveryNote:
        sdn = self.repo.get_by_id(sdn_id, for_update=for_update)
        if not sdn:
            raise NotFound("Sales Delivery Note not found.")
        ensure_scope_by_ids(context=context, target_company_id=sdn.company_id, target_branch_id=sdn.branch_id)
        return sdn

    def _generate_or_validate_code(self, company_id: int, branch_id: int, manual_code: Optional[str]) -> str:
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        """
        Validations for delivery note lines.
        Accepts lines containing either 'delivered_qty' or 'quantity' (submit flow).
        """
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.lookups.get_item_details_batch(company_id, item_ids)
        normalized = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized])
        V.validate_no_service_items(normalized)

        uom_ids = [ln["uom_id"] for ln in normalized if ln.get("uom_id")]
        if uom_ids:
            existing_uoms = self.lookups.get_existing_uom_ids(company_id, uom_ids)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized if ln.get("uom_id")]
        compat = self.lookups.get_compatible_uom_pairs(company_id, pairs)
        for ln in normalized:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compat
        V.validate_item_uom_compatibility(normalized)

        for ln in normalized:
            qty = ln.get("delivered_qty", ln.get("quantity"))
            V.validate_positive_quantity(qty)

        return normalized

    def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
        # Unit price may be optional per line
        return sum(
            Decimal(str(ln["delivered_qty"])) * Decimal(str(ln["unit_price"]))
            for ln in lines
            if ln.get("unit_price") is not None
        )

    # ----------------------------- create -----------------------------

    def create_sales_delivery_note(self, *, payload: SalesDeliveryNoteCreate, context: AffiliationContext) -> SalesDeliveryNote:
        lines_data = [ln.model_dump() for ln in payload.items]

        # Canonicalize (company_id, branch_id) via Way B and enforce scope
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.lookups.get_branch_company_id,
            require_branch=True,
        )

        # Validate party and warehouse
        valid_customers = self.lookups.get_valid_customer_ids(company_id, [payload.customer_id])
        V.validate_customer_is_active(payload.customer_id in valid_customers)

        valid_whs = self.lookups.get_transactional_warehouse_ids(company_id, branch_id, [payload.warehouse_id])
        V.validate_warehouse_is_transactional(payload.warehouse_id in valid_whs)

        # Validate lines
        self._validate_lines(company_id, lines_data)

        try:
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(lines_data)

            sdn = SalesDeliveryNote(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                customer_id=payload.customer_id,
                warehouse_id=payload.warehouse_id,
                code=code,
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                total_amount=total_amount,
                remarks=payload.remarks,
                items=[SalesDeliveryNoteItem(**ln) for ln in lines_data],
            )
            self.repo.save(sdn)
            self.s.commit()
            return sdn

        except Exception:
            self.s.rollback()
            raise

    # ----------------------------- update -----------------------------

    def update_sales_delivery_note(self, *, sdn_id: int, payload: SalesDeliveryNoteUpdate, context: AffiliationContext) -> SalesDeliveryNote:
        try:
            sdn = self._get_validated_delivery_note(sdn_id, context, for_update=True)
            # Updates allowed only in Draft (matches purchase pattern)
            V.guard_draft_only(sdn.doc_status)

            if payload.posting_date:
                sdn.posting_date = payload.posting_date

            if payload.customer_id:
                valid_customers = self.lookups.get_valid_customer_ids(sdn.company_id, [payload.customer_id])
                V.validate_customer_is_active(payload.customer_id in valid_customers)
                sdn.customer_id = payload.customer_id

            if payload.warehouse_id:
                valid_whs = self.lookups.get_transactional_warehouse_ids(sdn.company_id, sdn.branch_id, [payload.warehouse_id])
                V.validate_warehouse_is_transactional(payload.warehouse_id in valid_whs)
                sdn.warehouse_id = payload.warehouse_id

            if payload.remarks is not None:
                sdn.remarks = payload.remarks

            if payload.items is not None:
                lines_data = [ln.model_dump(exclude_unset=True) for ln in payload.items]
                self._validate_lines(sdn.company_id, lines_data)
                self.repo.sync_lines(sdn, lines_data)
                # Recompute total
                # NOTE: expects delivered_qty/unit_price in lines_data when present
                sdn.total_amount = self._calculate_total_amount(lines_data)

            self.repo.save(sdn)
            self.s.commit()
            return sdn

        except Exception:
            self.s.rollback()
            raise

    # ----------------------------- actions -----------------------------

    def submit_sales_delivery_note(self, *, sdn_id: int, context: AffiliationContext) -> SalesDeliveryNote:
        try:
            logging.info("SDN submit: start sdn_id=%s", sdn_id)

            # -------- 1) READ-ONLY PHASE (NO for_update) --------
            sdn = self._get_validated_delivery_note(sdn_id, context, for_update=False)
            V.guard_submittable_state(sdn.doc_status)
            V.validate_list_not_empty(sdn.items, "items for submission")

            # Build a validated snapshot of lines from the persisted items
            lines_data = [{
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "quantity": it.delivered_qty,
                "doc_row_id": it.id,
            } for it in sdn.items]
            self._validate_lines(sdn.company_id, lines_data)

            # Resolve DocumentType id for SALES_DELIVERY_NOTE
            doc_type_id = self.repo.get_doc_type_id_by_code("SALES_DELIVERY_NOTE")

            # FIX: Use the new helper to get a precise posting timestamp
            posting_dt: datetime = resolve_posting_dt(
                sdn.posting_date,
                created_at=getattr(sdn, "created_at", None),
            )

            # Build SLE intents (stock OUT: negative qty)
            intents: List[SLEIntent] = []
            for ln in lines_data:
                intents.append(SLEIntent(
                    company_id=sdn.company_id,
                    branch_id=sdn.branch_id,
                    item_id=ln["item_id"],
                    warehouse_id=sdn.warehouse_id,
                    posting_dt=posting_dt,
                    actual_qty=Decimal(str(-ln["quantity"])),  # STOCK OUT
                    incoming_rate=None,
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=sdn.id,
                    doc_row_id=ln["doc_row_id"],
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={}
                ))

            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            is_backdated = self.repo.has_future_sle(sdn.company_id, posting_dt, pairs)

            # Close any implicit read tx before the write phase
            self.s.rollback()

            # -------- 2) ATOMIC WRITE PHASE --------
            with self.s.begin():
                sdn_locked = self._get_validated_delivery_note(sdn_id, context, for_update=True)
                V.guard_submittable_state(sdn_locked.doc_status)

                sdn_locked.doc_status = DocStatusEnum.SUBMITTED
                sdn_locked.posting_date = posting_dt  # Update the document with the real timestamp
                self.repo.save(sdn_locked)

                with lock_pairs(pairs):
                    for intent in intents:
                        append_sle(intent)

            # -------- 3) POST-COMMIT --------
            if is_backdated:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        repost_from(company_id=sdn.company_id, item_id=item_id, warehouse_id=wh_id, start_dt=posting_dt)
            else:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        derive_bin(item_id, wh_id)

            logging.info("SDN submit: success id=%s code=%s", sdn.id, sdn.code)
            return sdn

        except Exception:
            logging.exception("SDN submit: FAILED", extra={"sdn_id": sdn_id})
            self.s.rollback()
            raise

    def cancel_sales_delivery_note(self, *, sdn_id: int, context: AffiliationContext) -> SalesDeliveryNote:
        try:
            sdn = self._get_validated_delivery_note(sdn_id, context, for_update=True)
            V.guard_cancellable_state(sdn.doc_status)

            sdn.doc_status = DocStatusEnum.CANCELLED
            # TODO: Add stock reversal logic on cancellation if needed

            self.repo.save(sdn)
            self.s.commit()
            return sdn
        except Exception:
            self.s.rollback()
            raise
