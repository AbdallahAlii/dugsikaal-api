# stock/engine/handlers/sales.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List
from app.application_stock.engine.types import SLEIntent, AdjustmentType


def build_intents_for_issue(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[dict],  # {item_id, qty, doc_row_id?}
) -> List[SLEIntent]:
    intents: List[SLEIntent] = []
    for ln in lines:
        qty = Decimal(str(ln["qty"]))
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=ln["item_id"],
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=-abs(qty),        # negative for issue
                incoming_rate=None,
                outgoing_rate=None,          # MA sets this in sle_writer from prev_rate
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.NORMAL,
            )
        )
    return intents
