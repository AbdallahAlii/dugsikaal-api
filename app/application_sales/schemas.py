# app/application_sales/schemas.py

from __future__ import annotations
from typing import Optional, List
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, condecimal, model_validator, field_validator
from app.application_stock.stock_models import DocStatusEnum


# --- Sales Quotation Schemas ---

class SalesQuotationItemBase(BaseModel):
    item_id: int
    quantity: condecimal(ge=0, decimal_places=6)
    uom_id: int
    rate: condecimal(ge=0, decimal_places=2)
    remarks: Optional[str] = None


class SalesQuotationItemCreate(SalesQuotationItemBase):
    pass


class SalesQuotationItemUpdate(SalesQuotationItemBase):
    id: Optional[int] = None
    quantity: Optional[condecimal(ge=0, decimal_places=6)] = None
    uom_id: Optional[int] = None
    rate: Optional[condecimal(ge=0, decimal_places=2)] = None


class SalesQuotationItemOut(SalesQuotationItemBase):
    id: int
    quotation_id: int
    amount: condecimal(ge=0, decimal_places=2)
    created_at: date
    updated_at: date

    class Config:
        from_attributes = True


class SalesQuotationCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    posting_date: date
    code: Optional[str] = Field(None)
    remarks: Optional[str] = None
    items: List[SalesQuotationItemCreate] = Field(..., min_length=1)


class SalesQuotationUpdate(BaseModel):
    customer_id: Optional[int] = None
    posting_date: Optional[date] = None
    remarks: Optional[str] = None
    items: Optional[List[SalesQuotationItemUpdate]] = None


class SalesQuotationOut(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
    company_id: int
    branch_id: int
    customer_id: int
    posting_date: date
    remarks: Optional[str]
    total_amount: condecimal(ge=0, decimal_places=2)
    created_at: date
    updated_at: date
    items: List[SalesQuotationItemOut]

    class Config:
        from_attributes = True


class SalesQuotationActionResponse(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum


# ==============================================================================
# --- Sales Delivery Note Schemas ---
# ==============================================================================

class SalesDeliveryNoteItemBase(BaseModel):
    item_id: int
    delivered_qty: condecimal(ge=0, decimal_places=6)
    uom_id: int
    unit_price: condecimal(ge=0, decimal_places=2)
    remarks: Optional[str] = None


class SalesDeliveryNoteItemCreate(SalesDeliveryNoteItemBase):
    pass


class SalesDeliveryNoteItemUpdate(SalesDeliveryNoteItemBase):
    id: Optional[int] = None
    delivered_qty: Optional[condecimal(ge=0, decimal_places=6)] = None
    unit_price: Optional[condecimal(ge=0, decimal_places=2)] = None


class SalesDeliveryNoteItemOut(SalesDeliveryNoteItemBase):
    id: int
    delivery_note_id: int
    amount: condecimal(ge=0, decimal_places=2)
    created_at: date
    updated_at: date

    class Config:
        from_attributes = True


class SalesDeliveryNoteCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    warehouse_id: int
    posting_date: date
    code: Optional[str] = Field(None)
    remarks: Optional[str] = None
    items: List[SalesDeliveryNoteItemCreate] = Field(..., min_length=1)


class SalesDeliveryNoteUpdate(BaseModel):
    customer_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    posting_date: Optional[date] = None
    remarks: Optional[str] = None
    items: Optional[List[SalesDeliveryNoteItemUpdate]] = None


class SalesDeliveryNoteOut(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
    company_id: int
    branch_id: int
    customer_id: int
    warehouse_id: int
    posting_date: date
    remarks: Optional[str]
    total_amount: condecimal(ge=0, decimal_places=2)
    created_at: date
    updated_at: date
    items: List[SalesDeliveryNoteItemOut]

    class Config:
        from_attributes = True


class SalesDeliveryNoteActionResponse(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum


# ==============================================================================
# --- Sales Invoice Schemas ---
# ==============================================================================

class SalesInvoiceItemBase(BaseModel):
    item_id: int
    quantity: condecimal(ge=0, decimal_places=6)
    uom_id: int
    rate: condecimal(ge=0, decimal_places=2)
    remarks: Optional[str] = None
    delivery_note_item_id: Optional[int] = None


class SalesInvoiceItemCreate(SalesInvoiceItemBase):
    pass


class SalesInvoiceItemUpdate(SalesInvoiceItemBase):
    id: Optional[int] = None
    quantity: Optional[condecimal(ge=0, decimal_places=6)] = None
    uom_id: Optional[int] = None
    rate: Optional[condecimal(ge=0, decimal_places=2)] = None
    delivery_note_item_id: Optional[int] = None


class SalesInvoiceItemOut(SalesInvoiceItemBase):
    id: int
    invoice_id: int
    delivery_note_item_id: Optional[int] = None
    amount: condecimal(ge=0, decimal_places=2)
    created_at: date
    updated_at: date

    class Config:
        from_attributes = True


class SalesInvoiceCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    customer_id: int
    posting_date: date
    code: Optional[str] = Field(None)
    due_date: Optional[date] = None
    remarks: Optional[str] = None

    # Conditional logic fields
    warehouse_id: Optional[int] = Field(None)
    delivery_note_id: Optional[int] = Field(None)
    update_stock: bool = Field(False)

    items: List[SalesInvoiceItemCreate] = Field(..., min_length=1)

    @model_validator(mode='after')
    def _validate_creation_logic(self) -> 'SalesInvoiceCreate':
        if self.delivery_note_id:
            if self.update_stock:
                raise ValueError("Cannot set 'update_stock' to True when creating from a Sales Delivery Note.")
            if self.warehouse_id:
                raise ValueError("Cannot provide 'warehouse_id' when creating from a Sales Delivery Note.")
        else:
            if self.update_stock and not self.warehouse_id:
                raise ValueError("'warehouse_id' is required when 'update_stock' is True.")
            if not self.update_stock and self.warehouse_id:
                raise ValueError("'warehouse_id' should only be provided when 'update_stock' is True.")
        return self


class SalesInvoiceUpdate(BaseModel):
    customer_id: Optional[int] = None
    posting_date: Optional[date] = None
    due_date: Optional[date] = None
    remarks: Optional[str] = None
    items: Optional[List[SalesInvoiceItemUpdate]] = None


class SalesInvoiceOut(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum
    company_id: int
    branch_id: int
    customer_id: int
    warehouse_id: Optional[int] = None
    posting_date: date
    due_date: Optional[date] = None
    update_stock: bool
    remarks: Optional[str]
    total_amount: condecimal(ge=0, decimal_places=2)
    balance_due: condecimal(ge=0, decimal_places=2)
    delivery_note_id: Optional[int] = None
    created_at: date
    updated_at: date
    items: List[SalesInvoiceItemOut]

    class Config:
        from_attributes = True


class SalesInvoiceActionResponse(BaseModel):
    id: int
    code: str
    doc_status: DocStatusEnum