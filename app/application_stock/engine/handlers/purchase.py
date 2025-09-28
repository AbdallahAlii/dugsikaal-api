# # application_stock/engine/handlers/purchase.py

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Dict, Any

from app.application_stock.engine.types import SLEIntent, AdjustmentType

__all__ = ["build_intents_for_receipt"]


def _to_decimal(val: Any, *, field: str) -> Decimal:
    """
    Coerce value to Decimal safely. Raises ValueError on bad input.
    """
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError):
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")


def build_intents_for_receipt(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[Dict[str, Any]],  # each: {item_id, accepted_qty, unit_price, doc_row_id?}
) -> List[SLEIntent]:
    """
    Build Stock Ledger Entry intents for a Purchase Receipt.

    Each input line must include:
      - item_id (int)
      - accepted_qty (number > 0)
      - unit_price (number >= 0)
      - doc_row_id (optional, for traceability)

    Returns a list of SLEIntent (receipts only: positive actual_qty, incoming_rate=unit_price).
    """
    intents: List[SLEIntent] = []

    for ln in lines:
        item_id = int(ln["item_id"])
        qty = _to_decimal(ln.get("accepted_qty"), field="accepted_qty")
        price = _to_decimal(ln.get("unit_price"), field="unit_price")

        # Skip zero/negative accepted qty (caller usually filters these already)
        if qty <= 0:
            continue

        # Negative prices make no sense for receipts; guard softly (treat None/blank as 0, else must be >= 0)
        if price < 0:
            raise ValueError(f"unit_price must be >= 0 for item_id={item_id}, got {price}")

        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=qty,               # positive => receipt
                incoming_rate=price,          # valuation price per unit
                outgoing_rate=None,           # not used for receipts
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.NORMAL,
            )
        )

    return intents
