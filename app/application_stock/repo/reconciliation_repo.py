# app/application_stock/reconciliation_repo.py

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Tuple, Set

from sqlalchemy import select, func, exists, tuple_, and_
from sqlalchemy.orm import Session, selectinload

from app.application_stock.stock_models import StockReconciliation, StockReconciliationItem
from app.application_nventory.inventory_models import Item, ItemTypeEnum
from app.application_stock.stock_models import Warehouse, DocStatusEnum
from app.application_org.models.company import Branch

from config.database import db
from app.common.models.base import StatusEnum


class StockReconciliationRepository:
    """Data Access Layer for Stock Reconciliation documents."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Document Read Operations ---

    def get_by_id(self, recon_id: int, for_update: bool = False) -> Optional[StockReconciliation]:
        """
        Fetches a Stock Reconciliation by its ID, with its items.
        Applies a pessimistic lock if `for_update` is True.
        """
        stmt = (
            select(StockReconciliation)
            .options(selectinload(StockReconciliation.items))
            .where(StockReconciliation.id == recon_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        """Checks if a document code already exists within a branch, case-insensitively."""
        stmt = select(exists().where(
            StockReconciliation.company_id == company_id,
            StockReconciliation.branch_id == branch_id,
            func.lower(StockReconciliation.code) == func.lower(code)
        ))
        if exclude_id:
            stmt = stmt.where(StockReconciliation.id != exclude_id)
        return self.s.execute(stmt).scalar()

    # --- Document Write Operations ---

    def save(self, recon: StockReconciliation) -> StockReconciliation:
        """Adds a new reconciliation to the session or flushes changes for an existing one."""
        if recon not in self.s:
            self.s.add(recon)
        self.s.flush()
        return recon

    def sync_lines(self, recon: StockReconciliation, lines_data: List[Dict]) -> None:
        """Atomically synchronizes the item lines of a Stock Reconciliation."""
        existing_lines_map = {line.id: line for line in recon.items}
        lines_to_keep_ids: Set[int] = set()

        for line_data in lines_data:
            line_id = line_data.get("id")
            if line_id and line_id in existing_lines_map:
                line = existing_lines_map[line_id]
                for key, value in line_data.items():
                    if hasattr(line, key):
                        setattr(line, key, value)
                lines_to_keep_ids.add(line_id)
            else:
                new_line = StockReconciliationItem(reconciliation_id=recon.id, **line_data)
                self.s.add(new_line)

        lines_to_delete_ids = set(existing_lines_map.keys()) - lines_to_keep_ids
        for line_id in lines_to_delete_ids:
            self.s.delete(existing_lines_map[line_id])

    # --- Master Data Validation Queries ---

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        """
        Returns the subset of warehouse IDs that are valid, active, and not group warehouses (leaf nodes).
        """
        if not warehouse_ids:
            return set()

        from sqlalchemy.orm import aliased
        W_child = aliased(Warehouse)

        child_exists = exists(
            select(1).where(W_child.parent_warehouse_id == Warehouse.id)
        )

        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~child_exists,  # not a parent → i.e., leaf/transactional
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        """Fetches key details for a batch of items for validation."""
        if not item_ids:
            return {}
        stmt = select(Item.id, Item.status, Item.item_type, Item.base_uom_id).where(
            Item.id.in_(item_ids),
            Item.company_id == company_id
        )
        rows = self.s.execute(stmt).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id
            }
            for r in rows
        }

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        """
        Return the company_id for a given branch, or None if not found.
        Used by resolve_company_branch_and_scope() to canonicalize scope.
        """
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()

    def get_current_stock_state_for_items(self, company_id: int, posting_dt: datetime,
                                          item_warehouse_pairs: List[Tuple[int, int]]) -> Dict[Tuple[int, int], Dict]:
        """
        Production-optimized: Bin table for performance, SLE for accuracy
        """
        if not item_warehouse_pairs:
            return {}

        pair_set = set(item_warehouse_pairs)

        # Fast path: Try Bin table first (for read-heavy operations)
        try:
            from app.application_stock.stock_models import Bin
            stmt = (
                select(Bin.item_id, Bin.warehouse_id, Bin.actual_qty, Bin.valuation_rate)
                .where(
                    Bin.company_id == company_id,
                    tuple_(Bin.item_id, Bin.warehouse_id).in_(pair_set)
                )
            )
            rows = self.s.execute(stmt).all()
            result = {}
            for item_id, wh_id, actual_qty, valuation_rate in rows:
                result[(item_id, wh_id)] = {
                    "current_qty": Decimal(actual_qty or 0),
                    "current_valuation_rate": Decimal(valuation_rate or 0)
                }

            # Fill missing pairs
            for p in pair_set:
                result.setdefault(p, {"current_qty": Decimal('0'), "current_valuation_rate": Decimal('0')})
            return result

        except Exception as e:
            logging.warning("Bin table not available, falling back to SLE: %s", e)
            # Fall through to SLE query

        # Accurate path: SLE window function query
        from app.application_stock.stock_models import StockLedgerEntry

        subq = (
            select(
                StockLedgerEntry.id.label("sle_id"),
                StockLedgerEntry.item_id,
                StockLedgerEntry.warehouse_id,
                func.row_number().over(
                    partition_by=(StockLedgerEntry.item_id, StockLedgerEntry.warehouse_id),
                    order_by=(
                        StockLedgerEntry.posting_date.desc(),
                        StockLedgerEntry.posting_time.desc(),
                        StockLedgerEntry.id.desc()
                    )
                ).label("rn")
            )
            .where(
                StockLedgerEntry.company_id == company_id,
                StockLedgerEntry.is_cancelled == False,
                and_(
                    (StockLedgerEntry.posting_date < posting_dt.date()) |
                    and_(
                        StockLedgerEntry.posting_date == posting_dt.date(),
                        StockLedgerEntry.posting_time <= posting_dt
                    )
                ),
                tuple_(StockLedgerEntry.item_id, StockLedgerEntry.warehouse_id).in_(pair_set)
            )
            .subquery()
        )

        sle_stmt = (
            select(
                StockLedgerEntry.item_id,
                StockLedgerEntry.warehouse_id,
                StockLedgerEntry.qty_after_transaction,
                StockLedgerEntry.valuation_rate
            )
            .select_from(StockLedgerEntry.join(subq, StockLedgerEntry.id == subq.c.sle_id))
            .where(subq.c.rn == 1)
        )

        rows = self.s.execute(sle_stmt).all()
        result = {}
        for item_id, wh_id, qty_after, rate in rows:
            result[(item_id, wh_id)] = {
                "current_qty": Decimal(qty_after or 0),
                "current_valuation_rate": Decimal(rate or 0)
            }

        for p in pair_set:
            result.setdefault(p, {"current_qty": Decimal('0'), "current_valuation_rate": Decimal('0')})

        return result