from __future__ import annotations

import logging

from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum

from sqlalchemy import and_, select, exists, or_
from werkzeug.exceptions import NotFound, Conflict
from sqlalchemy.orm import Session

from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.stock_models import DocumentType, StockLedgerEntry
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.handlers.purchase import build_intents_for_receipt
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,                 # used for persisted docs
    resolve_company_branch_and_scope,    # << Way B (canonicalize + scope)
)

# Business Logic Imports
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum, StockLedgerEntry, DocumentType
from app.application_buying.repository.receipt_repo import PurchaseReceiptRepository
from app.application_buying.schemas import PurchaseReceiptCreate, PurchaseReceiptUpdate
from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem

# Validation helpers
import app.business_validation.item_validation as V
from datetime import datetime, time, timezone, date, timedelta


class PurchaseReceiptService:
    """Service layer for managing Purchase Receipts with a strict workflow."""
    PREFIX = "PR"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseReceiptRepository(self.s)

    # ---- internal helpers ----------------------------------------------------
    def _get_validated_receipt(
        self, receipt_id: int, context: AffiliationContext, for_update: bool = False
    ) -> PurchaseReceipt:
        """Fetch, ensure scope to the persisted doc, and optionally lock."""
        pr = self.repo.get_by_id(receipt_id, for_update=for_update)
        if not pr:
            raise NotFound("Purchase Receipt not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=pr.company_id,
            target_branch_id=pr.branch_id,
        )
        return pr

    def _generate_or_validate_code(
        self, company_id: int, branch_id: int, manual_code: Optional[str]
    ) -> str:
        """Generate a document code or validate a manually provided one."""
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code
            )
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(self, company_id: int, branch_id: int, supplier_id: int, warehouse_id: int) -> None:
        """Batch validate header-level master data."""
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)

        valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, branch_id, [warehouse_id])
        V.validate_warehouse_is_transactional(warehouse_id in valid_warehouses)

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        """Validate item lines and enrich for further checks."""
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.repo.get_item_details_batch(company_id, item_ids)

        normalized_lines = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized_lines])
        V.validate_no_service_items(normalized_lines)
        V.validate_uom_present_for_stock_items(normalized_lines)

        uom_ids_to_check = [ln["uom_id"] for ln in normalized_lines if ln.get("uom_id")]
        if uom_ids_to_check:
            existing_uoms = self.repo.get_existing_uom_ids(company_id, uom_ids_to_check)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids_to_check])

        uom_pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized_lines if ln.get("uom_id")]
        compatible_pairs = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
        for ln in normalized_lines:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compatible_pairs
        V.validate_item_uom_compatibility(normalized_lines)

        for ln in normalized_lines:
            V.validate_positive_quantity(ln["received_qty"])
            V.validate_accepted_quantity_logic(ln["received_qty"], ln["accepted_qty"])
            V.validate_positive_price(ln.get("unit_price"))

        return normalized_lines

    def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
        """Σ(accepted_qty * unit_price) where price is present."""
        return sum(
            Decimal(str(ln["accepted_qty"])) * Decimal(str(ln["unit_price"]))
            for ln in lines if ln.get("unit_price") is not None
        )

    # ---- public API ----------------------------------------------------------
    def create_purchase_receipt(self, *, payload: PurchaseReceiptCreate, context: AffiliationContext) -> PurchaseReceipt:
        """
        Way B: canonicalize (company_id, branch_id) from the branch row and enforce scope,
        using the shared helper for zero duplication across modules.
        """
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,  # repo must provide this
            require_branch=True,
        )

        try:
            self._validate_header(company_id, branch_id, payload.supplier_id, payload.warehouse_id)

            lines_data = [ln.model_dump() for ln in payload.items]
            self._validate_and_normalize_lines(company_id, lines_data)

            code = self._generate_or_validate_code(company_id, branch_id, payload.code)

            pr = PurchaseReceipt(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=payload.supplier_id,
                warehouse_id=payload.warehouse_id,
                code=code,
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                remarks=payload.remarks,
                total_amount=self._calculate_total_amount(lines_data),
                items=[PurchaseReceiptItem(**ln) for ln in lines_data],
            )
            self.repo.save(pr)
            self.s.commit()
            return pr

        except Exception:
            self.s.rollback()
            raise

    def update_purchase_receipt(self, *, receipt_id: int, payload: PurchaseReceiptUpdate, context: AffiliationContext) -> PurchaseReceipt:
        try:
            pr = self._get_validated_receipt(receipt_id, context, for_update=True)
            V.guard_draft_only(pr.doc_status)

            header_changed = False
            if payload.supplier_id is not None and payload.supplier_id != pr.supplier_id:
                pr.supplier_id = payload.supplier_id
                header_changed = True
            if payload.warehouse_id is not None and payload.warehouse_id != pr.warehouse_id:
                pr.warehouse_id = payload.warehouse_id
                header_changed = True

            if header_changed:
                self._validate_header(pr.company_id, pr.branch_id, pr.supplier_id, pr.warehouse_id)

            if payload.posting_date:
                pr.posting_date = payload.posting_date
            if payload.remarks is not None:
                pr.remarks = payload.remarks

            if payload.items is not None:
                lines_data = [ln.model_dump() for ln in payload.items]
                self._validate_and_normalize_lines(pr.company_id, lines_data)
                self.repo.sync_lines(pr, lines_data)
                pr.total_amount = self._calculate_total_amount(lines_data)

            self.repo.save(pr)
            self.s.commit()
            return pr

        except Exception:
            self.s.rollback()
            raise

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            # make it a clean 400 so the endpoint returns a business error, not a 500
            raise V.BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
        return dt

    @staticmethod
    def _combine_date(posting_date_val: date | datetime) -> datetime:
        """Return a proper datetime with time component for stock posting."""
        return resolve_posting_dt(posting_date_val)



    def submit_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        """
        Strictly atomic submit using a SAVEPOINT (begin_nested):
          - append SLEs
          - backdated replay (if needed)
          - derive BINs
          - post GL (AUTO JE)
          - mark PR SUBMITTED
        Any failure rolls back the whole savepoint; no partial effects.
        """
        from sqlalchemy import and_, select, func, desc
        import logging

        try:
            # ---- 1) READ PHASE (no locks) ---------------------------------------
            logging.info("PR submit: start receipt_id=%s", receipt_id)

            pr = self._get_validated_receipt(receipt_id, context, for_update=False)
            V.guard_submittable_state(pr.doc_status)
            V.validate_list_not_empty(pr.items, "items for submission")
            self._validate_header(pr.company_id, pr.branch_id, pr.supplier_id, pr.warehouse_id)

            lines_snap = [{
                "item_id": i.item_id,
                "uom_id": i.uom_id,
                "received_qty": i.received_qty,
                "accepted_qty": i.accepted_qty,
                "unit_price": i.unit_price,
                "doc_row_id": i.id,
            } for i in pr.items]

            # Log raw API payload
            logging.info("PR submit: Raw API payload accepted_qty values: %s", [i.accepted_qty for i in pr.items])

            norm = self._validate_and_normalize_lines(pr.company_id, lines_snap)

            # Log validation results
            for ln in norm:
                if "accepted_qty" in ln:
                    qty_str = str(ln["accepted_qty"])
                    try:
                        dec_qty = Decimal(qty_str)
                        logging.info("PR submit: Validating accepted_qty: %s -> %s", qty_str, dec_qty)
                    except Exception as e:
                        logging.error("PR submit: FAILED TO CONVERT accepted_qty: %s with error: %s", qty_str, e)

            stock_lines = [ln for ln in norm if Decimal(str(ln.get("accepted_qty") or 0)) > 0]
            V.validate_list_not_empty(stock_lines, "accepted stock items")

            doc_type_id = self._get_doc_type_id_or_400("PURCHASE_RECEIPT")
            # posting_dt = resolve_posting_dt(pr.posting_date)
            # treat PR.posting_date as date-only, borrow created_at time-of-day, add micro-bump
            posting_dt = resolve_posting_dt(
                pr.posting_date.date() if hasattr(pr.posting_date, "date") else pr.posting_date,
                created_at=pr.created_at,
                tz=timezone(timedelta(hours=3)),  # or your configured company tz
                treat_midnight_as_date=True,
            )

            # Log timezone information
            logging.info("PR submit: posting_dt=%s (timezone: %s)", posting_dt, posting_dt.tzinfo)

            intents = build_intents_for_receipt(
                company_id=pr.company_id,
                branch_id=pr.branch_id,
                warehouse_id=pr.warehouse_id,
                posting_dt=posting_dt,
                doc_type_id=doc_type_id,
                doc_id=pr.id,
                lines=[{
                    "item_id": ln["item_id"],
                    "accepted_qty": ln["accepted_qty"],
                    "unit_price": ln["unit_price"],
                    "doc_row_id": ln["doc_row_id"],
                } for ln in stock_lines],
            )
            if not intents:
                raise V.BizValidationError("No stock intents were generated from accepted lines.")

            pairs: Set[Tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}
            logging.info(
                "PR submit: snapshot ok | pr_id=%s doc_type_id=%s posting_dt=%s intents=%s pairs=%s",
                pr.id, doc_type_id, posting_dt.isoformat(), len(intents), len(pairs)
            )

            # Backdating check
            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
                    StockLedgerEntry.company_id == pr.company_id,
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
                )
                return (q.scalar() or 0) > 0

            is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
            logging.info("PR submit: backdated=%s | pairs=%s", is_backdated, list(pairs))

            # ---- 2) ATOMIC WRITE PHASE (SAVEPOINT) ------------------------------
            with self.s.begin_nested():
                pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)
                V.guard_submittable_state(pr_locked.doc_status)

                # 2a) SLEs under advisory locks
                sle_written = 0
                with lock_pairs(self.s, pairs):
                    for intent in intents:
                        logging.info("PR submit: Final intent for SLE before append: %s", {
                            "item_id": intent.item_id,
                            "warehouse_id": intent.warehouse_id,
                            "actual_qty": intent.actual_qty,
                            "incoming_rate": intent.incoming_rate,
                            "doc_id": intent.doc_id,
                        })
                        sle = append_sle(self.s, intent)
                        sle_written += 1
                        logging.info("PR submit: SLE appended | pr_id=%s sle_id=%s sle_written=%s",
                                     pr_locked.id, sle.id, sle_written)

                        # Debug: Check latest SLEs in session
                        try:
                            latest_sles = self.s.query(StockLedgerEntry).order_by(StockLedgerEntry.id.desc()).limit(
                                10).all()
                            logging.info("PR submit: DEBUG SLE ids in-session (latest 10): %s",
                                         [sle.id for sle in latest_sles])
                        except Exception:
                            logging.exception("DEBUG: failed to list in-session SLE ids")

                        # Check the latest SLE for this item/warehouse
                        try:
                            latest_sle = (self.s.query(StockLedgerEntry)
                                          .filter_by(item_id=intent.item_id, warehouse_id=intent.warehouse_id,
                                                     is_cancelled=False)
                                          .order_by(StockLedgerEntry.posting_date.desc(),
                                                    StockLedgerEntry.posting_time.desc(),
                                                    StockLedgerEntry.id.desc())
                                          .first())

                            if latest_sle:
                                logging.info("PR submit: DEBUG latest SLE (item=%s,wh=%s): (%s, %s, %s, %s)",
                                             intent.item_id, intent.warehouse_id, latest_sle.id, latest_sle.actual_qty,
                                             latest_sle.valuation_rate, latest_sle.posting_time)
                            else:
                                logging.info("PR submit: DEBUG no SLE found for item=%s, wh=%s",
                                             intent.item_id, intent.warehouse_id)
                        except Exception:
                            logging.exception("DEBUG: failed to pull latest SLE snapshot")

                if sle_written != len(intents):
                    raise RuntimeError(f"SLE append mismatch (expected {len(intents)}, wrote {sle_written}).")
                logging.info("PR submit: SLE appended | pr_id=%s sle_written=%s", pr_locked.id, sle_written)

                # 2b) Backdated replay
                if is_backdated:
                    for item_id, wh_id in pairs:
                        logging.info("PR submit: Starting replay for item=%s, wh=%s", item_id, wh_id)

                        # IMPORTANT: Remove the doc_type exclusion to ensure all transactions are reposted
                        repost_from(
                            s=self.s,
                            company_id=pr_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set()  # Empty set means no exclusions
                        )
                    logging.info("PR submit: replay done for pairs=%s", list(pairs))

                # 2c) Derive BINs
                bins_updated = 0
                for item_id, wh_id in pairs:
                    logging.info("PR submit: Deriving bin for item=%s, wh=%s", item_id, wh_id)
                    bin_obj = derive_bin(self.s, pr_locked.company_id, item_id, wh_id)
                    bins_updated += 1

                    # Log bin details
                    try:
                        logging.info("PR submit: DEBUG BIN after derive (item=%s,wh=%s): %s",
                                     item_id, wh_id, bin_obj.__dict__ if bin_obj else None)
                    except Exception:
                        logging.exception("DEBUG: failed to inspect BIN after derive")

                logging.info("PR submit: bins derived | pr_id=%s bins_updated=%s", pr_locked.id, bins_updated)

                # 2d) GL post (AUTO) — PostingService
                from app.application_accounting.engine.posting_service import PostingService, PostingContext
                from app.application_accounting.chart_of_accounts.models import PartyTypeEnum

                acc_lines = [{"accepted_qty": ln["accepted_qty"], "unit_price": ln["unit_price"]} for ln in stock_lines]
                ctx = PostingContext(
                    company_id=pr_locked.company_id,
                    branch_id=pr_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=pr_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"Purchase Receipt {pr_locked.id}",
                    template_code="PURCHASE_RECEIPT_GRNI",
                    payload={
                        "receipt_lines": acc_lines,
                        "document_subtotal": None,
                        "tax_amount": None,
                        "document_total": None,
                    },
                    runtime_accounts={},
                    party_id=pr_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                )
                PostingService(self.s).post(ctx)
                logging.info("PR submit: GL posted | pr_id=%s lines=%s", pr_locked.id, len(acc_lines))

                # 2e) Mark SUBMITTED
                pr_locked.doc_status = DocStatusEnum.SUBMITTED
                self.repo.save(pr_locked)
                logging.info("PR submit: status -> SUBMITTED | pr_id=%s code=%s", pr_locked.id, pr_locked.code)

            # ---- 3) COMMIT OUTER TX ---------------------------------------------
            logging.info("PR submit: committing outer transaction for pr_id=%s", pr.id)
            self.s.commit()

            # ---- 4) Post-commit SLE sanity --------------------------------------
            try:
                cnt = self.s.execute(
                    select(func.count()).select_from(StockLedgerEntry).where(
                        StockLedgerEntry.company_id == pr.company_id,
                        StockLedgerEntry.doc_type_id == doc_type_id,
                        StockLedgerEntry.doc_id == pr.id,
                        StockLedgerEntry.is_cancelled == False,
                    )
                ).scalar()
                logging.info("DEBUG post-commit: SLE count for PR id=%s -> %s", pr.id, cnt)
            except Exception:
                logging.exception("DEBUG post-commit: failed to count SLE for PR")

            logging.info("PR submit: success | pr_id=%s code=%s", pr.id, pr.code)
            return pr

        except Exception:
            logging.exception("PR submit: FAILED (rolled back) | receipt_id=%s", receipt_id)
            self.s.rollback()
            raise


    # -------------------------------------------------------------------------
    # CANCEL — Reverse Stock + Accounting
    # -------------------------------------------------------------------------

    def cancel_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        """
        CANCEL flow:
          1) Read phase: validate; collect SLEs (not cancelled, not reversals).
          2) Write phase (SAVEPOINT): lock PR, set CANCELLED, write reversal SLEs under advisory locks.
          3) Commit outer transaction.
          4) Post-commit stock maintenance:
               - backdated -> replay valuation forward from earliest SLE posting_time
               - else      -> derive BINs
          5) Accounting reversal via PostingService.cancel (auto JE).
        """
        try:
            logging.info("PR cancel: start receipt_id=%s", receipt_id)

            # ---- 1) READ PHASE ----------------------------------------------------
            pr = self._get_validated_receipt(receipt_id, context, for_update=False)
            V.guard_cancellable_state(pr.doc_status)

            doc_type_id = self._get_doc_type_id_or_400("PURCHASE_RECEIPT")

            sle_rows = (
                self.s.query(
                    StockLedgerEntry.id,
                    StockLedgerEntry.item_id,
                    StockLedgerEntry.warehouse_id,
                    StockLedgerEntry.posting_time,
                )
                .filter(
                    StockLedgerEntry.company_id == pr.company_id,
                    StockLedgerEntry.doc_type_id == doc_type_id,
                    StockLedgerEntry.doc_id == pr.id,
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

            # If no SLEs -> still cancel PR and reverse GL.
            if not sle_rows:
                self.s.rollback()
                with self.s.begin():
                    pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)
                    V.guard_cancellable_state(pr_locked.doc_status)
                    pr_locked.doc_status = DocStatusEnum.CANCELLED
                    self.repo.save(pr_locked)

                # Accounting reversal (separate tx)
                with self.s.begin():
                    # FIX: avoid midnight collisions for accounting reversal timestamp
                    acct_posting_dt = resolve_posting_dt(
                        pr_locked.posting_date if not hasattr(pr_locked.posting_date, "date") else pr_locked.posting_date,
                        created_at=getattr(pr_locked, "created_at", None),
                        tz=timezone(timedelta(hours=3)),           # TODO: plug company/system TZ
                        treat_midnight_as_date=True,
                    )
                    PostingService(self.s).cancel(
                        PostingContext(
                            company_id=pr_locked.company_id,
                            branch_id=pr_locked.branch_id,
                            source_doctype_id=doc_type_id,
                            source_doc_id=pr_locked.id,
                            posting_date=acct_posting_dt,            # FIX: tz-aware, non-midnight
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=None,
                            remarks=f"Cancel Purchase Receipt {pr_locked.id}",
                            template_code=None,
                            payload={},
                            runtime_accounts={},
                            party_id=pr_locked.supplier_id,
                            party_type=PartyTypeEnum.SUPPLIER,
                        )
                    )

                logging.info("PR cancel: success (no stock effects) id=%s code=%s", pr.id, pr.code)
                return pr_locked

            pairs: Set[Tuple[int, int]] = {(r.item_id, r.warehouse_id) for r in sle_rows}
            start_dt: datetime = min(r.posting_time for r in sle_rows)

            # FIX: ensure tz-aware start_dt for consistent comparisons
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = (
                    self.s.query(StockLedgerEntry.id)
                    .filter(
                        StockLedgerEntry.company_id == pr.company_id,
                        StockLedgerEntry.item_id == item_id,
                        StockLedgerEntry.warehouse_id == wh_id,
                        (
                            (StockLedgerEntry.posting_date > start_dt.date())
                            | and_(
                                StockLedgerEntry.posting_date == start_dt.date(),
                                StockLedgerEntry.posting_time > start_dt,
                            )
                        ),
                        StockLedgerEntry.is_cancelled == False,  # noqa: E712
                    )
                    .limit(1)
                )
                return self.s.query(q.exists()).scalar()

            is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
            logging.info("PR cancel: backdated=%s | pairs=%s", is_backdated, list(pairs))

            # Close any implicit tx before the write phase
            self.s.rollback()

            # ---- 2) WRITE PHASE (SAVEPOINT) ---------------------------------------
            with self.s.begin_nested():
                pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)
                V.guard_cancellable_state(pr_locked.doc_status)

                pr_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(pr_locked)

                # Reverse exactly the PR’s SLEs under advisory locks
                with lock_pairs(self.s, pairs):
                    originals = (
                        self.s.query(StockLedgerEntry)
                        .filter(
                            StockLedgerEntry.company_id == pr_locked.company_id,
                            StockLedgerEntry.doc_type_id == doc_type_id,
                            StockLedgerEntry.doc_id == pr_locked.id,
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
                        # cancel_sle() already pushes reversal by +1µs after original
                        cancel_sle(self.s, original)

            # ---- 3) COMMIT OUTER TX BEFORE MAINTENANCE ----------------------------
            self.s.commit()

            # ---- 4) POST-COMMIT STOCK MAINTENANCE ---------------------------------
            if is_backdated:
                with self.s.begin():
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=pr.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=start_dt,  # FIX: tz-aware earliest original time
                        )
                logging.info("PR cancel: replay done for pairs=%s", list(pairs))
            else:
                with self.s.begin():
                    for item_id, wh_id in pairs:
                        derive_bin(self.s, pr.company_id, item_id, wh_id)
                logging.info("PR cancel: bins derived for pairs=%s", list(pairs))

            # ---- 5) ACCOUNTING REVERSAL -------------------------------------------
            with self.s.begin():
                # FIX: avoid midnight collisions and ensure tz-aware reversal timestamp
                acct_posting_dt = resolve_posting_dt(
                    pr.posting_date if not hasattr(pr.posting_date, "date") else pr.posting_date,
                    created_at=getattr(pr, "created_at", None),
                    tz=timezone(timedelta(hours=3)),               # TODO: plug company/system TZ
                    treat_midnight_as_date=True,
                )
                PostingService(self.s).cancel(
                    PostingContext(
                        company_id=pr.company_id,
                        branch_id=pr.branch_id,
                        source_doctype_id=doc_type_id,
                        source_doc_id=pr.id,
                        posting_date=acct_posting_dt,                # FIX
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=None,
                        remarks=f"Cancel Purchase Receipt {pr.id}",
                        template_code=None,
                        payload={},
                        runtime_accounts={},
                        party_id=pr.supplier_id,
                        party_type=PartyTypeEnum.SUPPLIER,
                    )
                )

            logging.info("PR cancel: success id=%s code=%s", pr.id, pr.code)
            return pr

        except Exception:
            logging.exception("PR cancel: FAILED", extra={"receipt_id": receipt_id})
            self.s.rollback()
            raise
