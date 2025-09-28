# stock/engine/handlers/landed_cost.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List, Dict

from app.application_stock.engine.types import SLEIntent, AdjustmentType


def build_intents_for_lcv(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    allocations: Iterable[dict],  # {item_id, warehouse_id, receipt_doc_type_id, receipt_doc_id, delta_value, doc_row_id?}
) -> List[SLEIntent]:
    """
    Design: we'll treat LCV as a value-only change (qty=0) so we can keep a clear audit
    and then schedule a repost from earliest affected receipt's posting_dt.
    """
    intents: List[SLEIntent] = []
    for row in allocations:
        delta = Decimal(str(row["delta_value"]))
        intents.append(
            SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=row["item_id"],
                warehouse_id=row["warehouse_id"],
                posting_dt=posting_dt,
                actual_qty=Decimal("0"),
                incoming_rate=None,
                outgoing_rate=None,
                stock_value_difference=delta,
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=row.get("doc_row_id"),
                adjustment_type=AdjustmentType.LCV,
                meta={
                    "applies_to_doc_type_id": row["receipt_doc_type_id"],
                    "applies_to_doc_id": row["receipt_doc_id"],
                },
            )
        )
    return intents
