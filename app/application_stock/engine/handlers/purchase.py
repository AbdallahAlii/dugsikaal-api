
# app/application_stock/engine/handlers/purchase.py

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
from app.application_nventory.inventory_models import Item
from config.database import db

logger = logging.getLogger(__name__)

__all__ = [
    "build_intents_for_receipt",
    "build_intents_for_return",
    "build_intents_for_stock_entry"
]


def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    """Safely coerce value to Decimal with proper error handling."""
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
    """Safely coerce value to integer with proper error handling."""
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")

    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error(f"Integer conversion failed for field '{field}': {val!r} - {str(e)}")
        raise ValueError(f"Invalid integer for '{field}': {val!r}")


def _validate_positive_decimal(val: Decimal, *, field: str, allow_zero: bool = False) -> None:
    """Validate that decimal value is positive."""
    if val is None:
        raise ValueError(f"Missing required value for '{field}'")

    if allow_zero and val < 0:
        raise ValueError(f"'{field}' must be >= 0, got {val}")
    elif not allow_zero and val <= 0:
        raise ValueError(f"'{field}' must be > 0, got {val}")


def _get_base_uom_id(session: Session, item_id: int) -> int:
    """Safely fetch base UOM ID for an item."""
    try:
        item = session.get(Item, item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        if not item.base_uom_id:
            raise ValueError(f"Item {item_id} has no base UOM configured")
        return item.base_uom_id
    except Exception as e:
        logger.error(f"Failed to fetch base UOM for item {item_id}: {str(e)}")
        raise ValueError(f"Cannot determine base UOM for item {item_id}: {str(e)}")


def build_intents_for_receipt(
        *,
        company_id: int,
        branch_id: int,
        warehouse_id: int,
        posting_dt: datetime,
        doc_type_id: int,
        doc_id: int,
        lines: Iterable[Dict[str, Any]],
        session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build Stock Ledger Entry intents for a Purchase Receipt.

    ✅ YOUR BUSINESS LOGIC (User enters BASE UOM price):
      - User enters: 1 Box @ $2.00 (price is per PIECE, not per BOX)
      - Conversion: 1 Box = 12 Pieces
      - Result: 12 Pieces @ $2.00/Piece = $24.00 total

    IMPORTANT: The unit_price is ALWAYS per BASE UOM in your system!
    DO NOT convert the rate - only convert the quantity!
    """
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        f"Building receipt intents - Company: {company_id}, "
        f"Warehouse: {warehouse_id}, Doc: {doc_type_id}/{doc_id}"
    )

    for line_idx, line in enumerate(lines):
        try:
            # Extract and validate required fields
            item_id = _coerce_int(line["item_id"], field="item_id")
            qty_u = _to_decimal(line.get("accepted_qty"), field="accepted_qty")
            price_per_base = _to_decimal(line.get("unit_price"), field="unit_price")
            doc_row_id = line.get("doc_row_id")

            # Validate business rules
            _validate_positive_decimal(qty_u, field="accepted_qty")
            _validate_positive_decimal(price_per_base, field="unit_price", allow_zero=True)

            uom_id = line.get("uom_id")
            base_uom_id = line.get("base_uom_id")

            logger.info(
                f"Processing receipt line {line_idx} - Item: {item_id}, "
                f"Txn UOM: {uom_id}, Qty: {qty_u}, Base Price: {price_per_base}"
            )

            # Handle UOM conversion
            if uom_id is None:
                # No UOM specified → assume payload already in base UOM
                base_qty = qty_u
                base_rate = price_per_base

                # Still need base_uom_id for SLE
                if not base_uom_id:
                    base_uom_id = _get_base_uom_id(s, item_id)

                meta = {
                    "base_uom_id": int(base_uom_id),
                    "txn_qty": str(qty_u),
                }

                total_value = base_qty * base_rate
                logger.info(
                    f"No UOM conversion:\n"
                    f"  Qty: {base_qty} (base UOM)\n"
                    f"  Rate: ${base_rate}/unit (base UOM)\n"
                    f"  Total: ${total_value}"
                )
            else:
                # UOM conversion required
                uom_id = _coerce_int(uom_id, field="uom_id")

                # Ensure we have base UOM
                if not base_uom_id:
                    base_uom_id = _get_base_uom_id(s, item_id)
                else:
                    base_uom_id = _coerce_int(base_uom_id, field="base_uom_id")

                # Check if conversion is actually needed
                if uom_id == base_uom_id:
                    base_qty = qty_u
                    base_rate = price_per_base
                    meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                    }
                    logger.info(f"Same UOM - No conversion needed")
                else:
                    # ✅ CRITICAL: Only convert QUANTITY, NOT rate!
                    # The price is already in BASE UOM (per piece)
                    try:
                        # Convert quantity only
                        base_qty_float, factor_float = to_base_qty(
                            qty=qty_u,
                            item_id=item_id,
                            uom_id=uom_id,
                            base_uom_id=base_uom_id,
                            strict=True
                        )

                        base_qty = Decimal(str(base_qty_float))
                        factor_dec = Decimal(str(factor_float))

                        # ✅ KEEP THE RATE AS-IS (it's already per base UOM)
                        base_rate = price_per_base

                    except UOMFactorMissing as e:
                        raise ValueError(
                            f"Missing UOM conversion for item_id={item_id}, "
                            f"uom_id={uom_id}, base_uom_id={base_uom_id}"
                        ) from e

                    meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                        "txn_rate": str(price_per_base),  # This is base rate, not txn rate
                        "conversion_factor": str(factor_dec),
                    }

                    # Comprehensive logging
                    total_value = base_qty * base_rate
                    logger.info(
                        f"UOM Conversion Applied:\n"
                        f"  Transaction: {qty_u} UOM#{uom_id} @ ${price_per_base}/base_unit\n"
                        f"  Conversion Factor: {factor_dec}\n"
                        f"  Base Qty: {base_qty} UOM#{base_uom_id}\n"
                        f"  Base Rate: ${base_rate}/unit (NO CHANGE - already base price)\n"
                        f"  Total Value: {qty_u} × {factor_dec} × ${base_rate} = ${total_value}"
                    )

            # Create SLE Intent
            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=base_qty,
                incoming_rate=base_rate,  # ✅ Already in base UOM
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
                f"✅ Created receipt intent - Item: {item_id}, "
                f"Base Qty: {base_qty}, Base Rate: ${base_rate}, "
                f"Total: ${base_qty * base_rate}"
            )

        except Exception as e:
            logger.error(
                f"Failed to process receipt line {line_idx}: {str(e)}\n"
                f"Line data: {line}"
            )
            raise

    logger.info(f"Successfully built {len(intents)} receipt intents")
    return intents


def build_intents_for_return(
        *,
        company_id: int,
        branch_id: int,
        warehouse_id: int,
        posting_dt: datetime,
        doc_type_id: int,
        doc_id: int,
        lines: Iterable[Dict[str, Any]],
        session: Optional[Session] = None,
) -> List[SLEIntent]:
    """Build Stock Ledger Entry intents for a Purchase Return."""
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        f"Building return intents - Company: {company_id}, "
        f"Warehouse: {warehouse_id}, Doc: {doc_type_id}/{doc_id}"
    )

    for line_idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            qty_u = _to_decimal(line.get("accepted_qty"), field="accepted_qty")
            price_per_base = _to_decimal(
                line.get("unit_price"),
                field="unit_price",
                default=Decimal("0")
            )
            doc_row_id = line.get("doc_row_id")

            # Ensure return quantity is negative
            if qty_u > 0:
                logger.warning(
                    f"Return quantity should be negative for item {item_id}, "
                    f"got {qty_u}. Converting to negative."
                )
                qty_u = -abs(qty_u)
            elif qty_u == 0:
                logger.warning(f"Skipping zero quantity return for item {item_id}")
                continue

            _validate_positive_decimal(price_per_base, field="unit_price", allow_zero=True)

            uom_id = line.get("uom_id")
            base_uom_id = line.get("base_uom_id")

            # Handle UOM conversion
            if uom_id is None:
                base_qty = qty_u
                base_rate = price_per_base

                if not base_uom_id:
                    base_uom_id = _get_base_uom_id(s, item_id)

                meta = {
                    "base_uom_id": int(base_uom_id),
                    "txn_qty": str(qty_u),
                }
            else:
                uom_id = _coerce_int(uom_id, field="uom_id")

                if not base_uom_id:
                    base_uom_id = _get_base_uom_id(s, item_id)
                else:
                    base_uom_id = _coerce_int(base_uom_id, field="base_uom_id")

                if uom_id == base_uom_id:
                    base_qty = qty_u
                    base_rate = price_per_base
                    meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                    }
                else:
                    # Convert absolute values, then restore negative sign
                    try:
                        abs_base_qty_float, factor_float = to_base_qty(
                            qty=abs(qty_u),
                            item_id=item_id,
                            uom_id=uom_id,
                            base_uom_id=base_uom_id,
                            strict=True
                        )

                        base_qty = -Decimal(str(abs_base_qty_float))

                        # ✅ KEEP THE RATE AS-IS (already per base UOM)
                        base_rate = price_per_base

                    except UOMFactorMissing as e:
                        raise ValueError(
                            f"Missing UOM conversion for item_id={item_id}, "
                            f"uom_id={uom_id}, base_uom_id={base_uom_id}"
                        ) from e

                    meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                        "txn_rate": str(price_per_base),
                        "conversion_factor": str(Decimal(str(factor_float))),
                    }

            # Create return SLE Intent
            intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=base_qty,
                incoming_rate=None,
                outgoing_rate=base_rate,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta=meta,
            )

            intents.append(intent)

            logger.info(
                f"Created return intent - Item: {item_id}, "
                f"Base Qty: {base_qty}, Base Rate: {base_rate}"
            )

        except Exception as e:
            logger.error(
                f"Failed to process return line {line_idx}: {str(e)}\n"
                f"Line data: {line}"
            )
            raise

    logger.info(f"Successfully built {len(intents)} return intents")
    return intents


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
    """Build Stock Ledger Entry intents for a Stock Entry (Transfer)."""
    intents: List[SLEIntent] = []
    s = session or db.session

    logger.info(
        f"Building stock entry intents - Company: {company_id}, "
        f"Source: {source_warehouse_id} → Target: {target_warehouse_id}"
    )

    for line_idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            qty_u = _to_decimal(line.get("qty"), field="qty")
            doc_row_id = line.get("doc_row_id")

            _validate_positive_decimal(qty_u, field="qty")

            uom_id = line.get("uom_id")
            base_uom_id = line.get("base_uom_id")

            # Quantity conversion if UOM provided
            if uom_id is None or not base_uom_id:
                base_qty = qty_u

                if not base_uom_id:
                    base_uom_id = _get_base_uom_id(s, item_id)

                conversion_meta = {
                    "base_uom_id": int(base_uom_id),
                    "txn_qty": str(qty_u),
                }
            else:
                uom_id = _coerce_int(uom_id, field="uom_id")
                base_uom_id = _coerce_int(base_uom_id, field="base_uom_id")

                if uom_id != base_uom_id:
                    try:
                        base_qty_float, factor_float = to_base_qty(
                            qty=qty_u,
                            item_id=item_id,
                            uom_id=uom_id,
                            base_uom_id=base_uom_id,
                            strict=True
                        )
                        base_qty = Decimal(str(base_qty_float))
                    except UOMFactorMissing as e:
                        raise ValueError(
                            f"Missing UOM conversion for item_id={item_id}, "
                            f"uom_id={uom_id}, base_uom_id={base_uom_id}"
                        ) from e

                    conversion_meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                        "conversion_factor": str(Decimal(str(factor_float))),
                    }
                else:
                    base_qty = qty_u
                    conversion_meta = {
                        "base_uom_id": base_uom_id,
                        "txn_uom_id": uom_id,
                        "txn_qty": str(qty_u),
                    }

            # Get current valuation rate
            from app.application_stock.engine import selectors as SEL
            current_rate = SEL.get_current_valuation_rate(
                s, company_id, item_id, source_warehouse_id
            ) or Decimal("0")

            logger.info(f"Current valuation rate for item {item_id}: {current_rate}")

            # Source warehouse entry (negative)
            source_intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=source_warehouse_id,
                posting_dt=posting_dt,
                actual_qty=-base_qty,
                incoming_rate=None,
                outgoing_rate=current_rate,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={**conversion_meta, "txn_type": "stock_entry_out"},
            )

            # Target warehouse entry (positive)
            target_intent = SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=target_warehouse_id,
                posting_dt=posting_dt,
                actual_qty=base_qty,
                incoming_rate=current_rate,
                outgoing_rate=None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={**conversion_meta, "txn_type": "stock_entry_in"},
            )

            intents.extend([source_intent, target_intent])

            logger.info(
                f"Created stock entry intents - Item: {item_id}, "
                f"Qty: {base_qty}, Rate: {current_rate}"
            )

        except Exception as e:
            logger.error(
                f"Failed to process stock entry line {line_idx}: {str(e)}\n"
                f"Line data: {line}"
            )
            raise

    logger.info(f"Successfully built {len(intents)} stock entry intents")
    return intents