# app/application_stock/reconciliation_service.py

from __future__ import annotations

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, select

from app.application_stock.engine.sle_helpers import create_reconciliation_intent
from app.application_stock.repo.reconciliation_repo  import StockReconciliationRepository
from app.application_stock.stock_models import StockReconciliation, StockReconciliationItem, \
    StockReconciliationPurpose
from app.application_stock.stock_models import DocumentType, StockLedgerEntry, DocStatusEnum
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.handlers.reconciliation import build_intents_for_reconciliation
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.sle_writer import append_sle, _last_sle_before_dt
from app.application_stock.engine.bin_derive import derive_bin

from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation.item_validation import BizValidationError, DocumentStateError, guard_draft_only, \
    guard_submittable_state, guard_cancellable_state

from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope

from config.database import db

logger = logging.getLogger(__name__)


class StockReconciliationService:
    """Service layer for managing Stock Reconciliation with strict workflow."""
    # PREFIX = "MAT-RECO"
    PREFIX = "SRE"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = StockReconciliationRepository(self.s)

    # ---- Internal Helpers ----------------------------------------------------

    def _get_validated_reconciliation(
            self, recon_id: int, context: AffiliationContext, for_update: bool = False
    ) -> StockReconciliation:
        """Fetch, ensure scope to the persisted doc, and optionally lock."""
        recon = self.repo.get_by_id(recon_id, for_update=for_update)
        if not recon:
            raise BizValidationError("Stock Reconciliation not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=recon.company_id,
            target_branch_id=recon.branch_id,
        )
        return recon

    def _generate_or_validate_code(
            self, company_id: int, branch_id: int, manual_code: Optional[str]
    ) -> str:
        """Generate a document code or validate a manually provided one."""
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code
            )
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> None:
        """Batch validate header-level master data."""
        valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, branch_id, warehouse_ids)
        if len(valid_warehouses) != len(warehouse_ids):
            raise BizValidationError("One or more warehouses are invalid or not transactional.")

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        """Validate item lines and enrich for stock processing."""
        from app.business_validation import item_validation as V

        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        warehouse_ids = [ln["warehouse_id"] for ln in lines]
        item_details = self.repo.get_item_details_batch(company_id, item_ids)

        # Create working copy with item details for validation
        working_lines = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        # Perform all validations
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in working_lines])
        V.validate_no_service_items(working_lines)

        for ln in working_lines:
            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln.get("valuation_rate"))

        # Validate warehouses
        valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, company_id, warehouse_ids)
        if len(valid_warehouses) != len(set(warehouse_ids)):
            raise BizValidationError("One or more warehouses are invalid.")

        # ✅ CORRECTED: Only include fields that exist in StockReconciliationItem model
        normalized_lines = []
        for ln in working_lines:
            clean_line = {
                "item_id": ln["item_id"],
                "warehouse_id": ln["warehouse_id"],
                "quantity": ln["quantity"],
                "valuation_rate": ln.get("valuation_rate"),
            }
            # ✅ Preserve doc_row_id for submission if it exists
            if "doc_row_id" in ln:
                clean_line["doc_row_id"] = ln["doc_row_id"]

            normalized_lines.append(clean_line)

        return normalized_lines

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
        return dt

    @staticmethod
    def _combine_date(posting_date_val: date | datetime) -> datetime:
        """Return a proper datetime with time component for stock posting."""
        return resolve_posting_dt(posting_date_val)

    def _get_difference_account_id(self, purpose: StockReconciliationPurpose, difference_account_id: Optional[int]) -> \
    Optional[int]:
        """
        Get the appropriate difference account based on purpose.
        Returns account ID or None if not found.
        """
        if difference_account_id:
            return difference_account_id

        # Default accounts based on purpose (Frappe style)
        try:
            from app.application_accounting.chart_of_accounts.models import Account

            if purpose == StockReconciliationPurpose.OPENING_STOCK:
                # Get account ID for 3004 - Opening Balance Equity
                account = self.s.execute(
                    select(Account.id).where(Account.code == "3004")
                ).scalar_one_or_none()
                logger.info("🔍 Looking for default OPENING_STOCK account (3004): %s", account)
                return account
            else:
                # Get account ID for 5015 - Stock Adjustments
                account = self.s.execute(
                    select(Account.id).where(Account.code == "5015")
                ).scalar_one_or_none()
                logger.info("🔍 Looking for default STOCK_RECONCILIATION account (5015): %s", account)
                return account

        except Exception as e:
            logger.error("❌ Error getting default difference account: %s", str(e))
            return None

    # ---- Public API ----------------------------------------------------------
    # def create_stock_reconciliation(
    #         self,
    #         *,
    #         payload: dict,
    #         context: AffiliationContext
    # ) -> StockReconciliation:
    #     """
    #     Production-ready Stock Reconciliation creation with ERPNext-style safety.
    #     - Posting datetime is timezone-aware
    #     - Difference calculation deterministic (Frappe-style)
    #     - Safe handling of optional fields
    #     """
    #     try:
    #         from app.common.timezone.service import get_company_timezone
    #         from datetime import datetime, time
    #         from decimal import Decimal
    #
    #         logger.info("🔄 Creating Stock Reconciliation")
    #
    #         # ---- 1) RESOLVE COMPANY AND BRANCH ----
    #         company_id, branch_id = resolve_company_branch_and_scope(
    #             context=context,
    #             payload_company_id=payload.get("company_id"),
    #             branch_id=payload.get("branch_id") or getattr(context, "branch_id", None),
    #             get_branch_company_id=self.repo.get_branch_company_id,
    #             require_branch=True,
    #         )
    #
    #         # ---- 2) VALIDATE POSTING DATE ----
    #         PostingDateValidator.validate_standalone_document(
    #             s=self.s,
    #             posting_date=payload["posting_date"],
    #             company_id=company_id,
    #         )
    #
    #         # ---- 3) RESOLVE POSTING DATETIME (FIXED - Preserve actual time) ----
    #         company_tz = get_company_timezone(self.s, company_id)
    #         posting_date_input = payload["posting_date"]
    #
    #         # ✅ FIX: Parse the full datetime and preserve the actual time
    #         if isinstance(posting_date_input, str):
    #             # Parse the full ISO datetime string
    #             posting_dt = datetime.fromisoformat(posting_date_input)
    #
    #             # Ensure it's in the company timezone
    #             if posting_dt.tzinfo is None:
    #                 posting_dt = posting_dt.replace(tzinfo=company_tz)
    #             else:
    #                 posting_dt = posting_dt.astimezone(company_tz)
    #         else:
    #             # If it's already a datetime object, ensure proper timezone
    #             posting_dt = posting_date_input
    #             if posting_dt.tzinfo is None:
    #                 posting_dt = posting_dt.replace(tzinfo=company_tz)
    #             else:
    #                 posting_dt = posting_dt.astimezone(company_tz)
    #
    #         logger.info("📅 Resolved posting datetime: %s (timezone: %s)", posting_dt, company_tz)
    #
    #         # ---- 4) VALIDATE HEADER AND NORMALIZE LINES ----
    #         warehouse_ids = list(set([ln["warehouse_id"] for ln in payload["items"]]))
    #         self._validate_header(company_id, branch_id, warehouse_ids)
    #
    #         normalized_lines = self._validate_and_normalize_lines(company_id, payload["items"])
    #         logger.info("✅ Validated %d items", len(normalized_lines))
    #
    #         # ---- 5) GET CURRENT STOCK STATES ----
    #         item_warehouse_pairs = [(ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines]
    #         current_states = self.repo.get_current_stock_state_for_items(
    #             company_id, posting_dt, item_warehouse_pairs
    #         )
    #         logger.info("📊 Fetched current stock states for %d pairs", len(current_states))
    #
    #         # ---- 6) CALCULATE DIFFERENCES (Frappe-style) ----
    #         calculated_lines = []
    #         for line in normalized_lines:
    #             pair = (line["item_id"], line["warehouse_id"])
    #             current_state = current_states.get(pair, {
    #                 "current_qty": Decimal('0'),
    #                 "current_valuation_rate": Decimal('0')
    #             })
    #
    #             counted_qty = Decimal(str(line["quantity"]))
    #             current_qty = current_state["current_qty"]
    #             current_rate = current_state["current_valuation_rate"]
    #             valuation_rate_used = line.get("valuation_rate") or current_rate
    #
    #             qty_difference = counted_qty - current_qty
    #             amount_difference = counted_qty * valuation_rate_used - current_qty * current_rate
    #
    #             calculated_lines.append({
    #                 **line,
    #                 "current_qty": current_qty,
    #                 "current_valuation_rate": current_rate,
    #                 "qty_difference": qty_difference,
    #                 "amount_difference": amount_difference,
    #                 "valuation_rate_used": valuation_rate_used,
    #             })
    #
    #         logger.info("✅ Calculated Frappe-style differences for %d lines", len(calculated_lines))
    #
    #         # ---- 7) GENERATE DOCUMENT CODE ----
    #         code = self._generate_or_validate_code(
    #             company_id=company_id,
    #             branch_id=branch_id,
    #             manual_code=payload.get("code")
    #         )
    #         purpose = StockReconciliationPurpose(payload.get("purpose", "STOCK_RECONCILIATION"))
    #
    #         # ---- 8) CREATE STOCK RECONCILIATION ITEMS ----
    #         recon_items = []
    #         for line in calculated_lines:
    #             item_data = {
    #                 "item_id": line["item_id"],
    #                 "warehouse_id": line["warehouse_id"],
    #                 "quantity": line["quantity"],
    #                 "valuation_rate": line.get("valuation_rate"),
    #                 "current_qty": line["current_qty"],
    #                 "current_valuation_rate": line["current_valuation_rate"],
    #                 "qty_difference": line["qty_difference"],
    #                 "amount_difference": line["amount_difference"],
    #             }
    #
    #             # Include doc_row_id only if model supports it
    #             if hasattr(StockReconciliationItem, "doc_row_id") and "doc_row_id" in line:
    #                 item_data["doc_row_id"] = line["doc_row_id"]
    #
    #             recon_items.append(StockReconciliationItem(**item_data))
    #
    #         # ---- 9) GET DIFFERENCE ACCOUNT ----
    #         difference_account_id = self._get_difference_account_id(
    #             purpose, payload.get("difference_account_id")
    #         )
    #
    #         # ---- 10) CREATE RECONCILIATION DOCUMENT ----
    #         recon = StockReconciliation(
    #             company_id=company_id,
    #             branch_id=branch_id,
    #             created_by_id=context.user_id,
    #             purpose=purpose,
    #             difference_account_id=difference_account_id,
    #             code=code,
    #             posting_date=posting_dt,  # ✅ Now preserves the actual datetime with time
    #             doc_status=DocStatusEnum.DRAFT,
    #             notes=payload.get("notes"),
    #             items=recon_items
    #         )
    #
    #         self.repo.save(recon)
    #         self.s.commit()
    #
    #         logger.info(
    #             "✅ Successfully created Stock Reconciliation %s (ID: %s) with %d items",
    #             recon.code, recon.id, len(recon_items)
    #         )
    #         return recon
    #
    #     except Exception as e:
    #         self.s.rollback()
    #         logger.error("❌ Failed to create Stock Reconciliation: %s", str(e), exc_info=True)
    #         raise BizValidationError(f"Failed to create stock reconciliation: {str(e)}")
    #
    # # ----- Missing Guard & Validation Helpers -----
    # def _validate_posting_date(self, posting_date: datetime, company_id: int) -> None:
    #     """Delegate to PostingDateValidator for standalone documents."""
    #     PostingDateValidator.validate_standalone_document(
    #         s=self.s,
    #         posting_date=posting_date,
    #         company_id=company_id
    #     )
    #
    # # ----- Missing Helper -----
    # def _get_company_timezone(self, company_id: int):
    #     """Return the company's timezone using the shared timezone service."""
    #     from app.common.timezone.service import get_company_timezone
    #     return get_company_timezone(self.s, company_id)
    #
    # def _guard_submittable_state(self, doc_status: DocStatusEnum) -> None:
    #     """Ensure document is in a submittable state (i.e., Draft)."""
    #     guard_submittable_state(doc_status)
    def create_stock_reconciliation(
            self,
            *,
            payload: dict,
            context: AffiliationContext
    ) -> StockReconciliation:
        """
        Production-ready Stock Reconciliation creation with ERPNext-style safety.
        - Posting datetime is timezone-aware
        - Difference calculation deterministic (Frappe-style)
        - Safe handling of optional fields
        """
        try:
            from app.common.timezone.service import get_company_timezone
            from datetime import datetime, time
            from decimal import Decimal

            logger.info("🔄 Creating Stock Reconciliation")

            # ---- 1) RESOLVE COMPANY AND BRANCH ----
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.get("company_id"),
                branch_id=payload.get("branch_id") or getattr(context, "branch_id", None),
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )

            # ---- 2) VALIDATE POSTING DATE ----
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=payload["posting_date"],
                company_id=company_id,
            )

            # ---- 3) RESOLVE POSTING DATETIME (FIXED - Preserve actual time) ----
            company_tz = get_company_timezone(self.s, company_id)
            posting_date_input = payload["posting_date"]

            # ✅ FIX: Parse the full datetime and preserve the actual time
            if isinstance(posting_date_input, str):
                # Parse the full ISO datetime string
                posting_dt = datetime.fromisoformat(posting_date_input)

                # Ensure it's in the company timezone
                if posting_dt.tzinfo is None:
                    posting_dt = posting_dt.replace(tzinfo=company_tz)
                else:
                    posting_dt = posting_dt.astimezone(company_tz)
            else:
                # If it's already a datetime object, ensure proper timezone
                posting_dt = posting_date_input
                if posting_dt.tzinfo is None:
                    posting_dt = posting_dt.replace(tzinfo=company_tz)
                else:
                    posting_dt = posting_dt.astimezone(company_tz)

            logger.info("📅 Resolved posting datetime: %s (timezone: %s)", posting_dt, company_tz)

            # ---- 4) VALIDATE HEADER AND NORMALIZE LINES ----
            warehouse_ids = list(set([ln["warehouse_id"] for ln in payload["items"]]))
            self._validate_header(company_id, branch_id, warehouse_ids)

            normalized_lines = self._validate_and_normalize_lines(company_id, payload["items"])
            logger.info("✅ Validated %d items", len(normalized_lines))

            # ---- 5) GET CURRENT STOCK STATES ----
            item_warehouse_pairs = [(ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines]
            current_states = self.repo.get_current_stock_state_for_items(
                company_id, posting_dt, item_warehouse_pairs
            )
            logger.info("📊 Fetched current stock states for %d pairs", len(current_states))

            # ---- 6) CALCULATE DIFFERENCES (Quantity only - Financial calc in submit) ----
            calculated_lines = []
            for line in normalized_lines:
                pair = (line["item_id"], line["warehouse_id"])
                current_state = current_states.get(pair, {
                    "current_qty": Decimal('0'),
                    "current_valuation_rate": Decimal('0')
                })

                counted_qty = Decimal(str(line["quantity"]))
                current_qty = current_state["current_qty"]
                current_rate = current_state["current_valuation_rate"]
                valuation_rate_used = line.get("valuation_rate") or current_rate

                qty_difference = counted_qty - current_qty

                # ✅ Store only quantity differences here
                # Financial value calculation happens during submit phase in build_intents_for_reconciliation
                calculated_lines.append({
                    **line,
                    "current_qty": current_qty,
                    "current_valuation_rate": current_rate,
                    "qty_difference": qty_difference,
                    "valuation_rate_used": valuation_rate_used,
                    # Note: amount_difference is calculated during submit, not here
                })

                logger.info(
                    f"📦 Line Calculation - Item: {line['item_id']}, Warehouse: {line['warehouse_id']}\n"
                    f"   Current: {current_qty} units @ {current_rate}/unit\n"
                    f"   Counted: {counted_qty} units @ {valuation_rate_used}/unit\n"
                    f"   Adjustment: {qty_difference} units"
                )

            logger.info("✅ Calculated quantity differences for %d lines", len(calculated_lines))

            # ---- 7) GENERATE DOCUMENT CODE ----
            code = self._generate_or_validate_code(
                company_id=company_id,
                branch_id=branch_id,
                manual_code=payload.get("code")
            )
            purpose = StockReconciliationPurpose(payload.get("purpose", "STOCK_RECONCILIATION"))

            # ---- 8) CREATE STOCK RECONCILIATION ITEMS ----
            recon_items = []
            for line in calculated_lines:
                item_data = {
                    "item_id": line["item_id"],
                    "warehouse_id": line["warehouse_id"],
                    "quantity": line["quantity"],  # The counted/physical quantity
                    "valuation_rate": line.get("valuation_rate"),
                    "current_qty": line["current_qty"],
                    "current_valuation_rate": line["current_valuation_rate"],
                    "qty_difference": line["qty_difference"],
                    # Note: amount_difference is not stored here - calculated during submit
                }

                # Include doc_row_id only if model supports it
                if hasattr(StockReconciliationItem, "doc_row_id") and "doc_row_id" in line:
                    item_data["doc_row_id"] = line["doc_row_id"]

                recon_items.append(StockReconciliationItem(**item_data))

            # ---- 9) GET DIFFERENCE ACCOUNT ----
            difference_account_id = self._get_difference_account_id(
                purpose, payload.get("difference_account_id")
            )

            # ---- 10) CREATE RECONCILIATION DOCUMENT ----
            recon = StockReconciliation(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                purpose=purpose,
                difference_account_id=difference_account_id,
                code=code,
                posting_date=posting_dt,  # ✅ Now preserves the actual datetime with time
                doc_status=DocStatusEnum.DRAFT,
                notes=payload.get("notes"),
                items=recon_items
            )

            self.repo.save(recon)
            self.s.commit()

            logger.info(
                "✅ Successfully created Stock Reconciliation %s (ID: %s) with %d items",
                recon.code, recon.id, len(recon_items)
            )

            # Log the expected financial impact (for information only)
            total_qty_adjustment = sum(item.qty_difference for item in recon_items)
            logger.info(
                "📊 Expected Adjustment - Total Quantity Change: %s units",
                total_qty_adjustment
            )

            return recon

        except Exception as e:
            self.s.rollback()
            logger.error("❌ Failed to create Stock Reconciliation: %s", str(e), exc_info=True)
            raise BizValidationError(f"Failed to create stock reconciliation: {str(e)}")

    def submit_stock_reconciliation(self, *, recon_id: int, context: AffiliationContext) -> StockReconciliation:
        """
        Submit a Stock Reconciliation document.
        """
        from app.common.timezone.service import get_company_timezone
        import logging
        from datetime import datetime
        from decimal import Decimal

        try:
            logger.info("🔄 Stock Reconciliation submit: START recon_id=%s", recon_id)

            # ---- 1) READ PHASE (no locks) ---------------------------------------
            recon = self._get_validated_reconciliation(recon_id, context, for_update=False)
            logger.info("📋 Reconciliation document loaded: id=%s, code=%s, company=%s, branch=%s",
                        recon.id, recon.code, recon.company_id, recon.branch_id)

            # Validate posting date
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=recon.posting_date,
                company_id=recon.company_id,
            )

            # Validate state
            guard_submittable_state(recon.doc_status)

            # Validate items
            from app.business_validation import item_validation as V
            V.validate_list_not_empty(recon.items, "items for submission")
            logger.info("✅ Document validation passed")

            # Get company timezone
            company_tz = get_company_timezone(self.s, recon.company_id)
            logger.info("🌍 Using company timezone: %s", company_tz)

            # Prepare lines for stock engine
            lines_snap = [{
                "item_id": item.item_id,
                "warehouse_id": item.warehouse_id,
                "quantity": item.quantity,
                "valuation_rate": item.valuation_rate,
                "doc_row_id": item.id,
                "purpose": recon.purpose.value,
            } for item in recon.items]

            logger.info("📦 Processing %d reconciliation items", len(lines_snap))

            # Get document type
            doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
            logger.info("📄 Document type ID: %s", doc_type_id)

            # ---- FIX: resolve_posting_dt correctly ----
            posting_date_dt = (recon.posting_date if isinstance(recon.posting_date, datetime)
                               else datetime.combine(recon.posting_date, datetime.min.time()))
            posting_dt = resolve_posting_dt(
                posting_date_dt,
                created_at=recon.created_at,
                tz=company_tz,
                treat_midnight_as_date=True,
            )
            logger.info("📅 Posting datetime resolved: %s", posting_dt)

            # Build reconciliation intents
            intents = build_intents_for_reconciliation(
                company_id=recon.company_id,
                branch_id=recon.branch_id,
                posting_dt=posting_dt,
                doc_type_id=doc_type_id,
                doc_id=recon.id,
                lines=lines_snap,
                session=self.s,
            )

            if not intents:
                raise BizValidationError("No stock intents were generated from lines.")

            pairs: set[tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}
            logger.info("📊 Stock intents generated: intents=%s, item/warehouse pairs=%s", len(intents), len(pairs))

            # Backdating check
            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
                    StockLedgerEntry.company_id == recon.company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                            (StockLedgerEntry.posting_date > posting_dt.date()) |
                            and_(
                                StockLedgerEntry.posting_date == posting_dt.date(),
                                StockLedgerEntry.posting_time > posting_dt,
                            )
                    ),
                    StockLedgerEntry.is_cancelled == False,
                )
                return (q.scalar() or 0) > 0

            is_backdated = any(_has_future_sle(i, w) for i, w in pairs)
            logger.info("⏰ Backdated check: %s", is_backdated)

            # Calculate total difference
            total_difference = sum(i.stock_value_difference for i in intents)
            logger.info("💰 Total value difference: %.2f", total_difference)

            # ---- 2) ATOMIC WRITE PHASE (SAVEPOINT) ------------------------------
            with self.s.begin_nested():
                recon_locked = self._get_validated_reconciliation(recon_id, context, for_update=True)
                guard_submittable_state(recon_locked.doc_status)

                # Ensure difference account
                if not recon_locked.difference_account_id:
                    default_account_id = self._get_difference_account_id(recon_locked.purpose, None)
                    if default_account_id:
                        recon_locked.difference_account_id = default_account_id
                        logger.info("🔄 Set default difference_account_id: %s", default_account_id)
                    else:
                        raise BizValidationError("Difference account is required for stock reconciliation.")

                # Append SLEs
                sle_written = 0
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        sle = append_sle(
                            self.s,
                            intent,
                            created_at_hint=recon_locked.created_at,
                            tz_hint=company_tz,
                            batch_index=idx,
                        )
                        sle_written += 1
                        logger.info("📝 SLE appended | item=%s, warehouse=%s, qty=%s",
                                    intent.item_id, intent.warehouse_id, intent.actual_qty)

                if sle_written != len(intents):
                    raise RuntimeError(f"SLE append mismatch (expected {len(intents)}, wrote {sle_written}).")
                logger.info("✅ All SLEs written: %s", sle_written)

                # 🚨 CRITICAL FIX: Exclude reconciliation documents from backdated replay
                if is_backdated:
                    recon_doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
                    logger.info("🔄 Starting backdated replay (excluding reconciliation documents)")

                    for item_id, wh_id in pairs:
                        from app.application_stock.engine.replay import repost_from
                        repost_from(
                            s=self.s,
                            company_id=recon_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types={recon_doc_type_id}  # 🎯 Exclude reconciliation docs
                        )
                logger.info("✅ Backdated replay completed")

                # Derive BINs
                bins_updated = 0
                for item_id, wh_id in pairs:
                    derive_bin(self.s, recon_locked.company_id, item_id, wh_id)
                    bins_updated += 1
                logger.info("✅ BINs derived: %s", bins_updated)

                # GL Posting
                ctx = PostingContext(
                    company_id=recon_locked.company_id,
                    branch_id=recon_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=recon_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"Stock Reconciliation {recon_locked.code}",
                    template_code="STOCK_RECON_GENERAL",
                    payload={"STOCK_RECON_DIFFERENCE": abs(total_difference)},
                    dynamic_account_context={"difference_account_id": recon_locked.difference_account_id},
                )
                PostingService(self.s).post(ctx)
                logger.info("✅ GL posting completed successfully")

                # Update document status
                recon_locked.doc_status = DocStatusEnum.SUBMITTED
                self.repo.save(recon_locked)
                logger.info("📈 Document status updated to SUBMITTED")

            # Commit outer transaction
            self.s.commit()
            logger.info("🎉 Stock Reconciliation submit: SUCCESS | recon_id=%s code=%s",
                        recon.id, recon.code)

            return recon_locked

        except Exception as e:
            logger.exception("❌ Stock Reconciliation submit: FAILED | recon_id=%s, error=%s", recon_id, str(e))
            self.s.rollback()
            raise
    #
    #
    # def submit_stock_reconciliation(self, *, recon_id: int, context: AffiliationContext) -> StockReconciliation:
    #     """
    #     Submit a Stock Reconciliation document.
    #     """
    #     from app.common.timezone.service import get_company_timezone
    #     import logging
    #
    #     try:
    #         # ---- 1) READ PHASE (no locks) ---------------------------------------
    #         logger.info("🔄 Stock Reconciliation submit: START recon_id=%s", recon_id)
    #
    #         recon = self._get_validated_reconciliation(recon_id, context, for_update=False)
    #         logger.info("📋 Reconciliation document loaded: id=%s, code=%s, company=%s, branch=%s",
    #                     recon.id, recon.code, recon.company_id, recon.branch_id)
    #
    #         # Validate posting date
    #         PostingDateValidator.validate_standalone_document(
    #             s=self.s,
    #             posting_date=recon.posting_date,
    #             company_id=recon.company_id,
    #         )
    #
    #         # Validate state
    #         guard_submittable_state(recon.doc_status)
    #
    #         # Validate items
    #         from app.business_validation import item_validation as V
    #         V.validate_list_not_empty(recon.items, "items for submission")
    #         logger.info("✅ Document validation passed")
    #
    #         # Get company timezone
    #         company_tz = get_company_timezone(self.s, recon.company_id)
    #         logger.info("🌍 Using company timezone: %s", company_tz)
    #
    #         # Prepare lines for stock engine
    #         lines_snap = [{
    #             "item_id": item.item_id,
    #             "warehouse_id": item.warehouse_id,
    #             "quantity": item.quantity,
    #             "valuation_rate": item.valuation_rate,
    #             "doc_row_id": item.id,
    #             "purpose": recon.purpose.value,
    #         } for item in recon.items]
    #
    #         logger.info("📦 Processing %d reconciliation items", len(lines_snap))
    #
    #         # Get document type
    #         doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
    #         logger.info("📄 Document type ID: %s", doc_type_id)
    #
    #         # Resolve posting datetime
    #         posting_dt = resolve_posting_dt(
    #             recon.posting_date.date() if hasattr(recon.posting_date, "date") else recon.posting_date,
    #             created_at=recon.created_at,
    #             tz=company_tz,
    #             treat_midnight_as_date=True,
    #         )
    #
    #         logger.info("📅 Posting datetime: %s", posting_dt)
    #
    #         # Build reconciliation intents (Frappe style)
    #         intents = build_intents_for_reconciliation(
    #             company_id=recon.company_id,
    #             branch_id=recon.branch_id,
    #             posting_dt=posting_dt,
    #             doc_type_id=doc_type_id,
    #             doc_id=recon.id,
    #             lines=lines_snap,
    #             session=self.s,
    #         )
    #
    #         if not intents:
    #             raise BizValidationError("No stock intents were generated from lines.")
    #
    #         pairs: Set[Tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}
    #         logger.info(
    #             "📊 Stock intents generated: intents=%s, item/warehouse pairs=%s",
    #             len(intents), len(pairs)
    #         )
    #
    #         # Backdating check
    #         def _has_future_sle(item_id: int, wh_id: int) -> bool:
    #             q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
    #                 StockLedgerEntry.company_id == recon.company_id,
    #                 StockLedgerEntry.item_id == item_id,
    #                 StockLedgerEntry.warehouse_id == wh_id,
    #                 (
    #                         (StockLedgerEntry.posting_date > posting_dt.date()) |
    #                         and_(
    #                             StockLedgerEntry.posting_date == posting_dt.date(),
    #                             StockLedgerEntry.posting_time > posting_dt,
    #                         )
    #                 ),
    #                 StockLedgerEntry.is_cancelled == False,
    #             )
    #             return (q.scalar() or 0) > 0
    #
    #         is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
    #         logger.info("⏰ Backdated check: %s", is_backdated)
    #
    #         # Calculate total difference for accounting
    #         total_difference = Decimal('0')
    #         for intent in intents:
    #             total_difference += intent.stock_value_difference
    #
    #         logger.info(
    #             "💰 Total value difference: %.2f",
    #             total_difference
    #         )
    #
    #         # ---- 2) ATOMIC WRITE PHASE (SAVEPOINT) ------------------------------
    #         with self.s.begin_nested():
    #             recon_locked = self._get_validated_reconciliation(recon_id, context, for_update=True)
    #             guard_submittable_state(recon_locked.doc_status)
    #
    #             # 🔍 CRITICAL: Check difference_account_id before GL posting
    #             logger.info("🔍 Checking difference_account_id: %s", recon_locked.difference_account_id)
    #
    #             if not recon_locked.difference_account_id:
    #                 logger.error("❌ difference_account_id is None or empty!")
    #                 # Try to get default account based on purpose
    #                 default_account_id = self._get_difference_account_id(recon_locked.purpose, None)
    #                 if default_account_id:
    #                     recon_locked.difference_account_id = default_account_id
    #                     logger.info("🔄 Set default difference_account_id: %s", default_account_id)
    #                 else:
    #                     raise BizValidationError("Difference account is required for stock reconciliation.")
    #
    #             logger.info("✅ difference_account_id is valid: %s", recon_locked.difference_account_id)
    #
    #             # Write SLEs under advisory locks
    #             sle_written = 0
    #             with lock_pairs(self.s, pairs):
    #                 for idx, intent in enumerate(intents):
    #                     sle = append_sle(
    #                         self.s,
    #                         intent,
    #                         created_at_hint=recon_locked.created_at,
    #                         tz_hint=company_tz,
    #                         batch_index=idx,
    #                     )
    #                     sle_written += 1
    #                     logger.info(
    #                         "📝 SLE appended | sle_id=%s, item=%s, warehouse=%s, qty=%s",
    #                         sle.id, intent.item_id, intent.warehouse_id, intent.actual_qty
    #                     )
    #
    #             if sle_written != len(intents):
    #                 raise RuntimeError(f"SLE append mismatch (expected {len(intents)}, wrote {sle_written}).")
    #
    #             logger.info("✅ All SLEs written: %s", sle_written)
    #
    #             # Backdated replay
    #             if is_backdated:
    #                 for item_id, wh_id in pairs:
    #                     logger.info("🔄 Starting replay for item=%s, wh=%s", item_id, wh_id)
    #                     repost_from(
    #                         s=self.s,
    #                         company_id=recon_locked.company_id,
    #                         item_id=item_id,
    #                         warehouse_id=wh_id,
    #                         start_dt=posting_dt,
    #                         exclude_doc_types=set()
    #                     )
    #                 logger.info("✅ Backdated replay completed")
    #
    #             # Derive BINs
    #             bins_updated = 0
    #             for item_id, wh_id in pairs:
    #                 logger.info("📊 Deriving bin for item=%s, wh=%s", item_id, wh_id)
    #                 bin_obj = derive_bin(self.s, recon_locked.company_id, item_id, wh_id)
    #                 bins_updated += 1
    #
    #             logger.info("✅ BINs derived: %s", bins_updated)
    #
    #             # GL posting - Use SINGLE template (Frappe style)
    #             from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
    #
    #             # 🔍 VERIFY account ID before creating context
    #             account_id_to_use = recon_locked.difference_account_id
    #             logger.info("🔍 Final account ID for GL: %s", account_id_to_use)
    #
    #             if not account_id_to_use:
    #                 raise BizValidationError("Cannot proceed with GL posting - difference_account_id is not set")
    #
    #             # ✅ FIXED: Use dynamic_account_context instead of runtime_accounts
    #             ctx = PostingContext(
    #                 company_id=recon_locked.company_id,
    #                 branch_id=recon_locked.branch_id,
    #                 source_doctype_id=doc_type_id,
    #                 source_doc_id=recon_locked.id,
    #                 posting_date=posting_dt,
    #                 created_by_id=context.user_id,
    #                 is_auto_generated=True,
    #                 entry_type=None,
    #                 remarks=f"Stock Reconciliation {recon_locked.code}",
    #                 template_code="STOCK_RECON_GENERAL",
    #                 payload={
    #                     "STOCK_RECON_DIFFERENCE": abs(total_difference),
    #                 },
    #                 # ✅ FIX: Use dynamic_account_context to match posting_service.py
    #                 dynamic_account_context={
    #                     "difference_account_id": account_id_to_use
    #                 },
    #                 party_id=None,
    #                 party_type=None,
    #             )
    #
    #             logger.info("📤 Starting GL posting with template: STOCK_RECON_GENERAL")
    #             logger.info("📊 GL context - difference_account_id: %s, total_difference: %s",
    #                         account_id_to_use, total_difference)
    #
    #             # 🔍 DEBUG: Check what's in dynamic_account_context
    #             logger.info("🔍 Dynamic account context content: %s", ctx.dynamic_account_context)
    #
    #             PostingService(self.s).post(ctx)
    #             logger.info("✅ GL posting completed successfully")
    #
    #             # Update document status
    #             recon_locked.doc_status = DocStatusEnum.SUBMITTED
    #             self.repo.save(recon_locked)
    #             logger.info("📈 Document status updated to SUBMITTED")
    #
    #         # ---- 3) COMMIT OUTER TX ---------------------------------------------
    #         self.s.commit()
    #
    #         logger.info(
    #             "🎉 Stock Reconciliation submit: SUCCESS | recon_id=%s code=%s",
    #             recon.id, recon.code
    #         )
    #         return recon
    #
    #     except Exception as e:
    #         logger.exception("❌ Stock Reconciliation submit: FAILED | recon_id=%s, error=%s", recon_id, str(e))
    #         self.s.rollback()
    #         raise
    def cancel_stock_reconciliation(self, *, recon_id: int, context: AffiliationContext) -> StockReconciliation:
        """
        Cancel a Stock Reconciliation document.
        Reverses both stock and accounting entries.
        """
        # Implementation similar to purchase receipt cancel
        # Would include:
        # 1. Read phase validation
        # 2. Write phase with reversal SLEs
        # 3. Accounting reversal
        # 4. Status update to CANCELLED

        # This follows the same pattern as PurchaseReceiptService.cancel_purchase_receipt
        # but adapted for stock reconciliation
        pass