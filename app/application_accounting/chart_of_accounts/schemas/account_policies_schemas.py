from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

from app.application_accounting.chart_of_accounts.account_policies import ModeOfPaymentTypeEnum, AccountUseRoleEnum

# ─────────── Mode of Payment ───────────
class MoPAccountIn(BaseModel):
    account_id: int
    is_default: bool = False
    enabled: bool = True

class ModeOfPaymentCreate(BaseModel):
    """Frappe-style: create with all data including accounts"""
    name: str = Field(..., min_length=1, max_length=100)
    type: ModeOfPaymentTypeEnum
    enabled: bool = True
    accounts: List[MoPAccountIn] = []

    @field_validator("accounts")
    @classmethod
    def validate_single_default(cls, accounts: List[MoPAccountIn]):
        """Frappe-style: only one default account per MoP"""
        defaults = [a for a in accounts if a.is_default]
        if len(defaults) > 1:
            raise ValueError("Only one account can be set as default")
        return accounts

class ModeOfPaymentUpdate(BaseModel):
    """Frappe-style: update entire document including accounts"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[ModeOfPaymentTypeEnum] = None
    enabled: Optional[bool] = None
    accounts: Optional[List[MoPAccountIn]] = None  # None = keep existing, [] = remove all

# ─────────── Account Access Policy ───────────
class AccountAccessPolicyCreate(BaseModel):
    mode_of_payment_id: int
    role: AccountUseRoleEnum
    account_id: int
    user_id: Optional[int] = None
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    enabled: bool = True

class AccountAccessPolicyUpdate(BaseModel):
    role: Optional[AccountUseRoleEnum] = None
    account_id: Optional[int] = None
    user_id: Optional[int] = None
    department_id: Optional[int] = None
    branch_id: Optional[int] = None
    enabled: Optional[bool] = None