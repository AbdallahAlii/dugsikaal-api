# app/application_stock/engine/handlers/purchase.py
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
from app.application_nventory.inventory_models import Item
from app.business_validation.item_validation import BizValidationError
from config.database import db

logger = logging.getLogger(__name__)

__all__ = [
    # SLE builders for Buying
    "build_intents_for_receipt",
    "build_intents_for_return",
    # (kept for symmetry) Stock Entry transfer
    "build_intents_for_stock_entry",
]

# ---------------------------------------------------------------------------
# Helpers (parity with sales handlers + strict ERP behavior)
# ---------------------------------------------------------------------------

def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    """Safely coerce value to Decimal with consistent error messages."""
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required decimal value for '{field}'")
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error("Decimal conversion failed for field '%s': %r - %s", field, val, e)
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")

def _coerce_int(val: Any, *, field: str) -> int:
    """Safely coerce to int with consistent error messages."""
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error("Integer conversion failed for field '%s': %r - %s", field, val, e)
        raise ValueError(f"Invalid integer for '{field}': {val!r}")

def _validate_positive_decimal(val: Decimal, *, field: str, allow_zero: bool = False) -> None:
    if val is None:
        raise ValueError(f"Missing required value for '{field}'")
    if allow_zero:
        if val < 0:
            raise ValueError(f"'{field}' must be >= 0, got {val}")
    else:
        if val <= 0:
            raise ValueError(f"'{field}' must be > 0, got {val}")

def _get_base_uom_id(session: Session, item_id: int) -> int:
    """Fetch base UOM id for item or fail (strict)."""
    try:
        item = session.get(Item, item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        if not item.base_uom_id:
            raise ValueError(f"Item {item_id} has no base UOM configured")
        return int(item.base_uom_id)
    except Exception as e:
        logger.error("Failed to fetch base UOM for item %s: %s", item_id, e)
        raise ValueError(f"Cannot determine base UOM for item {item_id}: {e}")

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
    """
    if uom_id is None:
        base_uom_id = maybe_base_uom_id or _get_base_uom_id(session, item_id)
        return qty, base_uom_id

    uom_id = _coerce_int(uom_id, field="uom_id")
    base_uom_id = _coerce_int(maybe_base_uom_id, field="base_uom_id") if maybe_base_uom_id else _get_base_uom_id(session, item_id)

    if uom_id == base_uom_id:
        return qty, base_uom_id

    try:
        base_qty_float, _ = to_base_qty(
            qty=qty, item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=True
        )
        return Decimal(str(base_qty_float)), base_uom_id
    except UOMFactorMissing as e:
        raise ValueError(
            f"Missing UOM conversion for item_id={item_id}, uom_id={uom_id}, base_uom_id={base_uom_id}"
        ) from e

def _resolve_line_warehouse(header_wh_id: Optional[int], line: Dict[str, Any], idx: int) -> int:
    """
    Resolve the warehouse to use for a line:
      1) line['warehouse_id'] if present
      2) header_wh_id if provided
      3) raise BizValidationError (strict ERP behavior)
    """
    wh = line.get("warehouse_id")
    if wh is None:
        wh = header_wh_id
    if wh is None:
        # strict: do not allow SLE without warehouse
        raise BizValidationError(
            f"Warehouse missing for stock line #{idx+1} (item {line.get('item_id')})."
        )
    try:
        return int(wh)
    except Exception:
        raise BizValidationError(
            f"Invalid warehouse for stock line #{idx+1} (item {line.get('item_id')}): {wh!r}"
        )

# ---------------------------------------------------------------------------
# SLE Builders (Purchase Receipt / Purchase Return)
# ---------------------------------------------------------------------------

def build_intents_for_receipt(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: Optional[int],   # header-level (optional; used as fallback)
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLE intents for a Purchase **Receipt** (stock coming IN).
    Each line must include:
      - item_id (int)
      - accepted_qty (Decimal > 0)
      - unit_price (Decimal >= 0)  -- always BASE UOM rate in this ERP
      - warehouse_id (int) optional at line; will fallback to header if present
      - uom_id (optional) and base_uom_id (optional)
      - doc_row_id (optional)

    Rules:
      - Quantity converted to base UOM if needed (rate is NOT converted).
      - Resulting SLE: actual_qty **positive** (receipt), incoming_rate set, outgoing_rate None.
      - Warehouse is REQUIRED (line or header). We never emit intents with warehouse=None.
    """
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        "Building receipt intents - Company: %s, Warehouse(header): %s, Doc: %s/%s",
        company_id, warehouse_id, doc_type_id, doc_id
    )

    for idx, ln in enumerate(lines):
        try:
            item_id = _coerce_int(ln["item_id"], field="item_id")
            qty_u = _to_decimal(ln.get("accepted_qty"), field="accepted_qty")
            unit_price = _to_decimal(ln.get("unit_price"), field="unit_price", default=Decimal("0"))
            doc_row_id = ln.get("doc_row_id")

            _validate_positive_decimal(qty_u, field="accepted_qty")
            _validate_positive_decimal(unit_price, field="unit_price", allow_zero=True)

            # Resolve warehouse strictly (line → header → error)
            wh_id = _resolve_line_warehouse(warehouse_id, ln, idx)

            # convert quantity only
            uom_id = ln.get("uom_id")
            base_uom_id = ln.get("base_uom_id")
            base_qty, base_uom_id = _to_base_qty_only(
                session=s, item_id=item_id, qty=qty_u, uom_id=uom_id, maybe_base_uom_id=base_uom_id
            )
            # rate remains as provided (already per base)
            incoming_rate = unit_price

            meta = {
                "base_uom_id": int(base_uom_id),
                "txn_qty": str(qty_u),
                "source": "PurchaseReceipt",
            }

            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=wh_id,
                posting_dt=posting_dt,
                actual_qty=base_qty,          # receipt => positive
                incoming_rate=incoming_rate,  # base UOM rate
                outgoing_rate=None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta=meta,
            )
            intents.append(intent)

            logger.info(
                "✅ Created receipt intent - Item: %s, Base Qty: %s, Base Rate: %s, Warehouse: %s, Total: %s",
                item_id, base_qty, incoming_rate, wh_id, base_qty * incoming_rate
            )
        except Exception as e:
            logger.error("Receipt line %s failed: %s | %s", idx, e, ln)
            raise

    logger.info("Successfully built %d receipt intents", len(intents))
    return intents


def build_intents_for_return(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: Optional[int],   # header-level (optional; used as fallback)
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLE intents for a Purchase **Return** (stock going OUT).
    Each line must include:
      - item_id (int)
      - accepted_qty (Decimal)  -- positive or negative accepted; we will issue as negative stock
      - unit_price (Decimal >= 0)  -- base UOM rate
      - warehouse_id (int) optional at line; fallback to header if needed
      - uom_id (optional) and base_uom_id (optional)
      - doc_row_id (optional)

    Rules:
      - We convert quantity to base UOM (rate untouched), then force **negative** actual_qty (issue).
      - outgoing_rate is set (valuation on issue); incoming_rate None.
      - Warehouse is REQUIRED (strict).
    """
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        "Building return intents - Company: %s, Warehouse(header): %s, Doc: %s/%s",
        company_id, warehouse_id, doc_type_id, doc_id
    )

    for idx, ln in enumerate(lines):
        try:
            item_id = _coerce_int(ln["item_id"], field="item_id")
            qty_u = _to_decimal(ln.get("accepted_qty"), field="accepted_qty")
            unit_price = _to_decimal(ln.get("unit_price"), field="unit_price", default=Decimal("0"))
            doc_row_id = ln.get("doc_row_id")

            _validate_positive_decimal(unit_price, field="unit_price", allow_zero=True)

            # resolve warehouse strictly
            wh_id = _resolve_line_warehouse(warehouse_id, ln, idx)

            # convert quantity only; then force sign to negative (issue)
            uom_id = ln.get("uom_id")
            base_uom_id = ln.get("base_uom_id")
            base_qty_abs, base_uom_id = _to_base_qty_only(
                session=s, item_id=item_id, qty=abs(qty_u), uom_id=uom_id, maybe_base_uom_id=base_uom_id
            )
            actual_qty = -base_qty_abs

            meta = {
                "base_uom_id": int(base_uom_id),
                "txn_qty": str(qty_u),
                "source": "PurchaseReturn",
            }

            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=wh_id,
                posting_dt=posting_dt,
                actual_qty=actual_qty,        # return => negative issue
                incoming_rate=None,
                outgoing_rate=unit_price,     # base UOM rate
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta=meta,
            )
            intents.append(intent)

            logger.info(
                "✅ Created return intent - Item: %s, Base Qty: %s, Base Rate: %s, Warehouse: %s",
                item_id, actual_qty, unit_price, wh_id
            )
        except Exception as e:
            logger.error("Return line %s failed: %s | %s", idx, e, ln)
            raise

    logger.info("Successfully built %d return intents", len(intents))
    return intents


# ---------------------------------------------------------------------------
# Stock Entry (Transfer) — unchanged except strictness & logs
# ---------------------------------------------------------------------------

def build_intents_for_stock_entry(
    *,
    company_id: int,
    branch_id: int,
    source_warehouse_id: int,
    target_warehouse_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLE intents for a Stock Entry (Transfer):
      - OUT from source (negative qty, outgoing_rate)
      - IN  to target (positive qty, incoming_rate = same valuation)
    """
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        "Building stock entry intents - Company: %s, Source: %s → Target: %s",
        company_id, source_warehouse_id, target_warehouse_id
    )

    from app.application_stock.engine import selectors as SEL

    for idx, ln in enumerate(lines):
        try:
            item_id = _coerce_int(ln["item_id"], field="item_id")
            qty_u = _to_decimal(ln.get("qty"), field="qty")
            _validate_positive_decimal(qty_u, field="qty")

            uom_id = ln.get("uom_id")
            base_uom_id = ln.get("base_uom_id")
            doc_row_id = ln.get("doc_row_id")

            base_qty, base_uom_id = _to_base_qty_only(
                session=s, item_id=item_id, qty=qty_u, uom_id=uom_id, maybe_base_uom_id=base_uom_id
            )

            current_rate = SEL.get_current_valuation_rate(
                s, company_id, item_id, source_warehouse_id
            ) or Decimal("0")

            # OUT (source)
            intents.append(SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=source_warehouse_id,
                posting_dt=posting_dt,
                actual_qty=-base_qty,          # issue
                incoming_rate=None,
                outgoing_rate=current_rate,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={"base_uom_id": base_uom_id, "txn_qty": str(qty_u), "txn_type": "stock_entry_out"},
            ))

            # IN (target)
            intents.append(SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=target_warehouse_id,
                posting_dt=posting_dt,
                actual_qty=base_qty,           # receipt
                incoming_rate=current_rate,
                outgoing_rate=None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={"base_uom_id": base_uom_id, "txn_qty": str(qty_u), "txn_type": "stock_entry_in"},
            ))

            logger.info(
                "Created stock entry intents - Item: %s, Qty: %s, Rate: %s (src→tgt %s→%s)",
                item_id, base_qty, current_rate, source_warehouse_id, target_warehouse_id
            )

        except Exception as e:
            logger.error("StockEntry line %s failed: %s | %s", idx, e, ln)
            raise

    logger.info("Successfully built %d stock entry intents", len(intents))
    return intents
