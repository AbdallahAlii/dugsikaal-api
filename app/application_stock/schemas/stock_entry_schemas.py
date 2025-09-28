from __future__ import annotations
from typing import Optional, List, Literal
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, condecimal, model_validator
from app.application_stock.stock_models import DocStatusEnum, StockEntryType


# ---------- Item Schemas ----------

class StockEntryItemBase(BaseModel):
    item_id: int
    uom_id: int
    quantity: condecimal(gt=0, decimal_places=6)  # always positive in the UI
    rate: condecimal(ge=0, decimal_places=6) = Decimal("0")
    source_warehouse_id: Optional[int] = None
    target_warehouse_id: Optional[int] = None


class StockEntryItemCreate(StockEntryItemBase):
    pass


class StockEntryItemUpdate(StockEntryItemBase):
    id: Optional[int] = None
    item_id: Optional[int] = None
    uom_id: Optional[int] = None
    quantity: Optional[condecimal(gt=0, decimal_places=6)] = None
    rate: Optional[condecimal(ge=0, decimal_places=6)] = None


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
    items: List[StockEntryItemCreate] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_warehouse_sides(self) -> "StockEntryCreate":
        t = self.stock_entry_type
        for ln in self.items:
            if t == StockEntryType.MATERIAL_RECEIPT:
                if not ln.target_warehouse_id or ln.source_warehouse_id:
                    raise ValueError("Receipt requires target_warehouse_id and no source_warehouse_id.")
            elif t == StockEntryType.MATERIAL_ISSUE:
                if not ln.source_warehouse_id or ln.target_warehouse_id:
                    raise ValueError("Issue requires source_warehouse_id and no target_warehouse_id.")
            elif t == StockEntryType.MATERIAL_TRANSFER:
                if not ln.source_warehouse_id or not ln.target_warehouse_id:
                    raise ValueError("Transfer requires both source_warehouse_id and target_warehouse_id.")
                if ln.source_warehouse_id == ln.target_warehouse_id:
                    raise ValueError("Transfer requires source and target warehouses to be different.")
        return self


class StockEntryUpdate(BaseModel):
    posting_date: Optional[date] = None
    stock_entry_type: Optional[StockEntryType] = None
    items: Optional[List[StockEntryItemUpdate]] = None


class StockEntryOut(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
    company_id: int
    branch_id: int
    posting_date: date
    stock_entry_type: StockEntryType
    created_at: date
    updated_at: date
    items: List[StockEntryItemOut]

    class Config:
        from_attributes = True


class StockEntryActionResponse(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
