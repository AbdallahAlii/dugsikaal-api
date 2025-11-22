# app/application_stock/schemas/stock_entry_schemas.py
from __future__ import annotations

from typing import Optional, List
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, condecimal, model_validator

from app.application_stock.stock_models import DocStatusEnum, StockEntryType


# ---------- Item Schemas ----------

class StockEntryItemBase(BaseModel):
    item_id: int
    uom_id: int
    quantity: condecimal(gt=0, decimal_places=6)          # always positive in UI
    rate: condecimal(ge=0, decimal_places=6) = Decimal("0")
    source_warehouse_id: Optional[int] = None
    target_warehouse_id: Optional[int] = None


class StockEntryItemCreate(StockEntryItemBase):
    pass


class StockEntryItemUpdate(BaseModel):
    """
    Partial update for items (used on PATCH).
    """
    id: Optional[int] = None
    item_id: Optional[int] = None
    uom_id: Optional[int] = None
    quantity: Optional[condecimal(gt=0, decimal_places=6)] = None
    rate: Optional[condecimal(ge=0, decimal_places=6)] = None
    source_warehouse_id: Optional[int] = None
    target_warehouse_id: Optional[int] = None


class StockEntryItemOut(StockEntryItemBase):
    id: int
    stock_entry_id: int
    amount: condecimal(ge=0, decimal_places=6)
    created_at: date
    updated_at: date

    class Config:
        from_attributes = True


# ---------- Document Schemas ----------

class StockEntryCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    code: Optional[str] = Field(None)
    posting_date: date
    stock_entry_type: StockEntryType
    difference_account_id: Optional[int] = None
    items: List[StockEntryItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_warehouse_sides(self) -> "StockEntryCreate":
        t = self.stock_entry_type
        for ln in self.items:
            if t == StockEntryType.MATERIAL_RECEIPT:
                if not ln.target_warehouse_id or ln.source_warehouse_id:
                    raise ValueError(
                        "Material Receipt: target_warehouse_id is required and source_warehouse_id must be empty."
                    )
            elif t == StockEntryType.MATERIAL_ISSUE:
                if not ln.source_warehouse_id or ln.target_warehouse_id:
                    raise ValueError(
                        "Material Issue: source_warehouse_id is required and target_warehouse_id must be empty."
                    )
            elif t == StockEntryType.MATERIAL_TRANSFER:
                if not ln.source_warehouse_id or not ln.target_warehouse_id:
                    raise ValueError(
                        "Material Transfer: both source_warehouse_id and target_warehouse_id are required."
                    )
                if ln.source_warehouse_id == ln.target_warehouse_id:
                    raise ValueError(
                        "Material Transfer: source and target warehouses must be different."
                    )
        return self


class StockEntryUpdate(BaseModel):
    posting_date: Optional[date] = None
    stock_entry_type: Optional[StockEntryType] = None
    difference_account_id: Optional[int] = None
    items: Optional[List[StockEntryItemUpdate]] = None


class StockEntryOut(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
    company_id: int
    branch_id: int
    posting_date: date
    stock_entry_type: StockEntryType
    difference_account_id: Optional[int] = None
    created_at: date
    updated_at: date
    items: List[StockEntryItemOut]

    class Config:
        from_attributes = True


class StockEntryActionResponse(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
