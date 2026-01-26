from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, validator

from app.application_accounting.chart_of_accounts.models import (
    AccountTypeEnum,
    ReportTypeEnum,
    DebitOrCreditEnum,
)


class AccountBase(BaseModel):
    name: str = Field(..., description="Account name (e.g., 'Loan to Ali Mohamed')")
    account_type: AccountTypeEnum
    report_type: ReportTypeEnum
    is_group: bool = False
    debit_or_credit: DebitOrCreditEnum

    @validator("name")
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Account Name is required.")
        return v


class AccountCreate(AccountBase):
    # ✅ Optional; auto-generated if omitted
    code: Optional[str] = Field(
        None,
        description="Optional account number (4 digits, optional -NN, e.g. '1152' or '1152-01'). "
                    "If omitted, the system will auto-generate it."
    )
    parent_account_id: Optional[int] = Field(
        ...,
        description="Parent account ID (must be a group account).",
    )

    @validator("code")
    def strip_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class AccountUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    account_type: Optional[AccountTypeEnum] = None
    report_type: Optional[ReportTypeEnum] = None
    is_group: Optional[bool] = None
    debit_or_credit: Optional[DebitOrCreditEnum] = None
    parent_account_id: Optional[int] = None
    enabled: Optional[bool] = None

    @validator("code")
    def strip_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @validator("name")
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


class AccountOut(BaseModel):
    id: int
    company_id: int
    parent_account_id: Optional[int]
    code: str
    name: str
    account_type: AccountTypeEnum
    report_type: ReportTypeEnum
    is_group: bool
    debit_or_credit: DebitOrCreditEnum
    enabled: bool

    class Config:
        from_attributes = True
