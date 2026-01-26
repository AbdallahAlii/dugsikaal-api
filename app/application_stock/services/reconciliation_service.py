# # app/application_stock/services/reconciliation_service.py
# from __future__ import annotations
#
# import logging
# from datetime import datetime, date
# from decimal import Decimal
# from typing import Optional, List, Dict, Set, Tuple
#
# from sqlalchemy.orm import Session
# from sqlalchemy import func, and_, select
# from werkzeug.exceptions import HTTPException
# from decimal import Decimal as Dec
# from app.application_reports.hook.invalidation import invalidate_all_core_reports_for_company, \
#     invalidate_financial_reports_for_company
# from app.application_stock.engine.sle_helpers import create_reconciliation_intent
# from app.application_stock.repo.reconciliation_repo import StockReconciliationRepository
# from app.application_stock.stock_models import (
#     StockReconciliation,
#     StockReconciliationItem,
#     StockReconciliationPurpose,
#     DocumentType,
#     StockLedgerEntry,
#     DocStatusEnum,
# )
# from app.application_stock.engine.posting_clock import resolve_posting_dt
# from app.application_stock.engine.handlers.reconciliation import build_intents_for_reconciliation
# from app.application_stock.engine.locks import lock_pairs
# from app.application_stock.engine.replay import repost_from
# from app.application_stock.engine.sle_writer import append_sle, _last_sle_before_dt
# from app.application_stock.engine.bin_derive import derive_bin
#
# from app.application_accounting.engine.posting_service import PostingService, PostingContext
# from app.business_validation.posting_date_validation import PostingDateValidator
# from app.business_validation.item_validation import (
#     BizValidationError,
#     DocumentStateError,
#     guard_draft_only,
#     guard_submittable_state,
#     guard_cancellable_state,
# )
#
# from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
# from app.security.rbac_effective import AffiliationContext
# from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope
#
# from config.database import db
#
# logger = logging.getLogger(__name__)
#
#
# class StockReconciliationService:
#     """Service layer for managing Stock Reconciliation with strict workflow."""
#     PREFIX = "SRE"
#
#     def __init__(self, session: Optional[Session] = None):
#         self.s: Session = session or db.session
#         self.repo = StockReconciliationRepository(self.s)
#
#     # ---- Internal Helpers ----------------------------------------------------
#
#     def _get_validated_reconciliation(
#         self, recon_id: int, context: AffiliationContext, for_update: bool = False
#     ) -> StockReconciliation:
#         recon = self.repo.get_by_id(recon_id, for_update=for_update)
#         if not recon:
#             raise BizValidationError("Stock Reconciliation not found.")
#         ensure_scope_by_ids(
#             context=context,
#             target_company_id=recon.company_id,
#             target_branch_id=recon.branch_id,
#         )
#         return recon
#
#     def _generate_or_validate_code(
#         self, company_id: int, branch_id: int, manual_code: Optional[str]
#     ) -> str:
#         if manual_code:
#             code = manual_code.strip()
#             if self.repo.code_exists(company_id, branch_id, code):
#                 raise BizValidationError("Document code already exists in this branch.")
#             ensure_manual_code_is_next_and_bump(
#                 prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code
#             )
#             return code
#         return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)
#
#     def _validate_header(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> None:
#         """Batch validate header-level master data."""
#         valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, branch_id, warehouse_ids)
#         if len(valid_warehouses) != len(set(warehouse_ids)):
#             raise BizValidationError("One or more warehouses are invalid or not transactional.")
#
#     def _validate_and_normalize_lines(
#         self,
#         company_id: int,
#         branch_id: int,
#         lines: List[Dict],
#     ) -> List[Dict]:
#         """
#         Validate item/warehouse master data and quantities/rates.
#         Returns a clean list for further processing.
#         Keeps `id` (for updates) and optional `doc_row_id`.
#
#         NOTE:
#         - For Stock Reconciliation we allow quantity = 0 (lost / stolen / damaged),
#           we only disallow NEGATIVE quantities here.
#         """
#         from app.business_validation import item_validation as V
#
#         V.validate_list_not_empty(lines, "items")
#         V.validate_unique_items(lines, key="item_id")
#
#         item_ids = [ln["item_id"] for ln in lines]
#         warehouse_ids = [ln["warehouse_id"] for ln in lines]
#
#         # Item master validations
#         item_details = self.repo.get_item_details_batch(company_id, item_ids)
#         working_lines: List[Dict] = [
#             {**ln, **item_details.get(ln["item_id"], {})} for ln in lines
#         ]
#
#         V.validate_items_are_active(
#             [(ln["item_id"], ln.get("is_active", False)) for ln in working_lines]
#         )
#         V.validate_no_service_items(working_lines)
#
#         # Here is the important change: allow 0, forbid < 0
#         for ln in working_lines:
#             qty = Decimal(str(ln["quantity"]))
#             if qty < 0:
#                 raise BizValidationError(
#                     "Quantity cannot be negative for stock reconciliation."
#                 )
#             ln["quantity"] = qty
#
#             V.validate_non_negative_rate(ln.get("valuation_rate"))
#
#         normalized_lines: List[Dict] = []
#         for ln in working_lines:
#             clean_line = {
#                 "item_id": ln["item_id"],
#                 "warehouse_id": ln["warehouse_id"],
#                 "quantity": ln["quantity"],          # now a Decimal >= 0
#                 "valuation_rate": ln.get("valuation_rate"),
#             }
#             if "id" in ln:
#                 clean_line["id"] = ln["id"]
#             if "doc_row_id" in ln:
#                 clean_line["doc_row_id"] = ln["doc_row_id"]
#
#             normalized_lines.append(clean_line)
#
#         return normalized_lines
#
#
#     def _get_doc_type_id_or_400(self, code: str) -> int:
#         dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
#         if not dt:
#             raise BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
#         return dt
#
#
#     def _get_difference_account_id(
#         self,
#         purpose: StockReconciliationPurpose,
#         difference_account_id: Optional[int],
#     ) -> Optional[int]:
#         """
#         Resolve default difference account by NAME (not code), so it stays
#         stable even if you change account codes between companies.
#
#         - OPENING_STOCK        -> "Temporary Opening"   (asset, code 1172 in your seed)
#         - STOCK_RECONCILIATION -> "Stock Adjustments"   (expense, code 5015 in your seed)
#         """
#         if difference_account_id:
#             return difference_account_id
#
#         try:
#             from app.application_accounting.chart_of_accounts.models import Account
#
#             if purpose == StockReconciliationPurpose.OPENING_STOCK:
#                 target_name = "Temporary Opening"
#             else:
#                 target_name = "Stock Adjustments"
#
#             account_id = (
#                 self.s.execute(
#                     select(Account.id).where(
#                         Account.name == target_name,
#                         getattr(Account, "is_group", False) == False,  # safe even if no is_group
#                     )
#                 )
#                 .scalar_one_or_none()
#             )
#
#             logger.info(
#                 "🔍 Default difference account for %s resolved by name '%s' -> %s",
#                 getattr(purpose, "value", purpose),
#                 target_name,
#                 account_id,
#             )
#             return account_id
#
#         except Exception as e:
#             logger.error("❌ Error getting default difference account: %s", str(e))
#             return None
#
#
#     # -------------------------------------------------------------------------
#     # CREATE
#     # -------------------------------------------------------------------------
#     # -------------------------------------------------------------------------
#     # CREATE
#     # -------------------------------------------------------------------------
#     def create_stock_reconciliation(
#         self,
#         *,
#         payload: dict,
#         context: AffiliationContext,
#     ) -> StockReconciliation:
#         """
#         Create a Stock Reconciliation (Draft), ERPNext-style.
#         - Valid for bulk (1000+ lines) via Data Import.
#         - Uses Bin fast-path for current stock.
#         - Only stores quantity difference; value difference is computed at submit.
#
#         Business rules:
#         - purpose = OPENING_STOCK:
#             * All lines must have counted quantity > 0
#             * Current stock at posting_date MUST be zero for each item+warehouse
#               (otherwise use purpose = STOCK_RECONCILIATION)
#         - purpose = STOCK_RECONCILIATION:
#             * Counted quantity >= 0 (0 allowed for loss/damage/write-off)
#         """
#         try:
#             logger.info("🔄 Creating Stock Reconciliation")
#
#             # 1) Resolve company/branch and RBAC scope
#             company_id, branch_id = resolve_company_branch_and_scope(
#                 context=context,
#                 payload_company_id=payload.get("company_id"),
#                 branch_id=payload.get("branch_id") or getattr(context, "branch_id", None),
#                 get_branch_company_id=self.repo.get_branch_company_id,
#                 require_branch=True,
#             )
#
#             # 2) Normalize & validate posting datetime (same pattern as Sales Invoice)
#             norm_dt = PostingDateValidator.validate_standalone_document(
#                 self.s,
#                 payload["posting_date"],
#                 company_id,
#                 created_at=None,
#                 treat_midnight_as_date=True,
#             )
#             posting_dt = norm_dt
#
#             # 3) Purpose (we need it early for validation)
#             purpose = StockReconciliationPurpose(
#                 payload.get("purpose", StockReconciliationPurpose.STOCK_RECONCILIATION.value)
#             )
#
#             # 4) Header & line validation
#             warehouse_ids = list({ln["warehouse_id"] for ln in payload["items"]})
#             self._validate_header(company_id, branch_id, warehouse_ids)
#
#             normalized_lines = self._validate_and_normalize_lines(
#                 company_id,
#                 branch_id,
#                 payload["items"],
#             )
#             logger.info("✅ Validated %d items", len(normalized_lines))
#
#             # 5) Get current stock state for all item/warehouse pairs (bulk)
#             item_warehouse_pairs = [
#                 (ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines
#             ]
#             current_states = self.repo.get_current_stock_state_for_items(
#                 company_id, posting_dt, item_warehouse_pairs
#             )
#
#             # 6) Calculate quantity differences (value handled at submit),
#             #    and apply purpose-specific validation.
#             calculated_lines: List[Dict] = []
#             for line in normalized_lines:
#                 pair = (line["item_id"], line["warehouse_id"])
#                 state = current_states.get(
#                     pair,
#                     {
#                         "current_qty": Decimal("0"),
#                         "current_valuation_rate": Decimal("0"),
#                     },
#                 )
#
#                 counted_qty = Decimal(str(line["quantity"]))
#                 current_qty = state["current_qty"]
#                 current_rate = state["current_valuation_rate"]
#                 valuation_rate_used = line.get("valuation_rate") or current_rate
#
#                 qty_difference = counted_qty - current_qty
#
#                 # ----- Purpose-specific rules -----
#                 if purpose == StockReconciliationPurpose.OPENING_STOCK:
#                     # 1) Opening Stock must actually introduce stock (no 0 lines)
#                     if counted_qty <= 0:
#                         raise BizValidationError(
#                             "Opening Stock lines must have counted quantity greater than 0. "
#                             "Use purpose 'Stock Reconciliation' for loss/write-off."
#                         )
#                     # 2) Existing stock must be zero
#                     if current_qty != 0:
#                         raise BizValidationError(
#                             "Opening Stock can only be used when current stock is zero for an item "
#                             f"(item_id={line['item_id']}, warehouse_id={line['warehouse_id']}). "
#                             "Use purpose 'Stock Reconciliation' to adjust existing stock."
#                         )
#                 # For STOCK_RECONCILIATION: counted_qty >= 0 already enforced; nothing extra.
#
#                 calculated_lines.append(
#                     {
#                         **line,
#                         "current_qty": current_qty,
#                         "current_valuation_rate": current_rate,
#                         "qty_difference": qty_difference,
#                         "valuation_rate_used": valuation_rate_used,
#                     }
#                 )
#
#             logger.info(
#                 "✅ Calculated quantity differences for %d lines", len(calculated_lines)
#             )
#
#             # 7) Code
#             code = self._generate_or_validate_code(
#                 company_id=company_id,
#                 branch_id=branch_id,
#                 manual_code=payload.get("code"),
#             )
#
#             # 8) Build item rows
#             recon_items: List[StockReconciliationItem] = []
#             for line in calculated_lines:
#                 item_data = {
#                     "item_id": line["item_id"],
#                     "warehouse_id": line["warehouse_id"],
#                     "quantity": line["quantity"],  # physical count (can be 0 for STOCK_RECONCILIATION)
#                     "valuation_rate": line.get("valuation_rate"),
#                     "current_qty": line["current_qty"],
#                     "current_valuation_rate": line["current_valuation_rate"],
#                     "qty_difference": line["qty_difference"],
#                     # amount_difference is filled at submit (from intents)
#                 }
#                 if hasattr(StockReconciliationItem, "doc_row_id") and "doc_row_id" in line:
#                     item_data["doc_row_id"] = line["doc_row_id"]
#
#                 recon_items.append(StockReconciliationItem(**item_data))
#
#             # 9) Difference account (depends on purpose)
#             difference_account_id = self._get_difference_account_id(
#                 purpose,
#                 payload.get("difference_account_id"),
#             )
#
#             # 10) Create document
#             recon = StockReconciliation(
#                 company_id=company_id,
#                 branch_id=branch_id,
#                 created_by_id=context.user_id,
#                 purpose=purpose,
#                 difference_account_id=difference_account_id,
#                 code=code,
#                 posting_date=posting_dt,
#                 doc_status=DocStatusEnum.DRAFT,
#                 notes=payload.get("notes"),
#                 items=recon_items,
#             )
#
#             self.repo.save(recon)
#             self.s.commit()
#
#             logger.info(
#                 "✅ Created Stock Reconciliation %s (ID: %s) with %d items",
#                 recon.code,
#                 recon.id,
#                 len(recon_items),
#             )
#             return recon
#
#         except BizValidationError as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ Validation error creating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise
#         except HTTPException as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ HTTP error creating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise
#         except Exception as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ Unexpected error creating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise BizValidationError(
#                 "Unexpected error while creating stock reconciliation."
#             )
#
#
#     # -------------------------------------------------------------------------
#     # UPDATE (Draft only – used by Data Import bulk edit)
#     # -------------------------------------------------------------------------
#     def update_stock_reconciliation(
#         self,
#         *,
#         recon_id: int,
#         payload: dict,
#         context: AffiliationContext,
#     ) -> StockReconciliation:
#         """
#         Update a Draft Stock Reconciliation (header + lines).
#         Used by Data Import and manual edits.
#
#         Business rules (same as create):
#         - purpose = OPENING_STOCK:
#             * All lines must have counted quantity > 0
#             * Current stock at posting_date MUST be zero for each item+warehouse
#         - purpose = STOCK_RECONCILIATION:
#             * Counted quantity >= 0 (0 allowed)
#         """
#         try:
#             logger.info("🔄 Updating Stock Reconciliation id=%s", recon_id)
#
#             recon = self._get_validated_reconciliation(
#                 recon_id, context, for_update=True
#             )
#             guard_draft_only(recon.doc_status)
#
#             # Posting date (optional)
#             if "posting_date" in payload and payload["posting_date"] is not None:
#                 new_pd = payload["posting_date"]
#
#                 posting_norm = PostingDateValidator.validate_standalone_document(
#                     self.s,
#                     new_pd,
#                     recon.company_id,
#                     created_at=recon.created_at,
#                     treat_midnight_as_date=True,
#                 )
#                 recon.posting_date = posting_norm
#                 posting_dt = posting_norm
#             else:
#                 posting_dt = recon.posting_date
#
#             # Purpose / difference account
#             if "purpose" in payload and payload["purpose"] is not None:
#                 recon.purpose = StockReconciliationPurpose(payload["purpose"])
#
#             if "difference_account_id" in payload:
#                 recon.difference_account_id = payload["difference_account_id"]
#
#             if recon.difference_account_id is None:
#                 recon.difference_account_id = self._get_difference_account_id(
#                     recon.purpose, None
#                 )
#
#             if "notes" in payload:
#                 recon.notes = payload["notes"]
#
#             effective_purpose = recon.purpose
#
#             # Lines (optional)
#             if "items" in payload and payload["items"] is not None:
#                 warehouse_ids = list({ln["warehouse_id"] for ln in payload["items"]})
#                 self._validate_header(
#                     recon.company_id, recon.branch_id, warehouse_ids
#                 )
#
#                 normalized_lines = self._validate_and_normalize_lines(
#                     recon.company_id,
#                     recon.branch_id,
#                     payload["items"],
#                 )
#
#                 item_warehouse_pairs = [
#                     (ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines
#                 ]
#                 current_states = self.repo.get_current_stock_state_for_items(
#                     recon.company_id, posting_dt, item_warehouse_pairs
#                 )
#
#                 lines_for_sync: List[Dict] = []
#                 for ln in normalized_lines:
#                     pair = (ln["item_id"], ln["warehouse_id"])
#                     state = current_states.get(
#                         pair,
#                         {
#                             "current_qty": Decimal("0"),
#                             "current_valuation_rate": Decimal("0"),
#                         },
#                     )
#
#                     counted_qty = Decimal(str(ln["quantity"]))
#                     current_qty = state["current_qty"]
#                     current_rate = state["current_valuation_rate"]
#                     qty_difference = counted_qty - current_qty
#
#                     # ----- Purpose-specific rules -----
#                     if effective_purpose == StockReconciliationPurpose.OPENING_STOCK:
#                         if counted_qty <= 0:
#                             raise BizValidationError(
#                                 "Opening Stock lines must have counted quantity greater than 0. "
#                                 "Use purpose 'Stock Reconciliation' for loss/write-off."
#                             )
#                         if current_qty != 0:
#                             raise BizValidationError(
#                                 "Opening Stock can only be used when current stock is zero for an item "
#                                 f"(item_id={ln['item_id']}, warehouse_id={ln['warehouse_id']}). "
#                                 "Use purpose 'Stock Reconciliation' to adjust existing stock."
#                             )
#                     # STOCK_RECONCILIATION: counted_qty >= 0 already enforced
#
#                     sync_line = {
#                         "id": ln.get("id"),
#                         "item_id": ln["item_id"],
#                         "warehouse_id": ln["warehouse_id"],
#                         "quantity": ln["quantity"],           # can be 0 for STOCK_RECONCILIATION
#                         "valuation_rate": ln.get("valuation_rate"),
#                         "current_qty": current_qty,
#                         "current_valuation_rate": current_rate,
#                         "qty_difference": qty_difference,
#                     }
#                     if "doc_row_id" in ln:
#                         sync_line["doc_row_id"] = ln["doc_row_id"]
#
#                     lines_for_sync.append(sync_line)
#
#                 self.repo.sync_lines(recon, lines_for_sync)
#
#             self.repo.save(recon)
#             self.s.commit()
#
#             logger.info("✅ Updated Stock Reconciliation id=%s", recon.id)
#             return recon
#
#         except BizValidationError as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ Validation error updating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise
#         except HTTPException as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ HTTP error updating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise
#         except Exception as e:
#             self.s.rollback()
#             logger.error(
#                 "❌ Unexpected error updating Stock Reconciliation: %s",
#                 str(e),
#                 exc_info=True,
#             )
#             raise BizValidationError(
#                 "Unexpected error while updating stock reconciliation."
#             )
#
#
#
#     # -------------------------------------------------------------------------
#     # SUBMIT
#     # -------------------------------------------------------------------------
#     def submit_stock_reconciliation(
#         self,
#         *,
#         recon_id: int,
#         context: AffiliationContext,
#     ) -> StockReconciliation:
#         """
#         Submit a Stock Reconciliation.
#         - Writes SLEs via reconciliation intents
#         - Replays for backdated docs
#         - Updates Bins
#         - Posts GL entry using STOCK_RECON_GENERAL with a **signed** difference
#         """
#         from app.common.timezone.service import get_company_timezone
#         from decimal import Decimal as Dec
#
#         try:
#             logger.info("🔄 Stock Reconciliation submit: START recon_id=%s", recon_id)
#
#             # 1) Read phase (no locks)
#             recon = self._get_validated_reconciliation(recon_id, context, for_update=False)
#
#             # Validate posting date again
#             PostingDateValidator.validate_standalone_document(
#                 self.s,
#                 recon.posting_date,
#                 recon.company_id,
#                 created_at=recon.created_at,
#                 treat_midnight_as_date=True,
#             )
#             guard_submittable_state(recon.doc_status)
#
#             from app.business_validation import item_validation as V
#             V.validate_list_not_empty(recon.items, "items for submission")
#
#             company_tz = get_company_timezone(self.s, recon.company_id)
#
#             lines_snap = [
#                 {
#                     "item_id": item.item_id,
#                     "warehouse_id": item.warehouse_id,
#                     "quantity": item.quantity,
#                     "valuation_rate": item.valuation_rate,
#                     "doc_row_id": item.id,
#                     "purpose": recon.purpose.value,
#                 }
#                 for item in recon.items
#             ]
#
#             doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
#
#             posting_date_dt = (
#                 recon.posting_date
#                 if isinstance(recon.posting_date, datetime)
#                 else datetime.combine(recon.posting_date, datetime.min.time())
#             )
#             posting_dt = resolve_posting_dt(
#                 posting_date_dt,
#                 created_at=recon.created_at,
#                 tz=company_tz,
#                 treat_midnight_as_date=True,
#             )
#
#             intents = build_intents_for_reconciliation(
#                 company_id=recon.company_id,
#                 branch_id=recon.branch_id,
#                 posting_dt=posting_dt,
#                 doc_type_id=doc_type_id,
#                 doc_id=recon.id,
#                 lines=lines_snap,
#                 session=self.s,
#             )
#             if not intents:
#                 raise BizValidationError("No stock intents were generated from lines.")
#
#             pairs: Set[Tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}
#
#             def _has_future_sle(item_id: int, wh_id: int) -> bool:
#                 q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
#                     StockLedgerEntry.company_id == recon.company_id,
#                     StockLedgerEntry.item_id == item_id,
#                     StockLedgerEntry.warehouse_id == wh_id,
#                     (
#                         (StockLedgerEntry.posting_date > posting_dt.date())
#                         | and_(
#                             StockLedgerEntry.posting_date == posting_dt.date(),
#                             StockLedgerEntry.posting_time > posting_dt,
#                         )
#                     ),
#                     StockLedgerEntry.is_cancelled == False,
#                 )
#                 return (q.scalar() or 0) > 0
#
#             is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
#
#             total_difference = sum(
#                 (i.stock_value_difference or Dec("0")) for i in intents
#             )
#             logger.info(
#                 "📊 Stock Reconciliation total stock_value_difference (GL payload): %s",
#                 total_difference,
#             )
#
#             # 2) Atomic write phase
#             with self.s.begin_nested():
#                 recon_locked = self._get_validated_reconciliation(
#                     recon_id, context, for_update=True
#                 )
#                 guard_submittable_state(recon_locked.doc_status)
#
#                 if not recon_locked.difference_account_id:
#                     default_account_id = self._get_difference_account_id(
#                         recon_locked.purpose, None
#                     )
#                     if default_account_id:
#                         recon_locked.difference_account_id = default_account_id
#                     else:
#                         raise BizValidationError(
#                             "Difference account is required for stock reconciliation."
#                         )
#
#                 sle_written = 0
#                 with lock_pairs(self.s, pairs):
#                     for idx, intent in enumerate(intents):
#                         append_sle(
#                             self.s,
#                             intent,
#                             created_at_hint=recon_locked.created_at,
#                             tz_hint=company_tz,
#                             batch_index=idx,
#                         )
#                         sle_written += 1
#
#                 if sle_written != len(intents):
#                     raise RuntimeError(
#                         f"SLE append mismatch (expected {len(intents)}, wrote {sle_written})."
#                     )
#
#                 if is_backdated:
#                     recon_doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
#                     for item_id, wh_id in pairs:
#                         repost_from(
#                             s=self.s,
#                             company_id=recon_locked.company_id,
#                             item_id=item_id,
#                             warehouse_id=wh_id,
#                             start_dt=posting_dt,
#                             exclude_doc_types={recon_doc_type_id},
#                         )
#
#                 for item_id, wh_id in pairs:
#                     derive_bin(self.s, recon_locked.company_id, item_id, wh_id)
#
#                 ctx = PostingContext(
#                     company_id=recon_locked.company_id,
#                     branch_id=recon_locked.branch_id,
#                     source_doctype_id=doc_type_id,
#                     source_doc_id=recon_locked.id,
#                     posting_date=posting_dt,
#                     created_by_id=context.user_id,
#                     is_auto_generated=True,
#                     entry_type=None,
#                     remarks=f"Stock Reconciliation {recon_locked.code}",
#                     template_code="STOCK_RECON_GENERAL",
#                     payload={"STOCK_RECON_DIFFERENCE": total_difference},
#                     dynamic_account_context={
#                         "difference_account_id": recon_locked.difference_account_id
#                     },
#                 )
#                 PostingService(self.s).post(ctx)
#
#                 recon_locked.doc_status = DocStatusEnum.SUBMITTED
#                 self.repo.save(recon_locked)
#
#             self.s.commit()
#             logger.info(
#                 "🎉 Stock Reconciliation submit: SUCCESS | recon_id=%s code=%s",
#                 recon_locked.id,
#                 recon_locked.code,
#             )
#             return recon_locked
#
#         except Exception as e:
#             logger.exception(
#                 "❌ Stock Reconciliation submit: FAILED | recon_id=%s, error=%s",
#                 recon_id,
#                 str(e),
#             )
#             self.s.rollback()
#             raise
#
#
#
#     # -------------------------------------------------------------------------
#     # CANCEL
#     # -------------------------------------------------------------------------
#
#     def cancel_stock_reconciliation(
#             self,
#             *,
#             recon_id: int,
#             context: AffiliationContext,
#     ) -> StockReconciliation:
#         """
#         Cancel a submitted Stock Reconciliation.
#
#         STOCK:
#         - Marks its SLEs as cancelled and replays stock from earliest SLE time.
#         - Re-derives bins.
#
#         GL:
#         - If the submit created an auto Journal Entry, call PostingService.cancel(...)
#           to create a clean reversal JE (swap DR/CR) — ERP-style.
#         """
#         from app.common.timezone.service import get_company_timezone  # if not imported globally
#
#         try:
#             logger.info("🔄 Stock Reconciliation cancel: START recon_id=%s", recon_id)
#
#             # 1) Read + basic guards
#             recon = self._get_validated_reconciliation(
#                 recon_id, context, for_update=False
#             )
#             PostingDateValidator.validate_standalone_document(
#                 self.s,
#                 recon.posting_date,
#                 recon.company_id,
#                 created_at=recon.created_at,
#                 treat_midnight_as_date=True,
#             )
#             guard_cancellable_state(recon.doc_status)
#
#             doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
#             company_tz = get_company_timezone(self.s, recon.company_id)
#
#             # 2) Existing, non-cancelled SLEs for this reconciliation
#             sle_rows: List[StockLedgerEntry] = (
#                 self.s.query(StockLedgerEntry)
#                 .filter(
#                     StockLedgerEntry.company_id == recon.company_id,
#                     StockLedgerEntry.doc_type_id == doc_type_id,
#                     StockLedgerEntry.doc_id == recon.id,
#                     StockLedgerEntry.is_cancelled == False,
#                 )
#                 .all()
#             )
#             if not sle_rows:
#                 raise BizValidationError(
#                     "No stock ledger entries found for this reconciliation; cannot cancel."
#                 )
#
#             pairs: Set[Tuple[int, int]] = {
#                 (sle.item_id, sle.warehouse_id) for sle in sle_rows
#             }
#             original_total_diff = sum(
#                 (sle.stock_value_difference or Dec("0")) for sle in sle_rows
#             )
#
#             earliest_dt = min(sle.posting_time for sle in sle_rows)
#
#             posting_date_dt = (
#                 recon.posting_date
#                 if isinstance(recon.posting_date, datetime)
#                 else datetime.combine(recon.posting_date, datetime.min.time())
#             )
#             posting_dt = resolve_posting_dt(
#                 posting_date_dt,
#                 created_at=recon.created_at,
#                 tz=company_tz,
#                 treat_midnight_as_date=True,
#             )
#
#             # 3) Atomic work
#             with self.s.begin_nested():
#                 recon_locked = self._get_validated_reconciliation(
#                     recon_id, context, for_update=True
#                 )
#                 guard_cancellable_state(recon_locked.doc_status)
#
#                 # 3.a Mark SLEs as cancelled
#                 for sle in sle_rows:
#                     sle.is_cancelled = True
#
#                 # 3.b Replay stock from earliest SLE time
#                 for item_id, wh_id in pairs:
#                     repost_from(
#                         s=self.s,
#                         company_id=recon_locked.company_id,
#                         item_id=item_id,
#                         warehouse_id=wh_id,
#                         start_dt=earliest_dt,
#                         exclude_doc_types=set(),
#                     )
#
#                 # 3.c Re-derive bins
#                 for item_id, wh_id in pairs:
#                     derive_bin(self.s, recon_locked.company_id, item_id, wh_id)
#
#                 # 3.d Reverse GL if submit actually posted any net difference
#                 if original_total_diff != Dec("0"):
#                     ctx_cancel = PostingContext(
#                         company_id=recon_locked.company_id,
#                         branch_id=recon_locked.branch_id,
#                         source_doctype_id=doc_type_id,
#                         source_doc_id=recon_locked.id,
#                         posting_date=posting_dt,  # required by dataclass, not used in cancel()
#                         created_by_id=context.user_id,
#                         is_auto_generated=True,
#                         remarks=f"Cancel Stock Reconciliation {recon_locked.code}",
#                     )
#                     PostingService(self.s).cancel(ctx_cancel)
#
#                 # 3.e Mark doc as CANCELLED
#                 recon_locked.doc_status = DocStatusEnum.CANCELLED
#                 self.repo.save(recon_locked)
#
#             self.s.commit()
#
#             # 4) Invalidate reports: stock + financial
#             invalidate_all_core_reports_for_company(
#                 recon.company_id, include_stock=True
#             )
#             invalidate_financial_reports_for_company(recon.company_id)
#
#             logger.info(
#                 "🎉 Stock Reconciliation cancel: SUCCESS | recon_id=%s code=%s",
#                 recon_locked.id,
#                 recon_locked.code,
#             )
#             return recon_locked
#
#         except Exception as e:
#             logger.exception(
#                 "❌ Stock Reconciliation cancel: FAILED | recon_id=%s, error=%s",
#                 recon_id,
#                 str(e),
#             )
#             self.s.rollback()
#             raise
# app/application_stock/services/reconciliation_service.py
from __future__ import annotations

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Set, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, select
from werkzeug.exceptions import HTTPException
from decimal import Decimal as Dec

from app.application_reports.hook.invalidation import (
    invalidate_all_core_reports_for_company,
    invalidate_financial_reports_for_company,
)
from app.application_stock.engine.sle_helpers import create_reconciliation_intent
from app.application_stock.repo.reconciliation_repo import StockReconciliationRepository
from app.application_stock.stock_models import (
    StockReconciliation,
    StockReconciliationItem,
    StockReconciliationPurpose,
    DocumentType,
    StockLedgerEntry,
    DocStatusEnum,
)
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.handlers.reconciliation import (
    build_intents_for_reconciliation,
)
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.sle_writer import append_sle, _last_sle_before_dt
from app.application_stock.engine.bin_derive import derive_bin

from app.application_accounting.engine.posting_service import (
    PostingService,
    PostingContext,
)
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation.item_validation import (
    BizValidationError,
    DocumentStateError,
    guard_draft_only,
    guard_submittable_state,
    guard_cancellable_state,
)

from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

from config.database import db

logger = logging.getLogger(__name__)


class StockReconciliationService:
    """
    Service layer for managing Stock Reconciliation with strict workflow.

    Transaction strategy (ERP-style):

    - For normal HTTP endpoints / CLI:
        service = StockReconciliationService()          # auto_commit=True
      The service owns the transaction and will commit/rollback.

    - For Data Import / batch pipelines:
        service = StockReconciliationService(auto_commit=False)
      The caller (pipeline) owns the transaction (and often uses
      Session.begin / begin_nested). In this mode the service:
        * never calls commit()/rollback()
        * only flushes so PKs are available.
    """

    PREFIX = "SRE"

    def __init__(
        self,
        session: Optional[Session] = None,
        *,
        auto_commit: bool = True,
    ):
        self.s: Session = session or db.session
        self.repo = StockReconciliationRepository(self.s)
        self.auto_commit = auto_commit

    # -------------------------------------------------------------------------
    # Transaction helpers
    # -------------------------------------------------------------------------
    def _flush_or_commit(self) -> None:
        """
        - auto_commit=True  -> commit() at service boundary
        - auto_commit=False -> only flush(), let caller manage commit/rollback
        """
        if self.auto_commit:
            self.s.commit()
        else:
            self.s.flush()

    def _rollback_if_needed(self) -> None:
        """
        Rollback only if this service owns the transaction.
        For Data Import (auto_commit=False), outer pipeline handles rollback.
        """
        if self.auto_commit:
            self.s.rollback()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _get_validated_reconciliation(
        self, recon_id: int, context: AffiliationContext, for_update: bool = False
    ) -> StockReconciliation:
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
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code
            )
            return code
        return generate_next_code(
            prefix=self.PREFIX, company_id=company_id, branch_id=branch_id
        )

    def _validate_header(
        self, company_id: int, branch_id: int, warehouse_ids: List[int]
    ) -> None:
        """Batch validate header-level master data."""
        valid_warehouses = self.repo.get_transactional_warehouse_ids(
            company_id, branch_id, warehouse_ids
        )
        if len(valid_warehouses) != len(set(warehouse_ids)):
            raise BizValidationError(
                "One or more warehouses are invalid or not transactional."
            )

    def _validate_and_normalize_lines(
        self,
        company_id: int,
        branch_id: int,
        lines: List[Dict],
    ) -> List[Dict]:
        """
        Validate item/warehouse master data and quantities/rates.
        Returns a clean list for further processing.
        Keeps `id` (for updates) and optional `doc_row_id`.

        NOTE:
        - For Stock Reconciliation we allow quantity = 0 (lost / stolen / damaged),
          we only disallow NEGATIVE quantities here.
        """
        from app.business_validation import item_validation as V

        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        warehouse_ids = [ln["warehouse_id"] for ln in lines]

        # Item master validations
        item_details = self.repo.get_item_details_batch(company_id, item_ids)
        working_lines: List[Dict] = [
            {**ln, **item_details.get(ln["item_id"], {})} for ln in lines
        ]

        V.validate_items_are_active(
            [(ln["item_id"], ln.get("is_active", False)) for ln in working_lines]
        )
        V.validate_no_service_items(working_lines)

        # Allow 0, forbid < 0
        normalized_lines: List[Dict] = []
        for ln in working_lines:
            qty = Decimal(str(ln["quantity"]))
            if qty < 0:
                raise BizValidationError(
                    "Quantity cannot be negative for stock reconciliation."
                )
            ln["quantity"] = qty

            V.validate_non_negative_rate(ln.get("valuation_rate"))

            clean_line = {
                "item_id": ln["item_id"],
                "warehouse_id": ln["warehouse_id"],
                "quantity": ln["quantity"],  # now a Decimal >= 0
                "valuation_rate": ln.get("valuation_rate"),
            }
            if "id" in ln:
                clean_line["id"] = ln["id"]
            if "doc_row_id" in ln:
                clean_line["doc_row_id"] = ln["doc_row_id"]

            normalized_lines.append(clean_line)

        return normalized_lines

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = (
            self.s.execute(select(DocumentType.id).where(DocumentType.code == code))
            .scalar_one_or_none()
        )
        if not dt:
            raise BizValidationError(
                f"DocumentType '{code}' not found. Seed the Document Types table."
            )
        return dt

    def _get_difference_account_id(
        self,
        purpose: StockReconciliationPurpose,
        difference_account_id: Optional[int],
    ) -> Optional[int]:
        """
        Resolve default difference account by NAME (not code), so it stays
        stable even if you change account codes between companies.

        - OPENING_STOCK        -> "Temporary Opening"   (asset, code 1172 in your seed)
        - STOCK_RECONCILIATION -> "Stock Adjustments"   (expense, code 5015 in your seed)
        """
        if difference_account_id:
            return difference_account_id

        try:
            from app.application_accounting.chart_of_accounts.models import Account

            if purpose == StockReconciliationPurpose.OPENING_STOCK:
                target_name = "Temporary Opening"
            else:
                target_name = "Stock Adjustments"

            account_id = (
                self.s.execute(
                    select(Account.id).where(
                        Account.name == target_name,
                        getattr(Account, "is_group", False) == False,
                    )
                )
                .scalar_one_or_none()
            )

            logger.info(
                "🔍 Default difference account for %s resolved by name '%s' -> %s",
                getattr(purpose, "value", purpose),
                target_name,
                account_id,
            )
            return account_id

        except Exception as e:
            logger.error("❌ Error getting default difference account: %s", str(e))
            return None

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------
    def create_stock_reconciliation(
        self,
        *,
        payload: dict,
        context: AffiliationContext,
    ) -> StockReconciliation:
        """
        Create a Stock Reconciliation (Draft), ERPNext-style.

        - Supports bulk (1000+ lines) via Data Import.
        - Uses current stock state at posting_date.
        - Stores qty_difference per line; value difference is computed at submit.

        Business rules:
        - purpose = OPENING_STOCK:
            * All lines must have counted quantity > 0
            * Current stock at posting_date MUST be zero for each item+warehouse
        - purpose = STOCK_RECONCILIATION:
            * Counted quantity >= 0 (0 allowed for loss/damage/write-off)
        """
        try:
            logger.info("🔄 Creating Stock Reconciliation")

            # 1) Resolve company/branch and RBAC scope
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.get("company_id"),
                branch_id=payload.get("branch_id") or getattr(context, "branch_id", None),
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )

            # 2) Normalize & validate posting datetime
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s,
                payload["posting_date"],
                company_id,
                created_at=None,
                treat_midnight_as_date=True,
            )
            posting_dt = norm_dt

            # 3) Purpose
            purpose = StockReconciliationPurpose(
                payload.get(
                    "purpose",
                    StockReconciliationPurpose.STOCK_RECONCILIATION.value,
                )
            )

            # 4) Header & line validation
            if not payload.get("items"):
                raise BizValidationError("At least one item line is required.")

            warehouse_ids = list({ln["warehouse_id"] for ln in payload["items"]})
            self._validate_header(company_id, branch_id, warehouse_ids)

            normalized_lines = self._validate_and_normalize_lines(
                company_id,
                branch_id,
                payload["items"],
            )
            logger.info("✅ Validated %d items", len(normalized_lines))

            # 5) Current stock state (bulk)
            item_warehouse_pairs = [
                (ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines
            ]
            current_states = self.repo.get_current_stock_state_for_items(
                company_id, posting_dt, item_warehouse_pairs
            )

            # 6) Calculate differences + purpose-specific rules
            calculated_lines: List[Dict] = []
            for line in normalized_lines:
                pair = (line["item_id"], line["warehouse_id"])
                state = current_states.get(
                    pair,
                    {
                        "current_qty": Decimal("0"),
                        "current_valuation_rate": Decimal("0"),
                    },
                )

                counted_qty = Decimal(str(line["quantity"]))
                current_qty = state["current_qty"]
                current_rate = state["current_valuation_rate"]
                valuation_rate_used = line.get("valuation_rate") or current_rate

                qty_difference = counted_qty - current_qty

                if purpose == StockReconciliationPurpose.OPENING_STOCK:
                    if counted_qty <= 0:
                        raise BizValidationError(
                            "Opening Stock lines must have counted quantity greater than 0. "
                            "Use purpose 'Stock Reconciliation' for loss/write-off."
                        )
                    if current_qty != 0:
                        raise BizValidationError(
                            "Opening Stock can only be used when current stock is zero for an item "
                            f"(item_id={line['item_id']}, warehouse_id={line['warehouse_id']}). "
                            "Use purpose 'Stock Reconciliation' to adjust existing stock."
                        )

                calculated_lines.append(
                    {
                        **line,
                        "current_qty": current_qty,
                        "current_valuation_rate": current_rate,
                        "qty_difference": qty_difference,
                        "valuation_rate_used": valuation_rate_used,
                    }
                )

            logger.info(
                "✅ Calculated quantity differences for %d lines", len(calculated_lines)
            )

            # 7) Generate or validate document code
            code = self._generate_or_validate_code(
                company_id=company_id,
                branch_id=branch_id,
                manual_code=payload.get("code"),
            )

            # 8) Build item rows
            recon_items: List[StockReconciliationItem] = []
            for line in calculated_lines:
                item_data = {
                    "item_id": line["item_id"],
                    "warehouse_id": line["warehouse_id"],
                    "quantity": line["quantity"],
                    "valuation_rate": line.get("valuation_rate"),
                    "current_qty": line["current_qty"],
                    "current_valuation_rate": line["current_valuation_rate"],
                    "qty_difference": line["qty_difference"],
                }
                if hasattr(StockReconciliationItem, "doc_row_id") and "doc_row_id" in line:
                    item_data["doc_row_id"] = line["doc_row_id"]

                recon_items.append(StockReconciliationItem(**item_data))

            # 9) Difference account
            difference_account_id = self._get_difference_account_id(
                purpose,
                payload.get("difference_account_id"),
            )

            # 10) Create document
            recon = StockReconciliation(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                purpose=purpose,
                difference_account_id=difference_account_id,
                code=code,
                posting_date=posting_dt,
                doc_status=DocStatusEnum.DRAFT,
                notes=payload.get("notes"),
                items=recon_items,
            )

            self.repo.save(recon)

            # Flush so IDs are populated regardless of auto_commit mode
            self.s.flush()
            recon_id = recon.id
            recon_code = recon.code
            items_count = len(recon_items)

            # Let outer layer decide commit vs just flush
            self._flush_or_commit()

            logger.info(
                "✅ Created Stock Reconciliation %s (ID: %s) with %d items",
                recon_code,
                recon_id,
                items_count,
            )
            return recon

        except BizValidationError as e:
            self._rollback_if_needed()
            logger.error(
                "❌ Validation error creating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise
        except HTTPException as e:
            self._rollback_if_needed()
            logger.error(
                "❌ HTTP error creating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise
        except Exception as e:
            self._rollback_if_needed()
            logger.error(
                "❌ Unexpected error creating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise BizValidationError(
                "Unexpected error while creating stock reconciliation."
            )

    # -------------------------------------------------------------------------
    # UPDATE (Draft only – used by Data Import bulk edit)
    # -------------------------------------------------------------------------
    def update_stock_reconciliation(
        self,
        *,
        recon_id: int,
        payload: dict,
        context: AffiliationContext,
    ) -> StockReconciliation:
        """
        Update a Draft Stock Reconciliation (header + lines).
        Used by Data Import and manual edits.
        """
        try:
            logger.info("🔄 Updating Stock Reconciliation id=%s", recon_id)

            recon = self._get_validated_reconciliation(
                recon_id, context, for_update=True
            )
            guard_draft_only(recon.doc_status)

            # Posting date (optional)
            if "posting_date" in payload and payload["posting_date"] is not None:
                new_pd = payload["posting_date"]

                posting_norm = PostingDateValidator.validate_standalone_document(
                    self.s,
                    new_pd,
                    recon.company_id,
                    created_at=recon.created_at,
                    treat_midnight_as_date=True,
                )
                recon.posting_date = posting_norm
                posting_dt = posting_norm
            else:
                posting_dt = recon.posting_date

            # Purpose / difference account
            if "purpose" in payload and payload["purpose"] is not None:
                recon.purpose = StockReconciliationPurpose(payload["purpose"])

            if "difference_account_id" in payload:
                recon.difference_account_id = payload["difference_account_id"]

            if recon.difference_account_id is None:
                recon.difference_account_id = self._get_difference_account_id(
                    recon.purpose, None
                )

            if "notes" in payload:
                recon.notes = payload["notes"]

            effective_purpose = recon.purpose

            # Lines (optional)
            if "items" in payload and payload["items"] is not None:
                from app.business_validation import item_validation as V

                V.validate_list_not_empty(payload["items"], "items")

                warehouse_ids = list({ln["warehouse_id"] for ln in payload["items"]})
                self._validate_header(
                    recon.company_id, recon.branch_id, warehouse_ids
                )

                normalized_lines = self._validate_and_normalize_lines(
                    recon.company_id,
                    recon.branch_id,
                    payload["items"],
                )

                item_warehouse_pairs = [
                    (ln["item_id"], ln["warehouse_id"]) for ln in normalized_lines
                ]
                current_states = self.repo.get_current_stock_state_for_items(
                    recon.company_id, posting_dt, item_warehouse_pairs
                )

                lines_for_sync: List[Dict] = []
                for ln in normalized_lines:
                    pair = (ln["item_id"], ln["warehouse_id"])
                    state = current_states.get(
                        pair,
                        {
                            "current_qty": Decimal("0"),
                            "current_valuation_rate": Decimal("0"),
                        },
                    )

                    counted_qty = Decimal(str(ln["quantity"]))
                    current_qty = state["current_qty"]
                    current_rate = state["current_valuation_rate"]
                    qty_difference = counted_qty - current_qty

                    if effective_purpose == StockReconciliationPurpose.OPENING_STOCK:
                        if counted_qty <= 0:
                            raise BizValidationError(
                                "Opening Stock lines must have counted quantity greater than 0. "
                                "Use purpose 'Stock Reconciliation' for loss/write-off."
                            )
                        if current_qty != 0:
                            raise BizValidationError(
                                "Opening Stock can only be used when current stock is zero for an item "
                                f"(item_id={ln['item_id']}, warehouse_id={ln['warehouse_id']}). "
                                "Use purpose 'Stock Reconciliation' to adjust existing stock."
                            )

                    sync_line = {
                        "id": ln.get("id"),
                        "item_id": ln["item_id"],
                        "warehouse_id": ln["warehouse_id"],
                        "quantity": ln["quantity"],
                        "valuation_rate": ln.get("valuation_rate"),
                        "current_qty": current_qty,
                        "current_valuation_rate": current_rate,
                        "qty_difference": qty_difference,
                    }
                    if "doc_row_id" in ln:
                        sync_line["doc_row_id"] = ln["doc_row_id"]

                    lines_for_sync.append(sync_line)

                self.repo.sync_lines(recon, lines_for_sync)

            self.repo.save(recon)
            self._flush_or_commit()

            logger.info("✅ Updated Stock Reconciliation id=%s", recon.id)
            return recon

        except BizValidationError as e:
            self._rollback_if_needed()
            logger.error(
                "❌ Validation error updating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise
        except HTTPException as e:
            self._rollback_if_needed()
            logger.error(
                "❌ HTTP error updating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise
        except Exception as e:
            self._rollback_if_needed()
            logger.error(
                "❌ Unexpected error updating Stock Reconciliation: %s",
                str(e),
                exc_info=True,
            )
            raise BizValidationError(
                "Unexpected error while updating stock reconciliation."
            )

    # -------------------------------------------------------------------------
    # SUBMIT
    # -------------------------------------------------------------------------
    def submit_stock_reconciliation(
        self,
        *,
        recon_id: int,
        context: AffiliationContext,
    ) -> StockReconciliation:
        """
        Submit a Stock Reconciliation.
        - Writes SLEs via reconciliation intents
        - Replays for backdated docs
        - Updates Bins
        - Posts GL entry using STOCK_RECON_GENERAL with a **signed** difference
        """
        from app.common.timezone.service import get_company_timezone

        try:
            logger.info("🔄 Stock Reconciliation submit: START recon_id=%s", recon_id)

            # 1) Read phase (no locks)
            recon = self._get_validated_reconciliation(
                recon_id, context, for_update=False
            )

            # Validate posting date again
            PostingDateValidator.validate_standalone_document(
                self.s,
                recon.posting_date,
                recon.company_id,
                created_at=recon.created_at,
                treat_midnight_as_date=True,
            )
            guard_submittable_state(recon.doc_status)

            from app.business_validation import item_validation as V

            V.validate_list_not_empty(recon.items, "items for submission")

            company_tz = get_company_timezone(self.s, recon.company_id)

            lines_snap = [
                {
                    "item_id": item.item_id,
                    "warehouse_id": item.warehouse_id,
                    "quantity": item.quantity,
                    "valuation_rate": item.valuation_rate,
                    "doc_row_id": item.id,
                    "purpose": recon.purpose.value,
                }
                for item in recon.items
            ]

            doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")

            posting_date_dt = (
                recon.posting_date
                if isinstance(recon.posting_date, datetime)
                else datetime.combine(recon.posting_date, datetime.min.time())
            )
            posting_dt = resolve_posting_dt(
                posting_date_dt,
                created_at=recon.created_at,
                tz=company_tz,
                treat_midnight_as_date=True,
            )

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

            pairs: Set[Tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}

            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
                    StockLedgerEntry.company_id == recon.company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                        (StockLedgerEntry.posting_date > posting_dt.date())
                        | and_(
                            StockLedgerEntry.posting_date == posting_dt.date(),
                            StockLedgerEntry.posting_time > posting_dt,
                        )
                    ),
                    StockLedgerEntry.is_cancelled == False,
                )
                return (q.scalar() or 0) > 0

            is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)

            total_difference = sum(
                (i.stock_value_difference or Dec("0")) for i in intents
            )
            logger.info(
                "📊 Stock Reconciliation total stock_value_difference (GL payload): %s",
                total_difference,
            )

            # 2) Atomic write phase (savepoint-friendly)
            with self.s.begin_nested():
                recon_locked = self._get_validated_reconciliation(
                    recon_id, context, for_update=True
                )
                guard_submittable_state(recon_locked.doc_status)

                if not recon_locked.difference_account_id:
                    default_account_id = self._get_difference_account_id(
                        recon_locked.purpose, None
                    )
                    if default_account_id:
                        recon_locked.difference_account_id = default_account_id
                    else:
                        raise BizValidationError(
                            "Difference account is required for stock reconciliation."
                        )

                sle_written = 0
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(
                            self.s,
                            intent,
                            created_at_hint=recon_locked.created_at,
                            tz_hint=company_tz,
                            batch_index=idx,
                        )
                        sle_written += 1

                if sle_written != len(intents):
                    raise RuntimeError(
                        f"SLE append mismatch (expected {len(intents)}, wrote {sle_written})."
                    )

                if is_backdated:
                    recon_doc_type_id = self._get_doc_type_id_or_400(
                        "STOCK_RECONCILIATION"
                    )
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=recon_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types={recon_doc_type_id},
                        )

                for item_id, wh_id in pairs:
                    derive_bin(self.s, recon_locked.company_id, item_id, wh_id)

                ctx_post = PostingContext(
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
                    payload={"STOCK_RECON_DIFFERENCE": total_difference},
                    dynamic_account_context={
                        "difference_account_id": recon_locked.difference_account_id
                    },
                )
                PostingService(self.s).post(ctx_post)

                recon_locked.doc_status = DocStatusEnum.SUBMITTED
                self.repo.save(recon_locked)

            # Let outer transaction decide final commit vs rollback
            self._flush_or_commit()

            logger.info(
                "🎉 Stock Reconciliation submit: SUCCESS | recon_id=%s code=%s",
                recon_locked.id,
                recon_locked.code,
            )
            return recon_locked

        except Exception as e:
            logger.exception(
                "❌ Stock Reconciliation submit: FAILED | recon_id=%s, error=%s",
                recon_id,
                str(e),
            )
            self._rollback_if_needed()
            raise

    # -------------------------------------------------------------------------
    # CANCEL
    # -------------------------------------------------------------------------
    def cancel_stock_reconciliation(
        self,
        *,
        recon_id: int,
        context: AffiliationContext,
    ) -> StockReconciliation:
        """
        Cancel a submitted Stock Reconciliation.

        STOCK:
        - Marks its SLEs as cancelled and replays stock from earliest SLE time.
        - Re-derives bins.

        GL:
        - If the submit created an auto Journal Entry, call PostingService.cancel(...)
          to create a clean reversal JE (swap DR/CR).
        """
        from app.common.timezone.service import get_company_timezone

        try:
            logger.info("🔄 Stock Reconciliation cancel: START recon_id=%s", recon_id)

            # 1) Read + basic guards
            recon = self._get_validated_reconciliation(
                recon_id, context, for_update=False
            )
            PostingDateValidator.validate_standalone_document(
                self.s,
                recon.posting_date,
                recon.company_id,
                created_at=recon.created_at,
                treat_midnight_as_date=True,
            )
            guard_cancellable_state(recon.doc_status)

            doc_type_id = self._get_doc_type_id_or_400("STOCK_RECONCILIATION")
            company_tz = get_company_timezone(self.s, recon.company_id)

            # 2) Existing, non-cancelled SLEs for this reconciliation
            sle_rows: List[StockLedgerEntry] = (
                self.s.query(StockLedgerEntry)
                .filter(
                    StockLedgerEntry.company_id == recon.company_id,
                    StockLedgerEntry.doc_type_id == doc_type_id,
                    StockLedgerEntry.doc_id == recon.id,
                    StockLedgerEntry.is_cancelled == False,
                )
                .all()
            )
            if not sle_rows:
                raise BizValidationError(
                    "No stock ledger entries found for this reconciliation; cannot cancel."
                )

            pairs: Set[Tuple[int, int]] = {
                (sle.item_id, sle.warehouse_id) for sle in sle_rows
            }
            original_total_diff = sum(
                (sle.stock_value_difference or Dec("0")) for sle in sle_rows
            )

            earliest_dt = min(sle.posting_time for sle in sle_rows)

            posting_date_dt = (
                recon.posting_date
                if isinstance(recon.posting_date, datetime)
                else datetime.combine(recon.posting_date, datetime.min.time())
            )
            posting_dt = resolve_posting_dt(
                posting_date_dt,
                created_at=recon.created_at,
                tz=company_tz,
                treat_midnight_as_date=True,
            )

            # 3) Atomic work
            with self.s.begin_nested():
                recon_locked = self._get_validated_reconciliation(
                    recon_id, context, for_update=True
                )
                guard_cancellable_state(recon_locked.doc_status)

                # 3.a Mark SLEs as cancelled
                for sle in sle_rows:
                    sle.is_cancelled = True

                # 3.b Replay stock from earliest SLE time
                for item_id, wh_id in pairs:
                    repost_from(
                        s=self.s,
                        company_id=recon_locked.company_id,
                        item_id=item_id,
                        warehouse_id=wh_id,
                        start_dt=earliest_dt,
                        exclude_doc_types=set(),
                    )

                # 3.c Re-derive bins
                for item_id, wh_id in pairs:
                    derive_bin(self.s, recon_locked.company_id, item_id, wh_id)

                # 3.d Reverse GL if submit actually posted any net difference
                if original_total_diff != Dec("0"):
                    ctx_cancel = PostingContext(
                        company_id=recon_locked.company_id,
                        branch_id=recon_locked.branch_id,
                        source_doctype_id=doc_type_id,
                        source_doc_id=recon_locked.id,
                        posting_date=posting_dt,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        remarks=f"Cancel Stock Reconciliation {recon_locked.code}",
                    )
                    PostingService(self.s).cancel(ctx_cancel)

                # 3.e Mark doc as CANCELLED
                recon_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(recon_locked)

            self._flush_or_commit()

            # 4) Invalidate reports: stock + financial
            invalidate_all_core_reports_for_company(
                recon.company_id, include_stock=True
            )
            invalidate_financial_reports_for_company(recon.company_id)

            logger.info(
                "🎉 Stock Reconciliation cancel: SUCCESS | recon_id=%s code=%s",
                recon_locked.id,
                recon_locked.code,
            )
            return recon_locked

        except Exception as e:
            logger.exception(
                "❌ Stock Reconciliation cancel: FAILED | recon_id=%s, error=%s",
                recon_id,
                str(e),
            )
            self._rollback_if_needed()
            raise
