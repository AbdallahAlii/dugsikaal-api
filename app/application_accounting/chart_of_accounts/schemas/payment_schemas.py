from __future__ import annotations
from typing import Optional, List, Literal
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field

PaymentType = Literal["PAY", "RECEIVE", "INTERNAL_TRANSFER"]
PartyKind = Literal["Customer", "Supplier", "Employee", "Shareholder", "Other"]

class PaymentReferenceRow(BaseModel):
    source_doctype_id: Optional[int] = None
    source_doc_id: Optional[int] = None
    allocated_amount: Decimal = Field(ge=0)

class PaymentCreateSchema(BaseModel):
    company_id: int
    branch_id: int
    # code is auto-generated; optional manual override (rare)
    code: Optional[str] = None
    payment_type: PaymentType
    posting_date: date
    mode_of_payment_id: Optional[int] = None
    party_type: Optional[PartyKind] = None
    party_id: Optional[int] = None
    paid_from_account_id: int
    paid_to_account_id: int
    paid_amount: Decimal = Field(gt=0)
    remarks: Optional[str] = None
    items: Optional[List[PaymentReferenceRow]] = None
    auto_allocate: Optional[bool] = False

class PaymentUpdateSchema(BaseModel):
    payment_type: Optional[PaymentType] = None
    posting_date: Optional[date] = None
    mode_of_payment_id: Optional[int] = None
    party_type: Optional[PartyKind] = None
    party_id: Optional[int] = None
    paid_from_account_id: Optional[int] = None
    paid_to_account_id: Optional[int] = None
    paid_amount: Optional[Decimal] = None
    remarks: Optional[str] = None
    items: Optional[List[PaymentReferenceRow]] = None
    auto_allocate: Optional[bool] = None

class PaymentSubmitSchema(BaseModel):
    auto_allocate: Optional[bool] = False

class PaymentCancelSchema(BaseModel):
    reason: Optional[str] = None

class OutstandingFilter(BaseModel):
    party_kind: PartyKind
    party_id: int
    posting_from: Optional[date] = None
    posting_to: Optional[date] = None
    due_from: Optional[date] = None
    due_to: Optional[date] = None
    gt_amount: Optional[Decimal] = None
    lt_amount: Optional[Decimal] = None
    limit: Optional[int] = 200

# Expense
class ExpenseItemIn(BaseModel):
    account_id: int
    paid_from_account_id: int
    description: Optional[str] = None
    amount: Decimal = Field(gt=0)
    cost_center_id: Optional[int] = None
    expense_type_id: Optional[int] = None

class ExpenseCreateSchema(BaseModel):
    company_id: int
    branch_id: int
    code: Optional[str] = None  # auto-generated
    posting_date: date
    remarks: Optional[str] = None
    items: List[ExpenseItemIn]

class ExpenseUpdateSchema(BaseModel):
    posting_date: Optional[date] = None
    remarks: Optional[str] = None
    cost_center_id: Optional[int] = None
    items: Optional[List[ExpenseItemIn]] = None  # full replace when provided

class ExpenseCancelSchema(BaseModel):
    reason: Optional[str] = None
