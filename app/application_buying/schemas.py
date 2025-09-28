# app/application_buying/schemas.py

from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, field_validator, Field, model_validator


# --- Item Line Schemas ---

class PurchaseReceiptItemBase(BaseModel):
    """Core fields for a purchase receipt item line."""
    item_id: int
    uom_id: int
    received_qty: Decimal = Field(..., gt=Decimal(0), description="Quantity physically received.")
    accepted_qty: Decimal = Field(..., gt=Decimal(0), description="Quantity accepted after inspection.")
    unit_price: Optional[Decimal] = Field(None, gt=Decimal(0), description="Price per unit of measure.")
    remarks: Optional[str] = Field(None, max_length=255)

class PurchaseReceiptItemCreate(PurchaseReceiptItemBase):
    """Schema for creating a new item line within a new document."""
    pass

class PurchaseReceiptItemUpdate(PurchaseReceiptItemBase):
    """Schema for updating an item line. 'id' is used to match existing lines."""
    id: Optional[int] = Field(None, description="Provide ID to update an existing line, or omit for a new line.")

class PurchaseReceiptItemOut(PurchaseReceiptItemBase):
    """Schema for representing an item line in an API response."""
    id: int
    amount: Optional[Decimal]

    class Config:
        from_attributes = True

# --- Main Document Schemas ---

class PurchaseReceiptCreate(BaseModel):
    """Payload for creating a new Purchase Receipt."""
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    supplier_id: int
    warehouse_id: int
    posting_date: datetime
    code: Optional[str] = Field(None, description="Manual document code. If omitted, it will be auto-generated.")
    remarks: Optional[str] = None
    items: List[PurchaseReceiptItemCreate]

    @field_validator("items")
    def _validate_non_empty_items(cls, v):
        if not v:
            raise ValueError("A purchase receipt must have at least one item.")
        return v

class PurchaseReceiptUpdate(BaseModel):
    """Payload for updating a draft Purchase Receipt."""
    posting_date: Optional[datetime] = None
    supplier_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    remarks: Optional[str] = None
    # The full, final list of items must be sent. The service will sync changes.
    items: Optional[List[PurchaseReceiptItemUpdate]] = None

# --- API Response Schemas ---

class PurchaseReceiptMinimalOut(BaseModel):
    """A minimal summary of a purchase receipt for list views."""
    id: int
    code: str
    doc_status: str
    total_amount: Decimal

    class Config:
        from_attributes = True

class PurchaseReceiptFullOut(PurchaseReceiptMinimalOut):
    """The full purchase receipt document, including header and item lines."""
    company_id: int
    branch_id: int
    supplier_id: int
    warehouse_id: int
    posting_date: datetime
    remarks: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[PurchaseReceiptItemOut]

class PurchaseReceiptActionResponse(BaseModel):
    """Standard response for actions like submit or cancel."""
    id: int
    code: str
    doc_status: str


# ==============================================================================
# --- Purchase Invoice Schemas ---
# ==============================================================================

# --- Invoice Item Line Schemas ---

class PurchaseInvoiceItemBase(BaseModel):
    item_id: int
    uom_id: Optional[int] = Field(None, description="Optional. If omitted, item's base UOM will be used.")
    quantity: Decimal = Field(..., gt=Decimal(0))
    rate: Decimal = Field(..., ge=Decimal(0))
    remarks: Optional[str] = Field(None, max_length=255)

class PurchaseInvoiceItemCreate(PurchaseInvoiceItemBase):
    """Schema for creating an invoice item. Can optionally link to a receipt item."""
    receipt_item_id: Optional[int] = Field(None, description="Link to the source Purchase Receipt item.")

class PurchaseInvoiceItemUpdate(PurchaseInvoiceItemCreate):
    """Schema for updating an invoice item line. 'id' matches existing lines."""
    id: Optional[int] = Field(None, description="Provide ID to update, or omit for a new line.")

class PurchaseInvoiceItemOut(PurchaseInvoiceItemBase):
    id: int
    amount: Decimal
    receipt_item_id: Optional[int]

    class Config:
        from_attributes = True

# --- Main Invoice Document Schemas ---

class PurchaseInvoiceCreate(BaseModel):
    """Payload for creating a new Purchase Invoice."""
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    supplier_id: int
    posting_date: datetime
    due_date: Optional[datetime] = None
    code: Optional[str] = Field(None, description="Manual code. Auto-generated if omitted.")
    remarks: Optional[str] = None

    # --- Conditional Logic Fields ---
    receipt_id: Optional[int] = Field(None, description="ID of the Purchase Receipt to bill against.")
    update_stock: bool = Field(False, description="If True, this invoice also acts as a stock receipt.")
    warehouse_id: Optional[int] = Field(None, description="Required if 'update_stock' is True.")

    items: List[PurchaseInvoiceItemCreate]

    @field_validator("items")
    def _validate_non_empty_items(cls, v):
        if not v:
            raise ValueError("A purchase invoice must have at least one item.")
        return v

    @model_validator(mode='after')
    def _validate_creation_logic(self) -> 'PurchaseInvoiceCreate':
        """Ensures the payload is valid for one of the two creation modes."""
        if self.receipt_id:
            # Mode 1: Creating from a Purchase Receipt
            if self.update_stock:
                raise ValueError("Cannot set 'update_stock' to True when creating from a Purchase Receipt.")
            if self.warehouse_id:
                raise ValueError("Cannot provide 'warehouse_id' when creating from a Purchase Receipt.")
            for item in self.items:
                if not item.receipt_item_id:
                    raise ValueError("All items must link to a 'receipt_item_id' when creating from a receipt.")
        else:
            # Mode 2: Direct Purchase Invoice
            if self.update_stock and not self.warehouse_id:
                raise ValueError("'warehouse_id' is required when 'update_stock' is True.")
            if not self.update_stock and self.warehouse_id:
                raise ValueError("'warehouse_id' should only be provided when 'update_stock' is True.")
        return self

class PurchaseInvoiceUpdate(BaseModel):
    """Payload for updating a draft Purchase Invoice."""
    posting_date: Optional[datetime] = None
    supplier_id: Optional[int] = None
    warehouse_id: Optional[int] = None # Can only be changed if it was a direct stock invoice
    due_date: Optional[datetime] = None
    remarks: Optional[str] = None
    items: Optional[List[PurchaseInvoiceItemUpdate]] = None

# --- API Response Schemas ---

class PurchaseInvoiceMinimalOut(BaseModel):
    id: int
    code: str
    doc_status: str
    total_amount: Decimal
    balance_due: Decimal

    class Config:
        from_attributes = True

class PurchaseInvoiceFullOut(PurchaseInvoiceMinimalOut):
    company_id: int
    branch_id: int
    supplier_id: int
    warehouse_id: Optional[int]
    posting_date: datetime
    due_date: Optional[datetime]
    update_stock: bool
    remarks: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[PurchaseInvoiceItemOut]

class PurchaseInvoiceActionResponse(BaseModel):
    id: int
    code: str
    doc_status: str


class IdCode(BaseModel):
    id: int
    code: str