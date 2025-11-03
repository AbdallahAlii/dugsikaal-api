from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select, func, and_, tuple_
from sqlalchemy.orm import Session

from config.database import db
from app.common.models.base import StatusEnum
from app.application_nventory.inventory_models import Item, UOMConversion, ItemTypeEnum
from app.application_stock.stock_models import Bin, StockLedgerEntry

DEC6 = Decimal("0.000001")

def _q(v) -> Decimal:
    return (Decimal(str(v or 0))).quantize(DEC6)

class StockAvailabilityRepository:
    """Read-only, fast readers for availability."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---- Item core ----
    def get_item_core(self, company_id: int, item_id: int) -> dict | None:
        row = self.s.execute(
            select(Item.item_type, Item.base_uom_id, Item.status)
            .where(Item.company_id == company_id, Item.id == item_id)
        ).first()
        if not row:
            return None
        return {
            "is_stock_item": row.item_type == ItemTypeEnum.STOCK_ITEM,
            "base_uom_id": row.base_uom_id,
            "is_active": row.status == StatusEnum.ACTIVE,
        }

    # ---- Latest (Sales screens) via Bin (O(1)) ----
    def sum_bins(self, company_id: int, item_id: int, warehouse_ids: Sequence[int]) -> dict:
        if not warehouse_ids:
            return {"actual": Decimal("0"), "reserved": Decimal("0"), "ordered": Decimal("0")}
        a, r, o = self.s.execute(
            select(
                func.coalesce(func.sum(Bin.actual_qty), 0),
                func.coalesce(func.sum(Bin.reserved_qty), 0),
                func.coalesce(func.sum(Bin.ordered_qty), 0),
            ).where(
                Bin.company_id == company_id,
                Bin.item_id == item_id,
                Bin.warehouse_id.in_(set(warehouse_ids)),
            )
        ).one()
        return {"actual": _q(a), "reserved": _q(r), "ordered": _q(o)}

    # ---- As-of (backdated) via SLE ----
    def sum_sle_as_of(self, company_id: int, item_id: int, warehouse_ids: Sequence[int], as_of: datetime) -> Decimal:
        """Return on-hand qty as-of timestamp (reserved/ordered unknown -> use actual only)."""
        if not warehouse_ids:
            return Decimal("0")
        pairs = {(item_id, wid) for wid in set(warehouse_ids)}
        sub = (
            select(
                StockLedgerEntry.id.label("sle_id"),
                StockLedgerEntry.item_id,
                StockLedgerEntry.warehouse_id,
                func.row_number().over(
                    partition_by=(StockLedgerEntry.item_id, StockLedgerEntry.warehouse_id),
                    order_by=(StockLedgerEntry.posting_date.desc(),
                              StockLedgerEntry.posting_time.desc(),
                              StockLedgerEntry.id.desc())
                ).label("rn")
            )
            .where(
                StockLedgerEntry.company_id == company_id,
                StockLedgerEntry.is_cancelled.is_(False),
                and_(
                    (StockLedgerEntry.posting_date < as_of.date()) |
                    and_(StockLedgerEntry.posting_date == as_of.date(),
                         StockLedgerEntry.posting_time <= as_of)
                ),
                tuple_(StockLedgerEntry.item_id, StockLedgerEntry.warehouse_id).in_(pairs),
            )
        ).subquery()

        rows = self.s.execute(
            select(StockLedgerEntry.qty_after_transaction)
            .where(StockLedgerEntry.id == sub.c.sle_id, sub.c.rn == 1)
        ).all()
        return _q(sum((r[0] or 0) for r in rows))

    # ---- UOM factor (1 this = factor base) with cache path ----
    def get_factor(self, item_id: int, uom_id: Optional[int], base_uom_id: int) -> Decimal:
        # If no UOM or same as base -> 1
        if not uom_id or uom_id == base_uom_id:
            return Decimal("1")

        # Use your cached resolver (fast path)
        try:
            from app.application_nventory.services.uom_math import resolve_factor  # uses uom_cache under the hood
            f = resolve_factor(item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=True)
            return _q(f)
        except Exception:
            # As absolute fallback, try direct table (should rarely hit due to cache)
            row = self.s.execute(
                select(UOMConversion.conversion_factor)
                .where(
                    UOMConversion.item_id == item_id,
                    UOMConversion.uom_id == uom_id,
                    UOMConversion.is_active.is_(True)
                )
            ).scalar_one_or_none()
            if not row:
                raise ValueError("UOM not compatible for this item.")
            return _q(row)
