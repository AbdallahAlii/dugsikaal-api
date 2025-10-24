# app/application_stock/reconciliation_schemas.py

from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

from app.application_stock.stock_models import StockReconciliationPurpose


class StockReconciliationItemBase(BaseModel):
    """Core fields for a stock reconciliation item line."""
    item_id: int
    warehouse_id: int
    quantity: Decimal = Field(..., gt=Decimal(0), description="Counted quantity.")
    valuation_rate: Optional[Decimal] = Field(None, ge=Decimal(0), description="Optional valuation rate for the difference.")

class StockReconciliationItemCreate(StockReconciliationItemBase):
    """Schema for creating a new item line."""
    pass

class StockReconciliationItemUpdate(StockReconciliationItemBase):
    """Schema for updating an item line."""
    id: Optional[int] = Field(None, description="Provide ID to update an existing line.")

class StockReconciliationItemOut(StockReconciliationItemBase):
    """Schema for representing an item line in an API response."""
    id: int
    current_qty: Optional[Decimal]
    current_valuation_rate: Optional[Decimal]
    qty_difference: Optional[Decimal]
    amount_difference: Optional[Decimal]

    class Config:
        from_attributes = True


class StockReconciliationCreate(BaseModel):
    """Payload for creating a new Stock Reconciliation."""
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    purpose: StockReconciliationPurpose = Field(default=StockReconciliationPurpose.STOCK_RECONCILIATION)
    posting_date: datetime
    code: Optional[str] = Field(None, description="Manual document code.")
    difference_account_id: Optional[int] = Field(None, description="Account for stock difference.")
    notes: Optional[str] = None
    items: List[StockReconciliationItemCreate]

    @field_validator("items")
    def _validate_non_empty_items(cls, v):
        if not v:
            raise ValueError("A stock reconciliation must have at least one item.")
        return v


class StockReconciliationUpdate(BaseModel):
    """Payload for updating a draft Stock Reconciliation."""
    posting_date: Optional[datetime] = None
    purpose: Optional[StockReconciliationPurpose] = None
    difference_account_id: Optional[int] = None
    notes: Optional[str] = None
    items: Optional[List[StockReconciliationItemUpdate]] = None


class StockReconciliationOut(BaseModel):
    """API response for Stock Reconciliation."""
    id: int
    code: str
    doc_status: str
    purpose: str
    posting_date: datetime
    notes: Optional[str]
    items: List[StockReconciliationItemOut]

    class Config:
        from_attributes = True


class StockReconciliationActionResponse(BaseModel):
    """Standard response for actions like submit or cancel."""
    id: int
    code: str
    doc_status: str