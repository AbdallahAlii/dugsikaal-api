#
# # FILE: app/application_stock/engine/builders/reconciliation_intents.py
#
# from __future__ import annotations
#
# import logging
# from datetime import datetime
# from decimal import Decimal, InvalidOperation
# from typing import Iterable, List, Dict, Any, Optional, Tuple
#
# from sqlalchemy.orm import Session
#
# from app.application_stock.engine.types import SLEIntent, AdjustmentType
# from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
# from app.application_nventory.inventory_models import Item
# from app.application_stock.stock_models import StockLedgerEntry
# from config.database import db
#
# logger = logging.getLogger(__name__)
#
# __all__ = ["build_intents_for_reconciliation"]
#
#
# def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
#     if val is None:
#         if default is not None:
#             return default
#         raise ValueError(f"Missing required decimal value for '{field}'")
#     try:
#         return Decimal(str(val))
#     except (InvalidOperation, TypeError, ValueError) as e:
#         logger.error(f"Decimal conversion failed for field '{field}': {val!r} - {str(e)}")
#         raise ValueError(f"Invalid decimal value for '{field}': {val!r}")
#
#
# def _coerce_int(val: Any, *, field: str) -> int:
#     if val is None:
#         raise ValueError(f"Missing required integer value for '{field}'")
#     try:
#         return int(val)
#     except (TypeError, ValueError) as e:
#         logger.error(f"Integer conversion failed for field '{field}': {val!r} - {str(e)}")
#         raise ValueError(f"Invalid integer for '{field}': {val!r}")
#
#
# def _validate_positive_decimal(val: Decimal, *, field: str, allow_zero: bool = False) -> None:
#     if val is None:
#         raise ValueError(f"Missing required value for '{field}'")
#     if allow_zero and val < 0:
#         raise ValueError(f"'{field}' must be >= 0, got {val}")
#     elif not allow_zero and val <= 0:
#         raise ValueError(f"'{field}' must be > 0, got {val}")
#
#
# def _get_base_uom_id(session: Session, item_id: int) -> int:
#     item = session.get(Item, item_id)
#     if not item:
#         raise ValueError(f"Item {item_id} not found")
#     if not item.base_uom_id:
#         raise ValueError(f"Item {item_id} has no base UOM configured")
#     return item.base_uom_id
#
#
# def _get_current_stock_state(session: Session, item_id: int, warehouse_id: int) -> Tuple[Decimal, Decimal]:
#     latest_sle = (
#         session.query(StockLedgerEntry)
#         .filter(
#             StockLedgerEntry.item_id == item_id,
#             StockLedgerEntry.warehouse_id == warehouse_id,
#             StockLedgerEntry.is_cancelled == False,
#         )
#         .order_by(
#             StockLedgerEntry.posting_date.desc(),
#             StockLedgerEntry.posting_time.desc(),
#             StockLedgerEntry.id.desc()
#         )
#         .first()
#     )
#
#     if latest_sle:
#         return latest_sle.qty_after_transaction or Decimal("0"), latest_sle.valuation_rate or Decimal("0")
#     return Decimal("0"), Decimal("0")
#
#
# def build_intents_for_reconciliation(
#         *,
#         company_id: int,
#         branch_id: int,
#         posting_dt: datetime,
#         doc_type_id: int,
#         doc_id: int,
#         lines: Iterable[Dict[str, Any]],
#         session: Optional[Session] = None,
# ) -> List[SLEIntent]:
#     intents: List[SLEIntent] = []
#     s = session or db.session
#
#     for line_idx, line in enumerate(lines):
#         try:
#             item_id = _coerce_int(line["item_id"], field="item_id")
#             warehouse_id = _coerce_int(line["warehouse_id"], field="warehouse_id")
#             counted_qty = _to_decimal(line["quantity"], field="quantity")
#             doc_row_id = line.get("doc_row_id")
#             _validate_positive_decimal(counted_qty, field="quantity", allow_zero=True)  # Allow zero for reconciliation
#
#             user_valuation_rate = line.get("valuation_rate")
#             if user_valuation_rate is not None:
#                 user_valuation_rate = _to_decimal(user_valuation_rate, field="valuation_rate")
#                 _validate_positive_decimal(user_valuation_rate, field="valuation_rate", allow_zero=True)
#
#             # --- Assuming Base UOM for simplicity, add UOM logic back if needed ---
#             base_counted_qty = counted_qty
#             meta = {"base_uom_id": _get_base_uom_id(s, item_id), "counted_qty": str(counted_qty),
#                     "counted_qty_base": str(base_counted_qty)}
#
#             # Get current system state
#             current_qty, current_valuation_rate = _get_current_stock_state(s, item_id, warehouse_id)
#             valuation_rate_to_use = user_valuation_rate if user_valuation_rate is not None else current_valuation_rate
#
#             # --- ✅ CRITICAL FIX: CORRECT FINANCIAL CALCULATION ---
#             qty_difference = base_counted_qty - current_qty
#             # The value of the adjustment is the CHANGE in quantity valued at the specified rate.
#             value_difference = qty_difference * valuation_rate_to_use
#
#             # Update the line dict with calculated values for logging/reporting
#             line.update({
#                 "current_qty": current_qty,
#                 "current_valuation_rate": current_valuation_rate,
#                 "qty_difference": qty_difference,
#                 "amount_difference": abs(value_difference),
#                 "is_gain": value_difference > 0,
#             })
#
#             intent = SLEIntent(
#                 company_id=company_id,
#                 branch_id=branch_id,
#                 item_id=item_id,
#                 warehouse_id=warehouse_id,
#                 posting_dt=posting_dt,
#                 actual_qty=qty_difference,  # The actual change in quantity
#                 incoming_rate=None,
#                 outgoing_rate=None,
#                 stock_value_difference=value_difference,  # The actual change in value
#                 doc_type_id=doc_type_id,
#                 doc_id=doc_id,
#                 doc_row_id=doc_row_id,
#                 adjustment_type=AdjustmentType.RECONCILIATION,
#                 meta={
#                     **meta,
#                     "current_qty": str(current_qty),
#                     "current_valuation_rate": str(current_valuation_rate),
#                     "valuation_rate_used": str(valuation_rate_to_use),
#                     "qty_difference": str(qty_difference),
#                     "value_difference": str(value_difference),
#                     "is_gain": str(value_difference > 0).lower(),
#                     "purpose": line.get("purpose", "stock_reconciliation"),
#                     "reconciliation_type": "frappe_style",
#                 },
#             )
#             intents.append(intent)
#
#         except Exception as e:
#             logger.exception(f"Failed to process line {line_idx}: {e}")
#             raise
#
#     return intents

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
from app.application_nventory.inventory_models import Item
from app.application_stock.stock_models import StockLedgerEntry
from config.database import db

logger = logging.getLogger(__name__)

__all__ = ["build_intents_for_reconciliation"]


def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required decimal value for '{field}'")
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"Decimal conversion failed for field '{field}': {val!r} - {str(e)}")
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")


def _coerce_int(val: Any, *, field: str) -> int:
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error(f"Integer conversion failed for field '{field}': {val!r} - {str(e)}")
        raise ValueError(f"Invalid integer for '{field}': {val!r}")


def _validate_positive_decimal(val: Decimal, *, field: str, allow_zero: bool = False) -> None:
    if val is None:
        raise ValueError(f"Missing required value for '{field}'")
    if allow_zero and val < 0:
        raise ValueError(f"'{field}' must be >= 0, got {val}")
    elif not allow_zero and val <= 0:
        raise ValueError(f"'{field}' must be > 0, got {val}")


def _get_base_uom_id(session: Session, item_id: int) -> int:
    item = session.get(Item, item_id)
    if not item:
        raise ValueError(f"Item {item_id} not found")
    if not item.base_uom_id:
        raise ValueError(f"Item {item_id} has no base UOM configured")
    return item.base_uom_id


def _get_current_stock_state(session: Session, item_id: int, warehouse_id: int) -> Tuple[Decimal, Decimal]:
    latest_sle = (
        session.query(StockLedgerEntry)
        .filter(
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            StockLedgerEntry.is_cancelled == False,
        )
        .order_by(
            StockLedgerEntry.posting_date.desc(),
            StockLedgerEntry.posting_time.desc(),
            StockLedgerEntry.id.desc()
        )
        .first()
    )

    if latest_sle:
        return latest_sle.qty_after_transaction or Decimal("0"), latest_sle.valuation_rate or Decimal("0")
    return Decimal("0"), Decimal("0")


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
    intents: List[SLEIntent] = []
    s = session or db.session

    for line_idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            warehouse_id = _coerce_int(line["warehouse_id"], field="warehouse_id")
            counted_qty = _to_decimal(line["quantity"], field="quantity")
            doc_row_id = line.get("doc_row_id")
            _validate_positive_decimal(counted_qty, field="quantity", allow_zero=True)

            user_valuation_rate = line.get("valuation_rate")
            if user_valuation_rate is not None:
                user_valuation_rate = _to_decimal(user_valuation_rate, field="valuation_rate")
                _validate_positive_decimal(user_valuation_rate, field="valuation_rate", allow_zero=True)

            # UOM handling
            base_uom_id = _get_base_uom_id(s, item_id)
            base_counted_qty = counted_qty
            meta = {
                "base_uom_id": base_uom_id,
                "counted_qty": str(counted_qty),
                "counted_qty_base": str(base_counted_qty)
            }

            # Get current system state
            current_qty, current_valuation_rate = _get_current_stock_state(s, item_id, warehouse_id)
            valuation_rate_to_use = user_valuation_rate if user_valuation_rate is not None else current_valuation_rate

            # ✅ CRITICAL FIX: Frappe-style calculation
            qty_difference = base_counted_qty - current_qty

            # 🎯 FIXED: Use qty_difference × valuation_rate_used (like Frappe)
            value_difference = qty_difference * valuation_rate_to_use

            # For reporting only (not used in SLE)
            counted_value = base_counted_qty * valuation_rate_to_use
            current_value = current_qty * current_valuation_rate

            logger.info(
                f"🔄 Reconciliation Calculation (Frappe Style):\n"
                f"  Current: {current_qty} @ ${current_valuation_rate} = ${current_value}\n"
                f"  Counted: {base_counted_qty} @ ${valuation_rate_to_use} = ${counted_value}\n"
                f"  Qty Adjustment: {qty_difference} units\n"
                f"  Value Adjustment: {qty_difference} × ${valuation_rate_to_use} = ${value_difference}"
            )

            # Update line for reporting
            line.update({
                "current_qty": current_qty,
                "current_valuation_rate": current_valuation_rate,
                "qty_difference": qty_difference,
                "amount_difference": abs(value_difference),
                "is_gain": value_difference > 0,
                "counted_value": counted_value,
                "current_value": current_value,
            })

            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=qty_difference,
                incoming_rate=None,
                outgoing_rate=None,
                stock_value_difference=value_difference,  # ✅ Now correct: 12 × 2 = 24
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.RECONCILIATION,
                meta={
                    **meta,
                    "current_qty": str(current_qty),
                    "current_valuation_rate": str(current_valuation_rate),
                    "valuation_rate_used": str(valuation_rate_to_use),
                    "qty_difference": str(qty_difference),
                    "counted_value": str(counted_value),
                    "current_value": str(current_value),
                    "value_difference": str(value_difference),
                    "is_gain": str(value_difference > 0).lower(),
                    "purpose": line.get("purpose", "stock_reconciliation"),
                    "reconciliation_type": "frappe_style",
                },
            )
            intents.append(intent)

        except Exception as e:
            logger.exception(f"Failed to process line {line_idx}: {e}")
            raise

    return intents