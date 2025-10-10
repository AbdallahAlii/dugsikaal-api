# app/application_nventory/services/uom_math.py
from __future__ import annotations
from typing import Optional, Tuple, Literal
from decimal import Decimal
from app.application_nventory.services.uom_cache import get_uom_factor

class UOMFactorMissing(Exception):
    pass

def resolve_factor(*, item_id: int, uom_id: int, base_uom_id: int, strict: bool = True) -> float:
    f = get_uom_factor(item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id)
    if f is None:
        if strict:
            raise UOMFactorMissing(f"Missing UOM conversion for item={item_id} uom={uom_id}")
        return 1.0
    return float(f)

def to_base_qty(*, qty: float | Decimal, item_id: int, uom_id: int, base_uom_id: int, strict: bool = True) -> Tuple[float, float]:
    f = resolve_factor(item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=strict)
    return float(qty) * f, f

def from_base_qty(*, base_qty: float | Decimal, item_id: int, uom_id: int, base_uom_id: int, strict: bool = True) -> Tuple[float, float]:
    f = resolve_factor(item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=strict)
    return float(base_qty) / f, f

# NEW: rate conversion helpers
def rate_to_base(*, price_per_uom: float | Decimal, factor: float) -> float:
    """
    Convert a unit price quoted per (transaction UOM) into a price per (Base UOM).
    base_rate = price_per_uom / factor
    """
    return float(Decimal(str(price_per_uom)) / Decimal(str(factor)))

def rate_from_base(*, price_per_base: float | Decimal, factor: float) -> float:
    """
    Convert a unit price quoted per (Base UOM) into a price per (transaction UOM).
    txn_rate = price_per_base * factor
    """
    return float(Decimal(str(price_per_base)) * Decimal(str(factor)))

def stock_delta_for_txn(
    *, txn_type: Literal["receipt", "issue"], qty: float | Decimal,
    item_id: int, uom_id: int, base_uom_id: int, strict: bool = True
) -> Tuple[float, float]:
    base_qty, f = to_base_qty(qty=qty, item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=strict)
    sign = 1.0 if txn_type == "receipt" else -1.0
    return sign * base_qty, f
