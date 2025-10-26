from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Delivery Note (Create/Update)
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryNoteItemCreate(BaseModel):
    item_id: int
    uom_id: Optional[int] = None          # Optional (service lines won’t use it)
    warehouse_id: int                     # Required for stock lines
    delivered_qty: Decimal = Field(..., gt=Decimal(0))
    unit_price: Optional[Decimal] = Field(None, ge=Decimal(0))
    remarks: Optional[str] = Field(None, max_length=255)

class DeliveryNoteCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    posting_date: datetime
    code: Optional[str] = None
    remarks: Optional[str] = None
    items: List[DeliveryNoteItemCreate]

    @field_validator("items")
    def _non_empty(cls, v):
        if not v:
            raise ValueError("Delivery Note must have at least one item.")
        return v

class DeliveryNoteItemUpdate(BaseModel):
    id: Optional[int] = None
    item_id: int
    uom_id: Optional[int] = None
    warehouse_id: int
    delivered_qty: Decimal = Field(..., gt=Decimal(0))
    unit_price: Optional[Decimal] = Field(None, ge=Decimal(0))
    remarks: Optional[str] = Field(None, max_length=255)

class DeliveryNoteUpdate(BaseModel):
    posting_date: Optional[datetime] = None
    customer_id: Optional[int] = None
    remarks: Optional[str] = None
    items: Optional[List[DeliveryNoteItemUpdate]] = None  # full sync when provided

# ─────────────────────────────────────────────────────────────────────────────
# Sales Invoice (Create/Update)
# ─────────────────────────────────────────────────────────────────────────────

class SalesInvoiceItemCreate(BaseModel):
    item_id: int
    uom_id: Optional[int] = None                # Optional; not needed for service items
    quantity: Decimal
    rate: Decimal = Field(..., ge=Decimal(0))
    warehouse_id: Optional[int] = None          # Required only for stock lines if update_stock=True
    income_account_id: Optional[int] = None
    delivery_note_item_id: Optional[int] = None
    remarks: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def _qty_non_zero(self) -> "SalesInvoiceItemCreate":
        if self.quantity == 0:
            raise ValueError("Item quantity cannot be zero.")
        return self

class SalesInvoiceCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    posting_date: datetime

    debit_to_account_id: Optional[int] = None   # default to 1131 if missing
    vat_account_id: Optional[int] = None
    vat_rate: Optional[Decimal] = None
    vat_amount: Decimal = Field(default=Decimal("0"), ge=Decimal(0))

    due_date: Optional[datetime] = None
    code: Optional[str] = None
    remarks: Optional[str] = None

    # Mode:
    update_stock: bool = False                  # direct SI with stock movement
    delivery_note_id: Optional[int] = None      # finance-only against DN

    items: List[SalesInvoiceItemCreate]

    @field_validator("items")
    def _non_empty(cls, v):
        if not v:
            raise ValueError("Sales Invoice must have at least one item.")
        return v

    @model_validator(mode="after")
    def _validate_mode(self) -> "SalesInvoiceCreate":
        if self.delivery_note_id:
            if self.update_stock:
                raise ValueError("Cannot set 'update_stock' when invoicing against a Delivery Note.")
        if self.vat_amount and self.vat_amount > 0 and not self.vat_account_id:
            raise ValueError("VAT account is required when VAT amount > 0.")
        return self

class SalesInvoiceItemUpdate(SalesInvoiceItemCreate):
    id: Optional[int] = None

class SalesInvoiceUpdate(BaseModel):
    posting_date: Optional[datetime] = None
    customer_id: Optional[int] = None
    debit_to_account_id: Optional[int] = None
    vat_account_id: Optional[int] = None
    vat_rate: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = Field(None, ge=Decimal(0))
    due_date: Optional[datetime] = None
    remarks: Optional[str] = None
    items: Optional[List[SalesInvoiceItemUpdate]] = None  # full sync when provided

# ─────────────────────────────────────────────────────────────────────────────
# Credit Note (Return)
# ─────────────────────────────────────────────────────────────────────────────

class SalesCreditNoteItemCreate(BaseModel):
    original_item_id: int
    return_qty: Decimal = Field(..., gt=Decimal(0))
    remarks: Optional[str] = None

class SalesCreditNoteCreate(BaseModel):
    posting_date: datetime
    branch_id: Optional[int] = None
    code: Optional[str] = None
    remarks: Optional[str] = None
    update_stock: bool = True
    items: List[SalesCreditNoteItemCreate]

    @field_validator("items")
    def _non_empty_cn(cls, v):
        if not v:
            raise ValueError("Credit Note must have at least one item.")
        return v
