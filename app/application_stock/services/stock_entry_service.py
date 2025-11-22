# app/application_stock/services/stock_entry_service.py

from __future__ import annotations

import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any, Set, Tuple
from decimal import Decimal as Dec
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from config.database import db
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_stock.repo.stock_entry_repo import StockEntryRepository
from app.application_stock.stock_models import (
    StockEntry,
    StockEntryItem,
    StockEntryType,
    StockLedgerEntry,
    DocStatusEnum,
)
from app.application_stock.engine.handlers.stock_entry import (
    build_intents_for_stock_entry,
)
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.sle_writer import append_sle
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.locks import lock_pairs

from app.common.timezone.service import get_company_timezone
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation import item_validation as V
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

from app.application_reports.hook.invalidation import (
    invalidate_financial_reports_for_company,
    invalidate_all_core_reports_for_company,
)

logger = logging.getLogger(__name__)


class StockEntryService:
    SE_PREFIX = "SE"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = StockEntryRepository(self.s)

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _get_doc_type_id_or_400(self, code: str) -> int:
        # repo method is get_doc_type_id_by_code
        dt = self.repo.get_doc_type_id_by_code(code)
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt

    def _detect_backdated(
        self,
        company_id: int,
        pairs: Set[Tuple[int, int]],
        posting_dt: datetime,
    ) -> bool:
        """
        Detect if posting_dt is before any existing SLE for (company,item,warehouse).
        Same pattern as SalesService / Stock Reconciliation.
        """

        def _has_future_sle(item_id: int, wh_id: int) -> bool:
            q = (
                self.s.execute(
                    select(func.count())
                    .select_from(StockLedgerEntry)
                    .where(
                        StockLedgerEntry.company_id == company_id,
                        StockLedgerEntry.item_id == item_id,
                        StockLedgerEntry.warehouse_id == wh_id,
                        (
                            (StockLedgerEntry.posting_date > posting_dt.date())
                            | and_(
                                StockLedgerEntry.posting_date == posting_dt.date(),
                                StockLedgerEntry.posting_time > posting_dt,
                            )
                        ),
                        StockLedgerEntry.is_cancelled == False,  # noqa: E712
                    )
                ).scalar()
                or 0
            )
            return q > 0

        return any(_has_future_sle(i, w) for (i, w) in pairs)

    def _generate_or_validate_code(
        self,
        *,
        prefix: str,
        company_id: int,
        branch_id: int,
        manual: Optional[str],
    ) -> str:
        from app.common.generate_code.service import (
            generate_next_code,
            ensure_manual_code_is_next_and_bump,
        )

        if manual:
            code = manual.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise V.BizValidationError("Stock Entry code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=prefix,
                company_id=company_id,
                branch_id=branch_id,
                code=code,
            )
            return code
        return generate_next_code(prefix=prefix, company_id=company_id, branch_id=branch_id)

    def _entry_type_label(self, entry_type: StockEntryType) -> str:
        """
        Convert enum to the human label your validators expect,
        e.g. "Material Receipt", "Material Issue", "Material Transfer".
        """
        return getattr(entry_type, "value", str(entry_type))

    def _get_difference_account_id(
        self,
        *,
        company_id: int,
        entry_type: StockEntryType,
        explicit_id: Optional[int],
    ) -> Optional[int]:
        """
        Resolve Difference Account for Stock Entry (ERP-style).

        - If explicit_id is provided, that wins.
        - For Material Transfer, usually no net change in stock value -> no diff account.
        - For Material Receipt / Issue, fall back to a company-level default
          (e.g. "Stock Adjustments" expense) via repo.
        """
        if explicit_id:
            return int(explicit_id)

        # Pure transfers normally have no GL impact (value does not change)
        if entry_type == StockEntryType.MATERIAL_TRANSFER:
            return None

        acc_id = self.repo.get_default_difference_account_id(company_id, entry_type)
        if not acc_id:
            raise V.BizValidationError(
                "Difference Account is required but no default is configured "
                "for this company and entry type."
            )
        return int(acc_id)

    # ----------------------------------------------------------------------
    # CREATE
    # ----------------------------------------------------------------------

    def create_stock_entry(
        self, *, payload: "StockEntryCreate", context: AffiliationContext
    ) -> StockEntry:
        """
        Uses StockEntryCreate schema:

        class StockEntryCreate(BaseModel):
            company_id: Optional[int]
            branch_id: Optional[int]
            posting_date: date
            stock_entry_type: StockEntryType
            code: Optional[str]
            difference_account_id: Optional[int]
            items: List[StockEntryItemCreate]
        """

        # 1) Resolve company/branch with scope checks
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        # 2) Normalize & validate posting datetime
        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s,
            payload.posting_date,
            company_id,
            created_at=None,
            treat_midnight_as_date=True,
        )

        # 3) Basic validations
        if not payload.items:
            raise V.BizValidationError("Stock Entry requires at least one item.")

        # Use schema field name: stock_entry_type
        entry_type = payload.stock_entry_type
        entry_type_str = self._entry_type_label(entry_type)

        # 4) Item activity + UOM compatibility
        item_ids = [ln.item_id for ln in payload.items]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        V.validate_items_are_active(
            [(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids]
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

        # 5) Per-line structural validation (warehouses, rate, qty)
        for idx, ln in enumerate(payload.items, start=1):
            qty_dec = Decimal(str(ln.quantity or 0))
            if qty_dec <= 0:
                raise V.BizValidationError(
                    f"Row {idx}: Quantity must be greater than zero."
                )

            V.validate_stock_entry_warehouses(
                entry_type=entry_type_str,
                row_idx=idx,
                source_warehouse_id=ln.source_warehouse_id,
                target_warehouse_id=ln.target_warehouse_id,
            )

            V.validate_stock_entry_rate(
                entry_type=entry_type_str,
                row_idx=idx,
                rate=Decimal(str(ln.rate or 0)),
            )

        # 6) Difference account (only needed when there will be value change)
        difference_account_id = self._get_difference_account_id(
            company_id=company_id,
            entry_type=entry_type,
            explicit_id=getattr(payload, "difference_account_id", None),
        )

        # 7) Generate code
        code = self._generate_or_validate_code(
            prefix=self.SE_PREFIX,
            company_id=company_id,
            branch_id=branch_id,
            manual=payload.code,
        )

        # 8) Build item rows
        se_items: List[StockEntryItem] = []
        for ln in payload.items:
            se_items.append(
                StockEntryItem(
                    item_id=ln.item_id,
                    quantity=Decimal(str(ln.quantity)),
                    rate=Decimal(str(ln.rate or 0)),
                    source_warehouse_id=ln.source_warehouse_id,
                    target_warehouse_id=ln.target_warehouse_id,
                    uom_id=ln.uom_id,
                )
            )

        # 9) Build & save header
        se = StockEntry(
            company_id=company_id,
            branch_id=branch_id,
            code=code,
            posting_date=norm_dt,
            stock_entry_type=entry_type,             # ✅ correct field name
            doc_status=DocStatusEnum.DRAFT,
            difference_account_id=difference_account_id,
            items=se_items,
        )
        self.repo.save(se)
        self.s.commit()
        return se

    # ----------------------------------------------------------------------
    # UPDATE
    # ----------------------------------------------------------------------

    def update_stock_entry(
        self, *, se_id: int, payload: "StockEntryUpdate", context: AffiliationContext
    ) -> StockEntry:
        """
        Only allowed in DRAFT.
        """
        se = self.repo.get_by_id(se_id, for_update=True)
        if not se:
            raise NotFound("Stock Entry not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=se.company_id,
            target_branch_id=se.branch_id,
        )
        V.guard_draft_only(se.doc_status)

        # Posting date
        if getattr(payload, "posting_date", None):
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s,
                payload.posting_date,
                se.company_id,
                created_at=se.created_at,
                treat_midnight_as_date=True,
            )
            se.posting_date = norm_dt

        # Entry type change (usually not allowed)
        if (
            hasattr(payload, "stock_entry_type")
            and payload.stock_entry_type is not None
            and payload.stock_entry_type != se.stock_entry_type
        ):
            raise V.BizValidationError("Cannot change Entry Type after creation.")

        # Effective entry_type for this update
        entry_type = getattr(payload, "stock_entry_type", None) or se.stock_entry_type
        entry_type_str = self._entry_type_label(entry_type)

        # Difference account update (allowed in draft)
        if (
            hasattr(payload, "difference_account_id")
            and payload.difference_account_id is not None
        ):
            se.difference_account_id = self._get_difference_account_id(
                company_id=se.company_id,
                entry_type=entry_type,
                explicit_id=payload.difference_account_id,
            )

        # Replace lines
        if payload.items is not None:
            item_ids = [ln.item_id for ln in payload.items]
            details = self.repo.get_item_details_batch(se.company_id, item_ids)
            V.validate_items_are_active(
                [(iid, details.get(iid, {}).get("is_active", False)) for iid in item_ids]
            )

            uom_pairs = [(ln.item_id, ln.uom_id) for ln in payload.items if ln.uom_id]
            if uom_pairs:
                compat = self.repo.get_compatible_uom_pairs(se.company_id, uom_pairs)
                for item_id, uom_id in uom_pairs:
                    if (
                        details.get(item_id, {}).get("is_stock_item", False)
                        and (item_id, uom_id) not in compat
                    ):
                        raise V.BizValidationError(
                            f"UOM not compatible for item_id={item_id}"
                        )

            # Per-line validations (qty, warehouses, rate)
            for idx, ln in enumerate(payload.items, start=1):
                qty_dec = Decimal(str(ln.quantity or 0))
                if qty_dec <= 0:
                    raise V.BizValidationError(
                        f"Row {idx}: Quantity must be greater than zero."
                    )

                V.validate_stock_entry_warehouses(
                    entry_type=entry_type_str,
                    row_idx=idx,
                    source_warehouse_id=ln.source_warehouse_id,
                    target_warehouse_id=ln.target_warehouse_id,
                )

                V.validate_stock_entry_rate(
                    entry_type=entry_type_str,
                    row_idx=idx,
                    rate=Decimal(str(ln.rate or 0)),
                )

            # Sync lines via repo
            lines: List[Dict[str, Any]] = []
            for ln in payload.items:
                lines.append(
                    dict(
                        id=ln.id,
                        item_id=ln.item_id,
                        quantity=ln.quantity,
                        rate=ln.rate,
                        source_warehouse_id=ln.source_warehouse_id,
                        target_warehouse_id=ln.target_warehouse_id,
                        uom_id=ln.uom_id,
                    )
                )
            self.repo.sync_lines(se, lines)

        self.repo.save(se)
        self.s.commit()
        return se

    # ----------------------------------------------------------------------
    # SUBMIT (with GL)
    # ----------------------------------------------------------------------

    # ----------------------------------------------------------------------
    # SUBMIT (with GL)
    # ----------------------------------------------------------------------
    # def submit_stock_entry(
    #     self, *, se_id: int, context: AffiliationContext
    # ) -> StockEntry:
    #     """
    #     Submit Stock Entry:
    #       - Build SLE intents (UOM aware).
    #       - Append SLEs with locking.
    #       - Repost if backdated.
    #       - Post GL using STOCK_ENTRY_GENERAL (if total difference != 0).
    #       - Mark as SUBMITTED.
    #       - Invalidate reports (stock + financial).
    #     """
    #     from decimal import Decimal as Dec
    #
    #     # 1) Read without locks
    #     se = self.repo.get_by_id(se_id, for_update=False)
    #     if not se:
    #         raise NotFound("Stock Entry not found.")
    #     ensure_scope_by_ids(
    #         context=context,
    #         target_company_id=se.company_id,
    #         target_branch_id=se.branch_id,
    #     )
    #     V.guard_submittable_state(se.doc_status)
    #
    #     if not se.items:
    #         raise V.BizValidationError("No items to submit.")
    #
    #     tz = get_company_timezone(self.s, se.company_id)
    #     posting_dt = resolve_posting_dt(
    #         se.posting_date.date(),
    #         created_at=se.created_at,
    #         tz=tz,
    #         treat_midnight_as_date=True,
    #     )
    #     dt_id = self._get_doc_type_id_or_400("STOCK_ENTRY")
    #
    #     # 2) Build intents from current items (no DB write yet)
    #     lines: List[Dict[str, Any]] = []
    #     for it in se.items:
    #         lines.append(
    #             {
    #                 "item_id": it.item_id,
    #                 "quantity": it.quantity,
    #                 "rate": it.rate,
    #                 "source_warehouse_id": it.source_warehouse_id,
    #                 "target_warehouse_id": it.target_warehouse_id,
    #                 "uom_id": it.uom_id,
    #                 "base_uom_id": None,  # handler will fetch if needed
    #                 "doc_row_id": it.id,
    #             }
    #         )
    #
    #     intents = build_intents_for_stock_entry(
    #         company_id=se.company_id,
    #         branch_id=se.branch_id,
    #         posting_dt=posting_dt,
    #         doc_type_id=dt_id,
    #         doc_id=se.id,
    #         entry_type=se.stock_entry_type,
    #         lines=lines,
    #         session=self.s,
    #     )
    #
    #     pairs = {(i.item_id, i.warehouse_id) for i in intents}
    #     is_backdated = self._detect_backdated(se.company_id, pairs, posting_dt)
    #
    #     # 3) Atomic write phase
    #     with self.s.begin_nested():
    #         se_locked = self.repo.get_by_id(se_id, for_update=True)
    #         V.guard_submittable_state(se_locked.doc_status)
    #
    #         # 3.a Write SLEs
    #         with lock_pairs(self.s, pairs):
    #             for idx, intent in enumerate(intents):
    #                 append_sle(
    #                     self.s,
    #                     intent,
    #                     created_at_hint=se_locked.created_at,
    #                     tz_hint=tz,
    #                     batch_index=idx,
    #                 )
    #
    #         # 3.b Repost if backdated
    #         if is_backdated:
    #             for item_id, wh_id in pairs:
    #                 repost_from(
    #                     s=self.s,
    #                     company_id=se_locked.company_id,
    #                     item_id=item_id,
    #                     warehouse_id=wh_id,
    #                     start_dt=posting_dt,
    #                     exclude_doc_types=set(),
    #                 )
    #
    #         # 3.c Re-derive bins
    #         for item_id, wh_id in pairs:
    #             derive_bin(self.s, se_locked.company_id, item_id, wh_id)
    #
    #         # 3.d NOW compute total stock value difference from SLE rows
    #         sle_rows: List[StockLedgerEntry] = (
    #             self.s.query(StockLedgerEntry)
    #             .filter(
    #                 StockLedgerEntry.company_id == se_locked.company_id,
    #                 StockLedgerEntry.doc_type_id == dt_id,
    #                 StockLedgerEntry.doc_id == se_locked.id,
    #                 StockLedgerEntry.is_cancelled == False,
    #             )
    #             .all()
    #         )
    #         total_difference = sum(
    #             (sle.stock_value_difference or Dec("0")) for sle in sle_rows
    #         )
    #
    #         # 3.e Post GL if there is any net difference
    #         if total_difference != Dec("0"):
    #             # Ensure difference account is set
    #             if not se_locked.difference_account_id:
    #                 se_locked.difference_account_id = self._get_difference_account_id(
    #                     company_id=se_locked.company_id,
    #                     entry_type=se_locked.stock_entry_type,
    #                     explicit_id=None,
    #                 )
    #
    #             ctx = PostingContext(
    #                 company_id=se_locked.company_id,
    #                 branch_id=se_locked.branch_id,
    #                 source_doctype_id=dt_id,
    #                 source_doc_id=se_locked.id,
    #                 posting_date=posting_dt,
    #                 created_by_id=context.user_id,
    #                 is_auto_generated=True,
    #                 entry_type=None,
    #                 remarks=f"Stock Entry {se_locked.code}",
    #                 template_code="STOCK_ENTRY_GENERAL",
    #                 payload={"STOCK_ENTRY_DIFFERENCE": total_difference},
    #                 dynamic_account_context={
    #                     "difference_account_id": se_locked.difference_account_id
    #                 },
    #             )
    #             PostingService(self.s).post(ctx)
    #
    #         # 3.f Mark submitted
    #         se_locked.doc_status = DocStatusEnum.SUBMITTED
    #         self.repo.save(se_locked)
    #
    #     self.s.commit()
    #
    #     # 4) Invalidate reports: stock + financial
    #     invalidate_all_core_reports_for_company(se.company_id, include_stock=True)
    #     invalidate_financial_reports_for_company(se.company_id)
    #
    #     return se


    # ----------------------------------------------------------------------
    # CANCEL (with reversing GL)
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # SUBMIT (with GL)
    # ----------------------------------------------------------------------
    def submit_stock_entry(
            self, *, se_id: int, context: AffiliationContext
    ) -> StockEntry:
        """
        Submit Stock Entry:
          - Build SLE intents (UOM aware).
          - Append SLEs with locking.
          - Repost if backdated.
          - Post GL using STOCK_ENTRY_GENERAL (if total difference != 0).
          - Mark as SUBMITTED.
          - Invalidate reports (stock + financial).
        """

        # 1) Read without locks
        se = self.repo.get_by_id(se_id, for_update=False)
        if not se:
            raise NotFound("Stock Entry not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=se.company_id,
            target_branch_id=se.branch_id,
        )
        V.guard_submittable_state(se.doc_status)

        if not se.items:
            raise V.BizValidationError("No items to submit.")

        tz = get_company_timezone(self.s, se.company_id)
        posting_dt = resolve_posting_dt(
            se.posting_date.date(),
            created_at=se.created_at,
            tz=tz,
            treat_midnight_as_date=True,
        )
        dt_id = self._get_doc_type_id_or_400("STOCK_ENTRY")

        # 2) Build intents from current items (no DB write yet)
        lines: List[Dict[str, Any]] = []
        for it in se.items:
            lines.append(
                {
                    "item_id": it.item_id,
                    "quantity": it.quantity,
                    "rate": it.rate,
                    "source_warehouse_id": it.source_warehouse_id,
                    "target_warehouse_id": it.target_warehouse_id,
                    "uom_id": it.uom_id,
                    "base_uom_id": None,  # handler will fetch if needed
                    "doc_row_id": it.id,
                }
            )

        intents = build_intents_for_stock_entry(
            company_id=se.company_id,
            branch_id=se.branch_id,
            posting_dt=posting_dt,
            doc_type_id=dt_id,
            doc_id=se.id,
            entry_type=se.stock_entry_type,
            lines=lines,
            session=self.s,
        )

        pairs = {(i.item_id, i.warehouse_id) for i in intents}
        is_backdated = self._detect_backdated(se.company_id, pairs, posting_dt)

        # 3) Atomic write phase
        with self.s.begin_nested():
            se_locked = self.repo.get_by_id(se_id, for_update=True)
            V.guard_submittable_state(se_locked.doc_status)

            # 3.a Write SLEs
            with lock_pairs(self.s, pairs):
                for idx, intent in enumerate(intents):
                    append_sle(
                        self.s,
                        intent,
                        created_at_hint=se_locked.created_at,
                        tz_hint=tz,
                        batch_index=idx,
                    )

            # 3.b Repost if backdated
            if is_backdated:
                for item_id, wh_id in pairs:
                    repost_from(
                        s=self.s,
                        company_id=se_locked.company_id,
                        item_id=item_id,
                        warehouse_id=wh_id,
                        start_dt=posting_dt,
                        exclude_doc_types=set(),
                    )

            # 3.c Re-derive bins
            for item_id, wh_id in pairs:
                derive_bin(self.s, se_locked.company_id, item_id, wh_id)

            # 3.d Compute total stock value difference from SLE rows
            sle_rows: List[StockLedgerEntry] = (
                self.s.query(StockLedgerEntry)
                .filter(
                    StockLedgerEntry.company_id == se_locked.company_id,
                    StockLedgerEntry.doc_type_id == dt_id,
                    StockLedgerEntry.doc_id == se_locked.id,
                    StockLedgerEntry.is_cancelled == False,
                )
                .all()
            )
            total_difference = sum(
                (sle.stock_value_difference or Dec("0")) for sle in sle_rows
            )

            # 3.e Post GL if there is any net difference
            if total_difference != Dec("0"):
                if not se_locked.difference_account_id:
                    se_locked.difference_account_id = self._get_difference_account_id(
                        company_id=se_locked.company_id,
                        entry_type=se_locked.stock_entry_type,
                        explicit_id=None,
                    )

                ctx = PostingContext(
                    company_id=se_locked.company_id,
                    branch_id=se_locked.branch_id,
                    source_doctype_id=dt_id,
                    source_doc_id=se_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    # 🔹 For SUBMIT we use a normal auto JE
                    entry_type="AUTO",
                    remarks=f"Stock Entry {se_locked.code}",
                    template_code="STOCK_ENTRY_GENERAL",
                    payload={"STOCK_ENTRY_DIFFERENCE": total_difference},
                    dynamic_account_context={
                        "difference_account_id": se_locked.difference_account_id
                    },
                )
                PostingService(self.s).post(ctx)

            # 3.f Mark submitted
            se_locked.doc_status = DocStatusEnum.SUBMITTED
            self.repo.save(se_locked)

        self.s.commit()

        # 4) Invalidate reports: stock + financial
        invalidate_all_core_reports_for_company(se.company_id, include_stock=True)
        invalidate_financial_reports_for_company(se.company_id)

        return se

    # ----------------------------------------------------------------------
    # CANCEL (with reversing GL)
    # ----------------------------------------------------------------------


    # ----------------------------------------------------------------------
    # CANCEL (with reversing GL)
    # ----------------------------------------------------------------------
    def cancel_stock_entry(
        self, *, se_id: int, context: AffiliationContext
    ) -> StockEntry:
        """
        Cancel a submitted Stock Entry.

        STOCK:
        - Marks its SLEs as cancelled and replays stock from the earliest SLE.
        - Re-derives bins.

        GL:
        - If original posting created an auto JE, call PostingService.cancel(...)
          to create a clean reversal JE (ERP-style).

        This matches ERPNext patterns:
        - SLEs: mark cancelled + replay
        - GL: reversal journal with swapped DR/CR.
        """
        se = self.repo.get_by_id(se_id, for_update=False)
        if not se:
            raise NotFound("Stock Entry not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=se.company_id,
            target_branch_id=se.branch_id,
        )
        V.guard_cancellable_state(se.doc_status)

        PostingDateValidator.validate_standalone_document(
            self.s,
            se.posting_date,
            se.company_id,
            created_at=se.created_at,
            treat_midnight_as_date=True,
        )

        dt_id = self._get_doc_type_id_or_400("STOCK_ENTRY")
        company_tz = get_company_timezone(self.s, se.company_id)

        # Existing, non-cancelled SLEs for this Stock Entry
        sle_rows: List[StockLedgerEntry] = (
            self.s.query(StockLedgerEntry)
            .filter(
                StockLedgerEntry.company_id == se.company_id,
                StockLedgerEntry.doc_type_id == dt_id,
                StockLedgerEntry.doc_id == se.id,
                StockLedgerEntry.is_cancelled == False,
            )
            .all()
        )
        if not sle_rows:
            raise V.BizValidationError(
                "No stock ledger entries found for this Stock Entry; cannot cancel."
            )

        pairs: Set[Tuple[int, int]] = {
            (sle.item_id, sle.warehouse_id) for sle in sle_rows
        }
        original_total_diff = sum(
            (sle.stock_value_difference or Dec("0")) for sle in sle_rows
        )

        earliest_dt = min(sle.posting_time for sle in sle_rows)

        posting_date_dt = (
            se.posting_date
            if isinstance(se.posting_date, datetime)
            else datetime.combine(se.posting_date, datetime.min.time())
        )
        posting_dt = resolve_posting_dt(
            posting_date_dt,
            created_at=se.created_at,
            tz=company_tz,
            treat_midnight_as_date=True,
        )

        with self.s.begin_nested():
            se_locked = self.repo.get_by_id(se_id, for_update=True)
            V.guard_cancellable_state(se_locked.doc_status)

            # 1) Cancel SLEs
            for sle in sle_rows:
                sle.is_cancelled = True

            # 2) Replay stock from earliest SLE time
            for item_id, wh_id in pairs:
                repost_from(
                    s=self.s,
                    company_id=se_locked.company_id,
                    item_id=item_id,
                    warehouse_id=wh_id,
                    start_dt=earliest_dt,
                    exclude_doc_types=set(),
                )

            # 3) Re-derive bins
            for item_id, wh_id in pairs:
                derive_bin(self.s, se_locked.company_id, item_id, wh_id)

            # 4) Reverse GL if the submit actually posted any difference
            if original_total_diff != Dec("0"):
                # We don't recompute a new template. We just reverse
                # the existing auto JE for this document.
                ctx_cancel = PostingContext(
                    company_id=se_locked.company_id,
                    branch_id=se_locked.branch_id,
                    source_doctype_id=dt_id,
                    source_doc_id=se_locked.id,
                    posting_date=posting_dt,  # required by dataclass, not used in cancel()
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    remarks=f"Cancel Stock Entry {se_locked.code}",
                )
                PostingService(self.s).cancel(ctx_cancel)

            # 5) Mark Stock Entry as CANCELLED
            se_locked.doc_status = DocStatusEnum.CANCELLED
            self.repo.save(se_locked)

        self.s.commit()

        # Invalidate again – cancellation changes stock balances & valuation
        invalidate_all_core_reports_for_company(se.company_id, include_stock=True)
        invalidate_financial_reports_for_company(se.company_id)

        return se
