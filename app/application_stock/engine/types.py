# stock/engine/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class AdjustmentType(str, Enum):
    NORMAL = "NORMAL"
    LCV = "LCV"
    RECONCILIATION = "RECONCILIATION"
    REVERSAL = "REVERSAL"
    RETURN = "RETURN"
    TRANSFER = "TRANSFER"


@dataclass(frozen=True)
class SLEIntent:
    """
    Pure description of a single Stock Ledger Entry to be appended.

    IMPORTANT:
    - Quantities are in the item's BASE UOM (enforced by your doc handlers / validators).
    - No stock_uom_id here; your system assumes base UOM for ledger math.
    """
    # Context
    company_id: int
    branch_id: int

    # Movement
    item_id: int
    warehouse_id: int
    posting_dt: datetime
    actual_qty: Decimal  # +ve receipt, -ve issue, 0 for pure valuation

    # Valuation fields (optional, depending on move)
    incoming_rate: Optional[Decimal] = None
    outgoing_rate: Optional[Decimal] = None
    stock_value_difference: Decimal = Decimal("0")  # used when actual_qty == 0 (LCV, revaluation)

    # Source document linkage
    doc_type_id: int = 0
    doc_id: int = 0
    doc_row_id: Optional[int] = None

    # Metadata
    adjustment_type: AdjustmentType = AdjustmentType.NORMAL
    meta: Dict[str, Any] = field(default_factory=dict)
