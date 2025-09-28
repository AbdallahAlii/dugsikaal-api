# stock/engine/handlers/returns.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Optional

from app.application_stock.engine.types import SLEIntent, AdjustmentType


def build_intents_for_purchase_return(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[dict],  # {item_id, qty, original_receipt_rate, doc_row_id?}
) -> List[SLEIntent]:
    intents: List[SLEIntent] = []
    for ln in lines:
        qty = Decimal(str(ln["qty"]))
        rate = Decimal(str(ln["original_receipt_rate"]))
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=ln["item_id"],
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=-abs(qty),
                incoming_rate=None,
                outgoing_rate=rate,  # value out at original receipt rate
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.RETURN,
            )
        )
    return intents


def build_intents_for_sales_return(
    *,
    company_id: int,
    branch_id: int,
    warehouse_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    lines: Iterable[dict],  # {item_id, qty, original_issue_cost, doc_row_id?}
) -> List[SLEIntent]:
    intents: List[SLEIntent] = []
    for ln in lines:
        qty = Decimal(str(ln["qty"]))
        rate = Decimal(str(ln["original_issue_cost"]))
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=ln["item_id"],
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=abs(qty),
                incoming_rate=rate,  # value in at original issue cost
                outgoing_rate=None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=ln.get("doc_row_id"),
                adjustment_type=AdjustmentType.RETURN,
            )
        )
    return intents
