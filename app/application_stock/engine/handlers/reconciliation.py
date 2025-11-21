# FILE: app/application_stock/engine/handlers/reconciliation.py
# or   app/application_stock/engine/builders/reconciliation_intents.py

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Dict, Any, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.inventory_models import Item
from app.application_stock.stock_models import StockLedgerEntry

logger = logging.getLogger(__name__)

__all__ = ["build_intents_for_reconciliation"]


# ----------------- small helpers -----------------


def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required decimal value for '{field}'")
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(
            "Decimal conversion failed for field '%s': %r - %s",
            field,
            val,
            str(e),
        )
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")


def _coerce_int(val: Any, *, field: str) -> int:
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error(
            "Integer conversion failed for field '%s': %r - %s",
            field,
            val,
            str(e),
        )
        raise ValueError(f"Invalid integer for '{field}': {val!r}")


def _validate_non_negative(val: Decimal, *, field: str, allow_zero: bool = False) -> None:
    if val is None:
        raise ValueError(f"Missing required value for '{field}'")
    if allow_zero:
        if val < 0:
            raise ValueError(f"'{field}' must be >= 0, got {val}")
    else:
        if val <= 0:
            raise ValueError(f"'{field}' must be > 0, got {val}")


def _get_base_uom_id(session: Session, item_id: int) -> int:
    item = session.get(Item, item_id)
    if not item:
        raise ValueError(f"Item {item_id} not found")
    if not item.base_uom_id:
        raise ValueError(f"Item {item_id} has no base UOM configured")
    return int(item.base_uom_id)


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

    This is equivalent to ERPNext's "current stock" at that posting moment.
    """
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


# ----------------- main builder -----------------


def build_intents_for_reconciliation(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLEIntent objects for Stock Reconciliation / Opening Stock.

    Frappe-style logic:

        qty_difference   = counted_qty - current_qty
        counted_value    = counted_qty * valuation_rate_used
        current_value    = current_qty * current_valuation_rate
        value_difference = counted_value - current_value

    The SLE writer then does:

        new_qty   = prev_qty  + qty_difference  == counted_qty
        new_value = prev_value + value_difference == counted_value
        new_rate  = new_value / new_qty         == valuation_rate_used
    """
    s = session or db.session
    intents: List[SLEIntent] = []

    for line_idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            warehouse_id = _coerce_int(line["warehouse_id"], field="warehouse_id")
            counted_qty = _to_decimal(line["quantity"], field="quantity")
            doc_row_id = line.get("doc_row_id")

            # allow 0 for reconciliation (lost/damaged/etc.), but forbid < 0
            _validate_non_negative(counted_qty, field="quantity", allow_zero=True)

            user_valuation_rate = line.get("valuation_rate")
            if user_valuation_rate is not None:
                user_valuation_rate = _to_decimal(
                    user_valuation_rate, field="valuation_rate"
                )
                _validate_non_negative(
                    user_valuation_rate, field="valuation_rate", allow_zero=True
                )

            # UOM / base qty
            base_uom_id = _get_base_uom_id(s, item_id)
            base_counted_qty = counted_qty

            # Current system stock at posting_dt
            current_qty, current_valuation_rate = _get_current_stock_state(
                s,
                company_id=company_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
            )

            valuation_rate_to_use: Decimal
            if user_valuation_rate is not None:
                valuation_rate_to_use = user_valuation_rate
            else:
                valuation_rate_to_use = current_valuation_rate

            # --- Frappe-style calculation ---
            qty_difference = base_counted_qty - current_qty

            counted_value = base_counted_qty * valuation_rate_to_use
            current_value = current_qty * current_valuation_rate

            # ✅ CRITICAL FIX: new_value = counted_value
            # => value_difference = counted_value - current_value
            value_difference = counted_value - current_value

            logger.info(
                "🔄 Reconciliation Calculation (Frappe Style):\n"
                "  Current: %s @ $%s = $%s\n"
                "  Counted: %s @ $%s = $%s\n"
                "  Qty Adjustment: %s units\n"
                "  Value Adjustment: %s - %s = %s",
                current_qty,
                current_valuation_rate,
                current_value,
                base_counted_qty,
                valuation_rate_to_use,
                counted_value,
                qty_difference,
                counted_value,
                current_value,
                value_difference,
            )

            # For reporting on the line
            line.update(
                {
                    "current_qty": current_qty,
                    "current_valuation_rate": current_valuation_rate,
                    "qty_difference": qty_difference,
                    # amount_difference is normally absolute in UI
                    "amount_difference": abs(value_difference),
                    "is_gain": value_difference > 0,
                    "counted_value": counted_value,
                    "current_value": current_value,
                }
            )

            purpose = line.get("purpose", "stock_reconciliation")

            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=qty_difference,
                incoming_rate=None,
                outgoing_rate=None,
                stock_value_difference=value_difference,
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.RECONCILIATION,
                meta={
                    "base_uom_id": base_uom_id,
                    "counted_qty": str(counted_qty),
                    "counted_qty_base": str(base_counted_qty),
                    "current_qty": str(current_qty),
                    "current_valuation_rate": str(current_valuation_rate),
                    "valuation_rate_used": str(valuation_rate_to_use),
                    "qty_difference": str(qty_difference),
                    "counted_value": str(counted_value),
                    "current_value": str(current_value),
                    "value_difference": str(value_difference),
                    "is_gain": str(value_difference > 0).lower(),
                    "purpose": purpose,
                    "reconciliation_type": "frappe_style",
                },
            )
            intents.append(intent)

        except Exception as e:
            logger.exception("Failed to process reconciliation line %s: %s", line_idx, e)
            raise

    return intents
