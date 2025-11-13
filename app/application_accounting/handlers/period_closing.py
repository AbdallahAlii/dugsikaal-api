# app/application_accounting/handlers/period_closing.py
from __future__ import annotations
from typing import Dict

def build_gl_context_for_period_closing(*, profit_amount: float, loss_amount: float) -> Dict:
    """
    No validations here (kept in service). Just shapes the payload the PERIOD_CLOSING
    template expects. Amounts must be positive numbers.
    """
    return {
        "PROFIT_AMOUNT": float(max(profit_amount or 0.0, 0.0)),
        "LOSS_AMOUNT": float(max(loss_amount or 0.0, 0.0)),
    }
