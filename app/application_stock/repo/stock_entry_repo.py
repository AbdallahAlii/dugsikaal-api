# app/application_stock/repo/stock_entry_repo.py
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Dict, Set, Tuple

from sqlalchemy import select, exists, func, and_
from sqlalchemy.orm import Session, selectinload, aliased

from config.database import db
from app.common.models.base import StatusEnum
from app.application_org.models.company import Branch
from app.application_nventory.inventory_models import (
    Item, UnitOfMeasure, UOMConversion, ItemTypeEnum,
)
from app.application_stock.stock_models import (
    StockEntry,
    StockEntryItem,
    Warehouse,
    DocStatusEnum,
    StockLedgerEntry,
    DocumentType, StockEntryType,
)


class StockEntryRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ----- core CRUD -----

    def get_by_id(self, se_id: int, *, for_update: bool = False) -> Optional[StockEntry]:
        stmt = (
            select(StockEntry)
            .options(selectinload(StockEntry.items))
            .where(StockEntry.id == se_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(
        self,
        company_id: int,
        branch_id: int,
        code: str,
        exclude_id: Optional[int] = None,
    ) -> bool:
        stmt = select(
            exists().where(
                StockEntry.company_id == company_id,
                StockEntry.branch_id == branch_id,
                func.lower(StockEntry.code) == func.lower(code),
            )
        )
        if exclude_id:
            stmt = stmt.where(StockEntry.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    def save(self, se: StockEntry) -> StockEntry:
        if se not in self.s:
            self.s.add(se)
        self.s.flush()
        return se

    def sync_lines(self, se: StockEntry, lines_data: List[Dict]) -> None:
        existing = {ln.id: ln for ln in se.items}
        keep: Set[int] = set()

        for data in lines_data:
            line_id = data.get("id")
            if line_id and line_id in existing:
                row = existing[line_id]
                for k, v in data.items():
                    if hasattr(row, k):
                        setattr(row, k, v)
                keep.add(line_id)
            else:
                self.s.add(StockEntryItem(stock_entry_id=se.id, **data))

        # delete removed
        for line_id in set(existing.keys()) - keep:
            self.s.delete(existing[line_id])

    # ----- lookups & helpers -----

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        return self.s.execute(
            select(Branch.company_id).where(Branch.id == branch_id)
        ).scalar_one_or_none()

    def get_transactional_warehouse_ids(
        self, company_id: int, branch_id: int, warehouse_ids: List[int]
    ) -> Set[int]:
        if not warehouse_ids:
            return set()

        W2 = aliased(Warehouse)
        has_child = select(W2.id).where(W2.parent_warehouse_id == Warehouse.id).exists()

        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~has_child,  # leaf only
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        if not item_ids:
            return {}
        stmt = select(
            Item.id,
            Item.status,
            Item.item_type,
            Item.base_uom_id,
        ).where(
            Item.id.in_(item_ids),
            Item.company_id == company_id,
        )
        rows = self.s.execute(stmt).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id,
            }
            for r in rows
        }

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        if not uom_ids:
            return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE,
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_compatible_uom_pairs(
        self, company_id: int, pairs: List[Tuple[int, int]]
    ) -> Set[Tuple[int, int]]:
        """
        Return the set of (item_id, uom_id) pairs that are valid for the given items.

        With the NEW UOM model:

        - Item has `base_uom_id`
        - UOMConversion has:
              item_id, uom_id, conversion_factor, is_active
        - Rule: 1 [uom_id] = conversion_factor [base_uom]

        So a (item_id, uom_id) is valid if:
          - uom_id == item's base_uom_id
          - OR there is an active UOMConversion row for (item_id, uom_id)
        """
        if not pairs:
            return set()

        item_ids = {p[0] for p in pairs}

        # Map item -> base_uom_id for this company
        base_map = dict(
            self.s.execute(
                select(Item.id, Item.base_uom_id).where(
                    Item.id.in_(item_ids),
                    Item.company_id == company_id,
                )
            ).all()
        )

        # Get all active conversions for these items
        conv_stmt = select(
            UOMConversion.item_id,
            UOMConversion.uom_id,
        ).where(
            UOMConversion.item_id.in_(item_ids),
            UOMConversion.is_active == True,  # noqa: E712
        )

        conv_set: Set[Tuple[int, int]] = {
            (row.item_id, row.uom_id)
            for row in self.s.execute(conv_stmt).all()
        }

        ok: Set[Tuple[int, int]] = set()
        for item_id, uom_id in pairs:
            base = base_map.get(item_id)
            if not base:
                # no base uom defined → we can't validate, skip
                continue

            # valid if equal to base UOM, or has an explicit conversion row
            if uom_id == base or (item_id, uom_id) in conv_set:
                ok.add((item_id, uom_id))

        return ok

    def get_doc_type_id_by_code(self, code: str) -> Optional[int]:
        return self.s.execute(
            select(DocumentType.id).where(DocumentType.code == code)
        ).scalar_one_or_none()

    def has_future_sle(
        self,
        company_id: int,
        start_dt: datetime,
        pairs: Set[Tuple[int, int]],
    ) -> bool:
        """
        Is there any non-cancelled SLE strictly after start_dt for any (item, wh) pair?
        """
        if not pairs:
            return False

        for item_id, wh_id in pairs:
            q = (
                self.s.query(StockLedgerEntry.id)
                .filter(
                    StockLedgerEntry.company_id == company_id,
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
            if self.s.query(q.exists()).scalar():
                return True
        return False
    def get_default_difference_account_id(
        self,
        company_id: int,
        entry_type: StockEntryType,
    ) -> Optional[int]:
        """
        Resolve default Difference Account for Stock Entry based on your COA.

        - For Material Receipt / Issue -> "Stock Adjustments" (code 5015 in your seed)
        - For Material Transfer        -> None (no net stock value change, so usually no GL)

        We resolve by **name** so it stays stable even if codes differ per company.
        """
        from app.application_accounting.chart_of_accounts.models import Account

        # Only Receipt/Issue need a difference account by default
        if entry_type not in (
            StockEntryType.MATERIAL_RECEIPT,
            StockEntryType.MATERIAL_ISSUE,
        ):
            return None

        target_name = "Stock Adjustments"

        q = select(Account.id).where(
            Account.name == target_name,
            getattr(Account, "is_group", False) == False,
        )

        # If Account has a company_id column, also filter by company_id
        if hasattr(Account, "company_id"):
            q = q.where(Account.company_id == company_id)

        account_id = self.s.execute(q).scalar_one_or_none()

        logging.info(
            "🔍 Default Stock Entry difference account for %s resolved by name '%s' -> %s",
            getattr(entry_type, "value", entry_type),
            target_name,
            account_id,
        )
        return account_id