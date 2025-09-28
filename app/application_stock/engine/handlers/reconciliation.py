# stock/engine/handlers/reconciliation.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List
from app.application_stock.engine.types import SLEIntent, AdjustmentType


def build_intents_for_reconciliation(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[dict],  # {item_id, warehouse_id, delta_qty, revalue_delta(optional)}
) -> List[SLEIntent]:
    intents: List[SLEIntent] = []
    for ln in lines:
        delta_qty = Decimal(str(ln.get("delta_qty", "0")))
        revalue_delta = Decimal(str(ln.get("revalue_delta", "0")))
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=ln["item_id"],
                warehouse_id=ln["warehouse_id"],
                posting_dt=posting_dt,
                actual_qty=delta_qty,
                incoming_rate=None,
                outgoing_rate=None,
                stock_value_difference=revalue_delta,
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.RECONCILIATION,
            )
        )
    return intents
