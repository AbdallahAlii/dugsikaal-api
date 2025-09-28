from __future__ import annotations
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest

from config.database import db
import app.business_validation.item_validation as V
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import resolve_company_branch_and_scope, ensure_scope_by_ids

from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine.sle_writer import append_sle
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.stock_models import (
    DocStatusEnum, StockEntryType, StockLedgerEntry, DocumentType,
)
from app.application_stock.repo.stock_entry_repo import StockEntryRepository
from app.application_stock.schemas.stock_entry_schemas import StockEntryCreate, StockEntryUpdate
from app.application_stock.stock_models import StockEntry, StockEntryItem


class StockEntryService:
    PREFIX = "SE"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = StockEntryRepository(self.s)

    # ---------------- Internals ----------------

    def _get_validated_entry(self, se_id: int, context: AffiliationContext, *, for_update: bool = False) -> StockEntry:
        se = self.repo.get_by_id(se_id, for_update=for_update)
        if not se:
            raise NotFound("Stock Entry not found.")
        ensure_scope_by_ids(context=context, target_company_id=se.company_id, target_branch_id=se.branch_id)
        return se

    def _generate_or_validate_code(self, company_id: int, branch_id: int, manual_code: Optional[str]) -> str:
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_lines(self, company_id: int, branch_id: int, entry_type: StockEntryType, lines: List[Dict]) -> List[Dict]:
        V.validate_list_not_empty(lines, "items")

        # Uniqueness by (item_id, source_warehouse_id, target_warehouse_id)
        seen: Set[Tuple[int, Optional[int], Optional[int]]] = set()
        for ln in lines:
            key = (ln.get("item_id"), ln.get("source_warehouse_id"), ln.get("target_warehouse_id"))
            if key in seen:
                raise V.BizValidationError("Duplicate item/warehouse combination.")
            seen.add(key)

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.repo.get_item_details_batch(company_id, item_ids)
        normalized = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized])
        V.validate_no_service_items(normalized)

        # UOM presence and compatibility
        uom_ids = [ln["uom_id"] for ln in normalized if ln.get("uom_id")]
        if uom_ids:
            existing_uoms = self.repo.get_existing_uom_ids(company_id, uom_ids)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized if ln.get("uom_id")]
        compat = self.repo.get_compatible_uom_pairs(company_id, pairs)
        for ln in normalized:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compat
        V.validate_item_uom_compatibility(normalized)

        for ln in normalized:
            V.validate_positive_quantity(Decimal(str(ln["quantity"])))
            V.validate_non_negative_rate(Decimal(str(ln.get("rate", 0))))

        # Warehouses by type
        src_ids = [ln["source_warehouse_id"] for ln in normalized if ln.get("source_warehouse_id")]
        tgt_ids = [ln["target_warehouse_id"] for ln in normalized if ln.get("target_warehouse_id")]
        if src_ids:
            valid_src = self.repo.get_transactional_warehouse_ids(company_id, branch_id, src_ids)
            for ln in normalized:
                if ln.get("source_warehouse_id") and ln["source_warehouse_id"] not in valid_src:
                    raise V.BizValidationError("Invalid or non-transactional source warehouse.")
        if tgt_ids:
            valid_tgt = self.repo.get_transactional_warehouse_ids(company_id, branch_id, tgt_ids)
            for ln in normalized:
                if ln.get("target_warehouse_id") and ln["target_warehouse_id"] not in valid_tgt:
                    raise V.BizValidationError("Invalid or non-transactional target warehouse.")

        # Per-type structure checks (defensive; schemas already did the first pass)
        for ln in normalized:
            if entry_type == StockEntryType.MATERIAL_RECEIPT:
                if not ln.get("target_warehouse_id") or ln.get("source_warehouse_id"):
                    raise V.BizValidationError("Receipt requires target warehouse only.")
            elif entry_type == StockEntryType.MATERIAL_ISSUE:
                if not ln.get("source_warehouse_id") or ln.get("target_warehouse_id"):
                    raise V.BizValidationError("Issue requires source warehouse only.")
            elif entry_type == StockEntryType.MATERIAL_TRANSFER:
                if not ln.get("source_warehouse_id") or not ln.get("target_warehouse_id"):
                    raise V.BizValidationError("Transfer requires both warehouses.")
                if ln["source_warehouse_id"] == ln["target_warehouse_id"]:
                    raise V.BizValidationError("Transfer requires different source and target.")

        return normalized

    def _get_doc_type_id_or_400(self) -> int:
        dt = self.repo.get_doc_type_id_by_code("STOCK_ENTRY")
        if not dt:
            raise V.BizValidationError("DocumentType 'STOCK_ENTRY' not found. Seed the Document Types table.")
        return dt

    # ---------------- Create / Update ----------------

    def create_stock_entry(self, *, payload: StockEntryCreate, context: AffiliationContext) -> StockEntry:
        lines_data = [ln.model_dump() for ln in payload.items]

        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        normalized = self._validate_lines(company_id, branch_id, payload.stock_entry_type, lines_data)

        try:
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            se = StockEntry(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                code=code,
                posting_date=payload.posting_date,
                stock_entry_type=payload.stock_entry_type,
                doc_status=DocStatusEnum.DRAFT,
                items=[StockEntryItem(**ln) for ln in normalized],
            )
            self.repo.save(se)
            self.s.commit()
            return se
        except Exception:
            self.s.rollback()
            raise

    def update_stock_entry(self, *, se_id: int, payload: StockEntryUpdate, context: AffiliationContext) -> StockEntry:
        try:
            se = self._get_validated_entry(se_id, context, for_update=True)
            V.guard_updatable_state(se.doc_status)

            if payload.posting_date:
                se.posting_date = payload.posting_date
            if payload.stock_entry_type:
                se.stock_entry_type = payload.stock_entry_type

            if payload.items is not None:
                lines_data = [ln.model_dump(exclude_unset=True) for ln in payload.items]
                normalized = self._validate_lines(se.company_id, se.branch_id, se.stock_entry_type, lines_data)
                self.repo.sync_lines(se, normalized)

            self.repo.save(se)
            self.s.commit()
            return se
        except Exception:
            self.s.rollback()
            raise

    # ---------------- Submit / Cancel ----------------

    def submit_stock_entry(self, *, se_id: int, context: AffiliationContext) -> StockEntry:
        try:
            logging.info("SE submit: start se_id=%s", se_id)

            se = self._get_validated_entry(se_id, context, for_update=False)
            V.guard_submittable_state(se.doc_status)
            V.validate_list_not_empty(se.items, "items for submission")

            doc_type_id = self._get_doc_type_id_or_400()

            posting_dt: datetime = resolve_posting_dt(
                se.posting_date, created_at=getattr(se, "created_at", None),
            )

            # Build intended locks/pairs & backdated probe
            pairs: Set[Tuple[int, int]] = set()
            if se.stock_entry_type == StockEntryType.MATERIAL_RECEIPT:
                pairs = {(ln.item_id, ln.target_warehouse_id) for ln in se.items}
            elif se.stock_entry_type == StockEntryType.MATERIAL_ISSUE:
                pairs = {(ln.item_id, ln.source_warehouse_id) for ln in se.items}
            elif se.stock_entry_type == StockEntryType.MATERIAL_TRANSFER:
                for ln in se.items:
                    pairs.add((ln.item_id, ln.source_warehouse_id))
                    pairs.add((ln.item_id, ln.target_warehouse_id))

            is_backdated = self.repo.has_future_sle(se.company_id, posting_dt, pairs)
            self.s.rollback()

            # Atomic write
            with self.s.begin():
                se_locked = self._get_validated_entry(se_id, context, for_update=True)
                V.guard_submittable_state(se_locked.doc_status)

                se_locked.doc_status = DocStatusEnum.SUBMITTED
                # Persist the precise timestamp used
                se_locked.posting_date = posting_dt
                self.repo.save(se_locked)

                with lock_pairs(pairs):
                    if se_locked.stock_entry_type == StockEntryType.MATERIAL_RECEIPT:
                        # +qty into target, incoming_rate = line.rate
                        for ln in se_locked.items:
                            append_sle(SLEIntent(
                                company_id=se_locked.company_id,
                                branch_id=se_locked.branch_id,
                                item_id=ln.item_id,
                                warehouse_id=ln.target_warehouse_id,
                                posting_dt=posting_dt,
                                actual_qty=Decimal(str(ln.quantity)),
                                incoming_rate=Decimal(str(ln.rate)),
                                outgoing_rate=None,
                                stock_value_difference=Decimal("0"),
                                doc_type_id=doc_type_id,
                                doc_id=se_locked.id,
                                doc_row_id=ln.id,
                                adjustment_type=AdjustmentType.NORMAL,
                                meta={}
                            ))

                    elif se_locked.stock_entry_type == StockEntryType.MATERIAL_ISSUE:
                        # -qty from source, outgoing at MA (implicit)
                        for ln in se_locked.items:
                            append_sle(SLEIntent(
                                company_id=se_locked.company_id,
                                branch_id=se_locked.branch_id,
                                item_id=ln.item_id,
                                warehouse_id=ln.source_warehouse_id,
                                posting_dt=posting_dt,
                                actual_qty=Decimal(str(-ln.quantity)),
                                incoming_rate=None,
                                outgoing_rate=None,
                                stock_value_difference=Decimal("0"),
                                doc_type_id=doc_type_id,
                                doc_id=se_locked.id,
                                doc_row_id=ln.id,
                                adjustment_type=AdjustmentType.NORMAL,
                                meta={}
                            ))

                    elif se_locked.stock_entry_type == StockEntryType.MATERIAL_TRANSFER:
                        # Two legs per line: issue from source (capture out_rate), then receipt to target with same in_rate
                        for ln in se_locked.items:
                            issue = append_sle(SLEIntent(
                                company_id=se_locked.company_id,
                                branch_id=se_locked.branch_id,
                                item_id=ln.item_id,
                                warehouse_id=ln.source_warehouse_id,
                                posting_dt=posting_dt,
                                actual_qty=Decimal(str(-ln.quantity)),
                                incoming_rate=None,
                                outgoing_rate=None,
                                stock_value_difference=Decimal("0"),
                                doc_type_id=doc_type_id,
                                doc_id=se_locked.id,
                                doc_row_id=ln.id,
                                adjustment_type=AdjustmentType.NORMAL,
                                meta={}
                            ))
                            in_rate = issue.outgoing_rate or Decimal("0")
                            append_sle(SLEIntent(
                                company_id=se_locked.company_id,
                                branch_id=se_locked.branch_id,
                                item_id=ln.item_id,
                                warehouse_id=ln.target_warehouse_id,
                                posting_dt=posting_dt,
                                actual_qty=Decimal(str(ln.quantity)),
                                incoming_rate=in_rate,
                                outgoing_rate=None,
                                stock_value_difference=Decimal("0"),
                                doc_type_id=doc_type_id,
                                doc_id=se_locked.id,
                                doc_row_id=ln.id,
                                adjustment_type=AdjustmentType.NORMAL,
                                meta={}
                            ))

            # Post-commit
            if is_backdated:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        repost_from(company_id=se.company_id, item_id=item_id, warehouse_id=wh_id, start_dt=posting_dt)
            else:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        derive_bin(item_id, wh_id)

            logging.info("SE submit: success id=%s code=%s", se.id, se.code)
            return se

        except Exception:
            logging.exception("SE submit: FAILED", extra={"se_id": se_id})
            self.s.rollback()
            raise

    def cancel_stock_entry(self, *, se_id: int, context: AffiliationContext) -> StockEntry:
        try:
            logging.info("SE cancel: start se_id=%s", se_id)

            se = self._get_validated_entry(se_id, context, for_update=False)
            V.guard_cancellable_state(se.doc_status)

            # Find SLEs posted by this document
            doc_type_id = self._get_doc_type_id_or_400()
            rows = (
                self.s.query(
                    StockLedgerEntry.id,
                    StockLedgerEntry.item_id,
                    StockLedgerEntry.warehouse_id,
                    StockLedgerEntry.posting_time,
                )
                .filter(
                    StockLedgerEntry.company_id == se.company_id,
                    StockLedgerEntry.doc_type_id == doc_type_id,
                    StockLedgerEntry.doc_id == se.id,
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

            if not rows:
                # Status flip only
                self.s.rollback()
                with self.s.begin():
                    se_locked = self._get_validated_entry(se_id, context, for_update=True)
                    V.guard_cancellable_state(se_locked.doc_status)
                    se_locked.doc_status = DocStatusEnum.CANCELLED
                    self.repo.save(se_locked)
                return se_locked

            pairs = {(r.item_id, r.warehouse_id) for r in rows}
            start_dt = min(r.posting_time for r in rows)
            is_backdated = self.repo.has_future_sle(se.company_id, start_dt, pairs)
            self.s.rollback()

            # Atomic reversal
            from app.application_stock.engine.sle_writer import cancel_sle
            with self.s.begin():
                se_locked = self._get_validated_entry(se_id, context, for_update=True)
                V.guard_cancellable_state(se_locked.doc_status)
                se_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(se_locked)

                with lock_pairs(pairs):
                    originals = (
                        self.s.query(StockLedgerEntry)
                        .filter(
                            StockLedgerEntry.company_id == se_locked.company_id,
                            StockLedgerEntry.doc_type_id == doc_type_id,
                            StockLedgerEntry.doc_id == se_locked.id,
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

            # Post-commit
            if is_backdated:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        repost_from(company_id=se.company_id, item_id=item_id, warehouse_id=wh_id, start_dt=start_dt)
            else:
                for item_id, wh_id in pairs:
                    with self.s.begin():
                        derive_bin(item_id, wh_id)

            logging.info("SE cancel: success id=%s code=%s", se.id, se.code)
            return se

        except Exception:
            logging.exception("SE cancel: FAILED", extra={"se_id": se_id})
            self.s.rollback()
            raise
