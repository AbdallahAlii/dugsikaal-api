from __future__ import annotations
from typing import Optional, List, Literal
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

PaymentType = Literal["PAY", "RECEIVE", "INTERNAL_TRANSFER"]
PartyKind   = Literal["Customer", "Supplier", "Employee", "Shareholder", "Other"]

class PaymentReferenceRow(BaseModel):
    source_doctype_id: Optional[int] = None
    source_doc_id: Optional[int] = None
    allocated_amount: Decimal = Field(ge=0)

class PaymentCreateSchema(BaseModel):
    company_id: Optional[int] = None  # Make optional
    branch_id: Optional[int] = None   # Make optional
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

    @model_validator(mode="after")
    def _logical_rules(self) -> "PaymentCreateSchema":
        # Friendly messages, ERP-style
        if self.payment_type in ("PAY", "RECEIVE"):
            if not self.party_type or not self.party_id:
                raise ValueError("Select a Party and Party Type.")
            if not self.mode_of_payment_id:
                raise ValueError("Select a payment method.")
        else:
            # INTERNAL_TRANSFER
            if self.party_type or self.party_id:
                raise ValueError("Remove Party for Internal Transfer.")
        return self

class PaymentUpdateSchema(BaseModel):
    # immutable: company_id, branch_id, code
    payment_type: Optional[PaymentType] = None
    posting_date: Optional[date] = None
    mode_of_payment_id: Optional[int] = None
    party_type: Optional[PartyKind] = None
    party_id: Optional[int] = None
    paid_from_account_id: Optional[int] = None
    paid_to_account_id: Optional[int] = None
    paid_amount: Optional[Decimal] = Field(default=None)
    remarks: Optional[str] = None
    items: Optional[List[PaymentReferenceRow]] = None
    auto_allocate: Optional[bool] = None

class PaymentSubmitSchema(BaseModel):
    auto_allocate: Optional[bool] = False

class PaymentCancelSchema(BaseModel):
    reason: Optional[str] = None

# ------- Outstanding filter (unchanged) -------
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
# Expense Type
class ExpenseTypeCreate(BaseModel):
    company_id: Optional[int] = None  # Will be set from context if not provided
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    default_account_id: Optional[int] = None

class ExpenseTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    default_account_id: Optional[int] = None
    enabled: Optional[bool] = None

# Expense Item
class ExpenseItemIn(BaseModel):
    account_id: int
    paid_from_account_id: int
    description: Optional[str] = Field(None, max_length=255)
    amount: Decimal = Field(gt=0)
    cost_center_id: Optional[int] = None
    expense_type_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_accounts_different(self) -> "ExpenseItemIn":
        if self.account_id == self.paid_from_account_id:
            raise ValueError("Expense account and payment account must be different.")
        return self

# Expense Document
class ExpenseCreateSchema(BaseModel):
    company_id: Optional[int] = None  # Will be set from context if not provided
    branch_id: Optional[int] = None   # Will be set from context if not provided
    code: Optional[str] = None  # auto-generated
    posting_date: date
    remarks: Optional[str] = None
    cost_center_id: Optional[int] = None
    items: List[ExpenseItemIn] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_items(self) -> "ExpenseCreateSchema":
        if not self.items or len(self.items) == 0:
            raise ValueError("Add at least one expense item.")
        return self

class ExpenseUpdateSchema(BaseModel):
    posting_date: Optional[date] = None
    remarks: Optional[str] = None
    cost_center_id: Optional[int] = None
    items: Optional[List[ExpenseItemIn]] = None  # full replace when provided

class ExpenseSubmitSchema(BaseModel):
    pass  # No additional fields needed for submit

class ExpenseCancelSchema(BaseModel):
    reason: Optional[str] = None
