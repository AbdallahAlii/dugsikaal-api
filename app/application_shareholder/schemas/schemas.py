# app/application_shareholder/schemas/schemas.py
from __future__ import annotations

from typing import Optional, List
from datetime import datetime

from pydantic import BaseModel, Field, EmailStr, validator

from app.application_shareholder.models import (
    ShareholderCategoryEnum,
    ShareTransactionTypeEnum,
)
from app.common.models.base import StatusEnum


# ----------------------------
# Emergency Contact
# ----------------------------

class ShareholderEmergencyContactCreate(BaseModel):
    name: str
    phone: str
    email: Optional[EmailStr] = None
    relationship_to_shareholder: Optional[str] = None
    remarks: Optional[str] = None


# ----------------------------
# Shareholder (create / update)
# ----------------------------

class ShareholderCreate(BaseModel):
    code: Optional[str] = None
    company_id: Optional[int] = None  # resolved from context if None

    full_name: str
    category: ShareholderCategoryEnum = ShareholderCategoryEnum.INDIVIDUAL

    national_id: Optional[str] = None
    registration_no: Optional[str] = None

    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None

    # image is handled via file upload (img_key is set by service)
    img_key: Optional[str] = None

    status: StatusEnum = StatusEnum.ACTIVE
    remarks: Optional[str] = None

    emergency_contacts: Optional[List[ShareholderEmergencyContactCreate]] = None


class ShareholderUpdate(BaseModel):
    # code is immutable at update
    full_name: Optional[str] = None
    category: Optional[ShareholderCategoryEnum] = None

    national_id: Optional[str] = None
    registration_no: Optional[str] = None

    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None

    img_key: Optional[str] = None
    status: Optional[StatusEnum] = None
    remarks: Optional[str] = None

    # ERP-style replace all emergency contacts if provided
    emergency_contacts: Optional[List[ShareholderEmergencyContactCreate]] = None


# ----------------------------
# Shareholder outputs
# ----------------------------

class ShareholderMinimalOut(BaseModel):
    id: int
    code: str
    full_name: str


class ShareholderCreateResponse(BaseModel):
    message: str = "Shareholder created successfully"
    shareholder: ShareholderMinimalOut


# ----------------------------
# Share Type create / update
# ----------------------------

class ShareTypeCreate(BaseModel):
    company_id: Optional[int] = None
    code: str
    name: str
    nominal_value: float = 0.0
    is_default: bool = False
    total_authorised_shares: Optional[int] = None
    status: StatusEnum = StatusEnum.ACTIVE
    remarks: Optional[str] = None


class ShareTypeUpdate(BaseModel):
    name: Optional[str] = None
    nominal_value: Optional[float] = None
    is_default: Optional[bool] = None
    total_authorised_shares: Optional[int] = None
    status: Optional[StatusEnum] = None
    remarks: Optional[str] = None


# ----------------------------
# Share Ledger Entry create
# ----------------------------

class ShareLedgerEntryCreate(BaseModel):
    company_id: Optional[int] = None
    shareholder_id: int
    share_type_id: int

    posting_date: datetime
    transaction_type: ShareTransactionTypeEnum

    quantity: float
    rate: float = 0.0
    amount: float = 0.0

    journal_entry_id: Optional[int] = None
    source_doctype_id: Optional[int] = None
    source_doc_id: Optional[int] = None

    remarks: Optional[str] = None

    @validator("quantity")
    def _non_zero_qty(cls, v: float) -> float:
        if v == 0:
            raise ValueError("Quantity must be non-zero.")
        return v

    @validator("amount", always=True)
    def _default_amount(cls, v, values):
        # auto compute if not provided
        qty = values.get("quantity")
        rate = values.get("rate")
        if qty is not None and rate is not None and (v is None or v == 0):
            return float(qty) * float(rate)
        return v
