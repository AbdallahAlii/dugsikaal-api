# app/application_stock/engine/handlers/stock_entry.py

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Dict, Any, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.inventory_models import Item, ItemTypeEnum
from app.application_stock.stock_models import StockLedgerEntry, StockEntryType
from app.application_nventory.services.uom_math import (
    to_base_qty,
    UOMFactorMissing,
)

logger = logging.getLogger(__name__)

__all__ = ["build_intents_for_stock_entry"]


# ---------------------------------------------------------------------------
# Small helpers (shared style with sales handler)
# ---------------------------------------------------------------------------

def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required decimal value for '{field}'")
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error("Decimal conversion failed for field '%s': %r - %s", field, val, str(e))
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")


def _coerce_int(val: Any, *, field: str) -> int:
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error("Integer conversion failed for field '%s': %r - %s", field, val, str(e))
        raise ValueError(f"Invalid integer for '{field}': {val!r}")


def _get_base_uom_id(session: Session, item_id: int) -> int:
    """
    Fetch base UOM for item and ensure it's a stock item.

    Supports two styles:
    - Old: Item has boolean column is_stock_item
    - New: Item has item_type == ItemTypeEnum.STOCK_ITEM
    """
    item = session.get(Item, item_id)
    if not item:
        raise ValueError(f"Item {item_id} not found")

    # Prefer explicit is_stock_item flag if present
    if hasattr(item, "is_stock_item"):
        if not bool(getattr(item, "is_stock_item")):
            raise ValueError(f"Item {item_id} is not marked as a stock item")
    else:
        # Fallback: check item_type Enum
        if getattr(item, "item_type", None) != ItemTypeEnum.STOCK_ITEM:
            raise ValueError(f"Item {item_id} is not marked as a stock item")

    if not getattr(item, "base_uom_id", None):
        raise ValueError(f"Item {item_id} has no base UOM configured")

    return int(item.base_uom_id)


def _to_base_qty_only(
    *,
    session: Session,
    item_id: int,
    qty: Decimal,
    uom_id: Optional[int],
    maybe_base_uom_id: Optional[int],
) -> Tuple[Decimal, int]:
    """
    Convert quantity to base UOM if needed (rate untouched).

    - If uom_id is None → treat qty as base UOM.
    - If uom_id == base_uom_id → no conversion.
    - Else → use uom_math.to_base_qty (strict=True).
    """
    if uom_id is None:
        base_uom_id = maybe_base_uom_id or _get_base_uom_id(session, item_id)
        return qty, base_uom_id

    uom_id = _coerce_int(uom_id, field="uom_id")
    base_uom_id = (
        _coerce_int(maybe_base_uom_id, field="base_uom_id")
        if maybe_base_uom_id
        else _get_base_uom_id(session, item_id)
    )

    if uom_id == base_uom_id:
        return qty, base_uom_id

    try:
        base_qty_float, _factor = to_base_qty(
            qty=qty,
            item_id=item_id,
            uom_id=uom_id,
            base_uom_id=base_uom_id,
            strict=True,
        )
        return Decimal(str(base_qty_float)), base_uom_id
    except UOMFactorMissing as e:
        raise ValueError(
            f"Missing UOM conversion for item_id={item_id}, "
            f"uom_id={uom_id}, base_uom_id={base_uom_id}"
        ) from e


def _get_current_stock_state(
    session: Session,
    *,
    company_id: int,
    item_id: int,
    warehouse_id: int,
    posting_dt: datetime,
) -> Tuple[Decimal, Decimal]:
    """
    Last NON-CANCELLED SLE at or before posting_dt for (company,item,warehouse).
    Used for Material Transfer valuation rate.
    """
    from sqlalchemy import or_  # local import to avoid shadowing

    q = (
        session.query(StockLedgerEntry)
        .filter(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
        )
    )

    if posting_dt is not None:
        q = q.filter(
            or_(
                StockLedgerEntry.posting_date < posting_dt.date(),
                and_(
                    StockLedgerEntry.posting_date == posting_dt.date(),
                    StockLedgerEntry.posting_time <= posting_dt,
                ),
            )
        )

    latest: Optional[StockLedgerEntry] = (
        q.order_by(
            StockLedgerEntry.posting_date.desc(),
            StockLedgerEntry.posting_time.desc(),
            StockLedgerEntry.id.desc(),
        )
        .limit(1)
        .first()
    )

    if latest:
        current_qty = latest.qty_after_transaction or Decimal("0")
        current_rate = latest.valuation_rate or Decimal("0")
        return Decimal(str(current_qty)), Decimal(str(current_rate))

    return Decimal("0"), Decimal("0")


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_intents_for_stock_entry(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    entry_type: StockEntryType,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLEIntents for Stock Entry (Material Receipt / Issue / Transfer),
    UOM-aware, ERP-style semantics.
    """
    s = session or db.session
    intents: List[SLEIntent] = []

    for idx, line in enumerate(lines):
        item_id = _coerce_int(line.get("item_id"), field="item_id")
        qty_uom = _to_decimal(line.get("quantity"), field="quantity")
        if qty_uom <= 0:
            raise ValueError(f"Row {idx + 1}: quantity must be > 0 for Stock Entry.")

        uom_id = line.get("uom_id")
        base_uom_id = line.get("base_uom_id")
        doc_row_id = line.get("doc_row_id") or line.get("id")

        src_wh = line.get("source_warehouse_id")
        tgt_wh = line.get("target_warehouse_id")

        # Convert to base quantity (rate untouched here)
        base_qty, base_uom_id = _to_base_qty_only(
            session=s,
            item_id=item_id,
            qty=qty_uom,
            uom_id=uom_id,
            maybe_base_uom_id=base_uom_id,
        )

        # Rate: assume already per BASE UOM (UI responsibility)
        rate = _to_decimal(line.get("rate"), field="rate", default=Decimal("0"))

        if entry_type == StockEntryType.MATERIAL_RECEIPT:
            wh_id = _coerce_int(tgt_wh, field="target_warehouse_id")

            intents.append(
                SLEIntent(
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    warehouse_id=wh_id,
                    posting_dt=posting_dt,
                    actual_qty=base_qty,              # +base_qty
                    incoming_rate=rate,               # per BASE UOM
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=doc_id,
                    doc_row_id=doc_row_id,
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={
                        "entry_type": "Material Receipt",
                        "base_uom_id": base_uom_id,
                        "txn_qty": str(qty_uom),
                    },
                )
            )

        elif entry_type == StockEntryType.MATERIAL_ISSUE:
            wh_id = _coerce_int(src_wh, field="source_warehouse_id")

            intents.append(
                SLEIntent(
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    warehouse_id=wh_id,
                    posting_dt=posting_dt,
                    actual_qty=-base_qty,             # issue → negative
                    incoming_rate=None,
                    outgoing_rate=None,               # MA handled by SLE writer
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=doc_id,
                    doc_row_id=doc_row_id,
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={
                        "entry_type": "Material Issue",
                        "base_uom_id": base_uom_id,
                        "txn_qty": str(qty_uom),
                    },
                )
            )

        elif entry_type == StockEntryType.MATERIAL_TRANSFER:
            src_id = _coerce_int(src_wh, field="source_warehouse_id")
            tgt_id = _coerce_int(tgt_wh, field="target_warehouse_id")

            # valuation rate from source (moving average at posting_dt)
            _current_qty, current_rate = _get_current_stock_state(
                s,
                company_id=company_id,
                item_id=item_id,
                warehouse_id=src_id,
                posting_dt=posting_dt,
            )

            # leg 1: issue from source (MA rate handled by SLE writer)
            intents.append(
                SLEIntent(
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    warehouse_id=src_id,
                    posting_dt=posting_dt,
                    actual_qty=-base_qty,
                    incoming_rate=None,
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=doc_id,
                    doc_row_id=doc_row_id,
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={
                        "entry_type": "Material Transfer",
                        "leg": "issue",
                        "base_uom_id": base_uom_id,
                        "txn_qty": str(qty_uom),
                    },
                )
            )

            # leg 2: receipt into target at same valuation rate
            intents.append(
                SLEIntent(
                    company_id=company_id,
                    branch_id=branch_id,
                    item_id=item_id,
                    warehouse_id=tgt_id,
                    posting_dt=posting_dt,
                    actual_qty=base_qty,
                    incoming_rate=current_rate,       # MA rate from source WH
                    outgoing_rate=None,
                    stock_value_difference=Decimal("0"),
                    doc_type_id=doc_type_id,
                    doc_id=doc_id,
                    doc_row_id=doc_row_id,
                    adjustment_type=AdjustmentType.NORMAL,
                    meta={
                        "entry_type": "Material Transfer",
                        "leg": "receipt",
                        "base_uom_id": base_uom_id,
                        "txn_qty": str(qty_uom),
                        "source_rate": str(current_rate),
                    },
                )
            )

        else:
            raise ValueError(f"Unknown Stock Entry type: {entry_type}")

    return intents
