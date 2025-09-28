# stock/engine/handlers/transfer.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List

from app.application_stock.engine.types import SLEIntent, AdjustmentType


def build_intents_for_transfer(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[dict],  # {item_id, qty, source_warehouse_id, target_warehouse_id, doc_row_id?}
) -> List[SLEIntent]:
    intents: List[SLEIntent] = []
    for ln in lines:
        qty = Decimal(str(ln["qty"]))
        item_id = ln["item_id"]
        src = ln["source_warehouse_id"]
        tgt = ln["target_warehouse_id"]

        # Out of source
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=src,
                posting_dt=posting_dt,
                actual_qty=-abs(qty),
                incoming_rate=None,
                outgoing_rate=None,  # MA: engine uses prev rate
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.TRANSFER,
            )
        )
        # Into target at same cost (MA will take the outgoing_rate of source as incoming)
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=tgt,
                posting_dt=posting_dt,
                actual_qty=abs(qty),
                incoming_rate=None,  # will be set during replay or using last source rate if you choose to pass it
                outgoing_rate=None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.TRANSFER,
            )
        )
    return intents
