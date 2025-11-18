
# app/application_selling/schemas.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


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
    uom_id: Optional[int] = None
    quantity: Decimal
    rate: Decimal = Field(..., ge=Decimal(0))
    warehouse_id: Optional[int] = None
    income_account_id: Optional[int] = None
    delivery_note_item_id: Optional[int] = None
    # NEW: needed for returns to know which original row this line belongs to
    return_against_item_id: Optional[int] = None
    remarks: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def _qty_non_zero(self) -> "SalesInvoiceItemCreate":
        if self.quantity == 0:
            raise ValueError("Item quantity cannot be zero.")
        return self


class SalesInvoiceCreate(BaseModel):
    # Pydantic v2: forbid unknown keys so bad payloads are rejected up front
    model_config = ConfigDict(extra="forbid")

    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    posting_date: datetime
    is_return: bool = False
    return_against_id: Optional[int] = None
    debit_to_account_id: Optional[int] = None
    vat_account_id: Optional[int] = None
    vat_rate: Optional[Decimal] = None
    vat_amount: Decimal = Field(default=Decimal("0"), ge=Decimal(0))  # ignored when vat_rate is provided

    # write-off (validation only; not stored in DB)
    write_off_amount: Decimal = Field(default=Decimal("0"), ge=Decimal(0))

    # payment-at-create support
    # NOTE: allow negative for returns; business rules handled in service
    paid_amount: Decimal = Field(default=Decimal("0"))
    mode_of_payment_id: Optional[int] = None
    cash_bank_account_id: Optional[int] = None

    due_date: Optional[datetime] = None
    code: Optional[str] = None
    remarks: Optional[str] = None
    update_stock: bool = False
    delivery_note_id: Optional[int] = None
    items: List[SalesInvoiceItemCreate]

    @field_validator("items")
    def _non_empty(cls, v):
        if not v:
            raise ValueError("Sales Invoice must have at least one item.")
        return v

    @model_validator(mode="after")
    def _validate_mode(self) -> "SalesInvoiceCreate":
        if self.delivery_note_id and self.update_stock:
            raise ValueError("Cannot set 'Update Stock' when invoicing against a Delivery Note.")
        if self.vat_amount and self.vat_amount > 0 and not self.vat_account_id and self.vat_rate is None:
            raise ValueError("Add a VAT account when VAT amount > 0.")
        if self.is_return and not self.return_against_id:
            raise ValueError("Return Against is required for a return Sales Invoice.")
        return self


class SalesInvoiceItemUpdate(SalesInvoiceItemCreate):
    id: Optional[int] = None


class SalesInvoiceUpdate(BaseModel):
    # still reject unknown keys (prevents silent bugs)
    model_config = ConfigDict(extra="forbid")

    posting_date: Optional[datetime] = None
    customer_id: Optional[int] = None
    debit_to_account_id: Optional[int] = None
    vat_account_id: Optional[int] = None
    vat_rate: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = Field(None, ge=Decimal(0))
    write_off_amount: Optional[Decimal] = Field(default=None, ge=Decimal(0))

    # payment edits (draft only) — can be negative for returns
    paid_amount: Optional[Decimal] = Field(None)
    mode_of_payment_id: Optional[int] = None
    cash_bank_account_id: Optional[int] = None

    # return support (immutable once created, but allow idempotent PATCH if same)
    is_return: Optional[bool] = None
    return_against_id: Optional[int] = None
    due_date: Optional[datetime] = None
    remarks: Optional[str] = None
    items: Optional[List[SalesInvoiceItemUpdate]] = None

    # allow toggling update_stock in draft
    update_stock: Optional[bool] = None


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
