# stock/engine/valuation/moving_average.py
from __future__ import annotations
from decimal import Decimal


def apply_receipt(prev_qty: Decimal, prev_rate: Decimal, qty_in: Decimal, rate_in: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Returns (qty_after, rate_after, stock_value_diff)."""
    new_qty = prev_qty + qty_in
    prev_value = prev_qty * prev_rate
    delta_value = qty_in * rate_in
    new_rate = (prev_value + delta_value) / new_qty if new_qty != 0 else Decimal("0")
    return new_qty, new_rate, delta_value


def apply_issue(prev_qty: Decimal, prev_rate: Decimal, qty_out: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Returns (qty_after, rate_after, stock_value_diff). Outgoing uses prev_rate."""
    new_qty = prev_qty - qty_out
    delta_value = -(qty_out * prev_rate)
    # rate stays the same for MA on issue
    return new_qty, prev_rate, delta_value


def apply_zero_qty_revaluation(prev_qty: Decimal, prev_rate: Decimal, delta_value: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """
    LCV / pure valuation change. Returns (qty_after, rate_after, stock_value_diff).
    """
    if prev_qty == 0:
        # no stock → rate becomes 0; keep value diff as 0 to avoid divide-by-zero inconsistencies
        return prev_qty, Decimal("0"), Decimal("0")
    new_value = prev_qty * prev_rate + delta_value
    new_rate = new_value / prev_qty
    return prev_qty, new_rate, delta_value
