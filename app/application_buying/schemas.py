# # app/application_buying/schemas.py

from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator


# ──────────────────────────────────────────────────────────────────────────────
# PURCHASE RECEIPT
# ──────────────────────────────────────────────────────────────────────────────

class PurchaseReceiptItemCreate(BaseModel):
    item_id: int
    uom_id: Optional[int] = None
    # Positive for normal receipt; Negative for return
    received_qty: Decimal
    accepted_qty: Decimal
    unit_price: Optional[Decimal] = Field(None, ge=Decimal("0"))
    remarks: Optional[str] = Field(None, max_length=255)
    # Optional per-line warehouse; will be auto-filled from header if missing
    warehouse_id: Optional[int] = None
    # For returns (negative qty) – must reference original PR item
    return_against_item_id: Optional[int] = None


class PurchaseReceiptItemUpdate(PurchaseReceiptItemCreate):
    id: Optional[int] = None


class PurchaseReceiptCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    supplier_id: int
    posting_date: datetime
    code: Optional[str] = None
    remarks: Optional[str] = None
    is_return: bool = False
    # Convenience default — nullable header
    warehouse_id: Optional[int] = None
    # Required when is_return = True
    return_against_id: Optional[int] = None
    items: List[PurchaseReceiptItemCreate]

    @field_validator("items")
    def _require_items(cls, v):
        if not v:
            raise ValueError("A Purchase Receipt requires at least one item.")
        return v

    @model_validator(mode="after")
    def _return_rules(self):
        if self.is_return:
            if not self.return_against_id:
                raise ValueError("return_against_id is required for a return Purchase Receipt.")
            # All qty must be negative
            for it in self.items:
                if it.accepted_qty >= 0 or it.received_qty >= 0:
                    raise ValueError("Return Receipt items must have negative quantities.")
                if it.return_against_item_id is None:
                    raise ValueError("Return Receipt requires return_against_item_id on each item.")
        else:
            # All qty must be positive for normal receipt
            for it in self.items:
                if it.accepted_qty <= 0 or it.received_qty <= 0:
                    raise ValueError("Normal Receipt items must have positive quantities.")
        return self


class PurchaseReceiptUpdate(BaseModel):
    posting_date: Optional[datetime] = None
    supplier_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    remarks: Optional[str] = None
    items: Optional[List[PurchaseReceiptItemUpdate]] = None


class PurchaseReceiptMinimalOut(BaseModel):
    id: int
    code: str
    doc_status: str
    total_amount: Decimal

    class Config:
        from_attributes = True


class PurchaseReceiptFullOut(PurchaseReceiptMinimalOut):
    company_id: int
    branch_id: int
    supplier_id: int
    posting_date: datetime
    is_return: bool
    warehouse_id: Optional[int]
    remarks: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[dict]  # Keep simple; your response serializers can shape it.


# ──────────────────────────────────────────────────────────────────────────────
# PURCHASE INVOICE (finance + optional stock)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseInvoiceItemCreate(BaseModel):
    item_id: int
    uom_id: Optional[int] = None
    quantity: Decimal                  # +ve = normal PI, -ve = return
    rate: Decimal = Field(..., ge=Decimal("0"))
    remarks: Optional[str] = Field(None, max_length=255)

    # Optional link to PR item if against receipt (normal PIs only)
    receipt_item_id: Optional[int] = None

    # Optional per-line warehouse (required before submit when update_stock=True)
    warehouse_id: Optional[int] = None

    # For returns – must reference original PurchaseInvoiceItem.id
    return_against_item_id: Optional[int] = None


class PurchaseInvoiceItemUpdate(PurchaseInvoiceItemCreate):
    id: Optional[int] = None

class PurchaseInvoiceCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    supplier_id: int
    posting_date: datetime
    code: Optional[str] = None
    remarks: Optional[str] = None

    # finance fields
    payable_account_id: Optional[int] = None
    due_date: Optional[datetime] = None

    # optional immediate payment (can be negative for returns)
    paid_amount: Decimal = Field(default=Decimal("0"))
    mode_of_payment_id: Optional[int] = None
    cash_bank_account_id: Optional[int] = None

    # stock flags
    update_stock: bool = False
    # convenience header warehouse; copied to lines if missing (only enforced when update_stock=True)
    warehouse_id: Optional[int] = None

    # Return controls
    is_return: bool = False
    return_against_id: Optional[int] = None  # required when is_return=True

    # GRNI clearing (normal PIs only)
    receipt_id: Optional[int] = None

    items: List[PurchaseInvoiceItemCreate]

    @field_validator("items")
    def _require_items(cls, v):
        if not v:
            raise ValueError("A Purchase Invoice requires at least one item.")
        return v

    @model_validator(mode="after")
    def _validate_modes(self):
        # basic return requirement
        if self.is_return and not self.return_against_id:
            raise ValueError("return_against_id is required for a return Purchase Invoice.")

        # Return PI should not be linked to receipt (ERPNext-style: return against Invoice)
        if self.is_return and self.receipt_id:
            raise ValueError("Return Purchase Invoice cannot reference receipt_id; use return_against_id instead.")

        # GRNI rule: billing against PR cannot update stock from PI
        if self.receipt_id and self.update_stock:
            raise ValueError("When billing against Purchase Receipt, update_stock must be False.")

        # Direction: normal = positive, return = negative
        for it in self.items:
            if self.is_return:
                if it.quantity >= 0:
                    raise ValueError("Return Invoice items must have negative quantities.")
            else:
                if it.quantity <= 0:
                    raise ValueError("Normal Invoice items must have positive quantities.")

        return self


class PurchaseInvoiceUpdate(BaseModel):
    posting_date: Optional[datetime] = None
    supplier_id: Optional[int] = None
    warehouse_id: Optional[int] = None  # header convenience default
    due_date: Optional[datetime] = None
    remarks: Optional[str] = None
    update_stock: Optional[bool] = None

    # payment edits (draft only)
    paid_amount: Optional[Decimal] = None
    mode_of_payment_id: Optional[int] = None
    cash_bank_account_id: Optional[int] = None

    # full sync when provided
    items: Optional[List[PurchaseInvoiceItemUpdate]] = None


class PurchaseInvoiceMinimalOut(BaseModel):
    id: int
    code: str
    doc_status: str
    total_amount: Decimal
    outstanding_amount: Decimal

    class Config:
        from_attributes = True


class PurchaseInvoiceFullOut(PurchaseInvoiceMinimalOut):
    company_id: int
    branch_id: int
    supplier_id: int
    posting_date: datetime
    is_return: bool
    update_stock: bool
    warehouse_id: Optional[int]
    remarks: Optional[str]
    created_at: datetime
    updated_at: datetime
    items: List[dict]
