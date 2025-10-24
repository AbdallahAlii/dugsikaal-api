from decimal import Decimal
from app.application_stock.engine.types import SLEIntent, AdjustmentType

def create_reconciliation_intent(
    company_id: int,
    branch_id: int,
    warehouse_id: int,
    item_id: int,
    counted_qty_base: Decimal,
    doc_type_id: int,
    doc_id: int,
    doc_row_id: int,
    valuation_rate_used: Decimal,
    posting_dt=None,
) -> SLEIntent:
    """
    Creates a SLEIntent for a reconciliation adjustment.
    Automatically sets counted_qty_base and valuation_rate_used in meta.
    """
    intent = SLEIntent(
        company_id=company_id,
        branch_id=branch_id,
        warehouse_id=warehouse_id,
        item_id=item_id,
        actual_qty=counted_qty_base,  # ignored for reconciliation
        doc_type_id=doc_type_id,
        doc_id=doc_id,
        doc_row_id=doc_row_id,
        adjustment_type=AdjustmentType.RECONCILIATION,
        posting_dt=posting_dt,
        meta={
            "counted_qty_base": str(counted_qty_base),
            "valuation_rate_used": str(valuation_rate_used),
        }
    )
    return intent
