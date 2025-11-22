# app/application_accounting/chart_of_accounts/schemas/journal_schemas.py
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.application_accounting.chart_of_accounts.models import (
    JournalEntryTypeEnum,
    PartyTypeEnum,
)


# ----------------------------- Journal Entry -----------------------------


class JournalEntryLineIn(BaseModel):
    account_id: int
    debit: Decimal = Decimal("0.0000")
    credit: Decimal = Decimal("0.0000")
    cost_center_id: Optional[int] = None
    party_type: Optional[PartyTypeEnum] = None
    party_id: Optional[int] = None
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def _validate_amounts(self):
        d = Decimal(str(self.debit or 0))
        c = Decimal(str(self.credit or 0))

        if d < 0 or c < 0:
            raise ValueError("Debit/Credit cannot be negative.")
        if (d == 0) and (c == 0):
            # ERP-style: "Row X: Both Debit and Credit values cannot be zero."
            # Here we don't know row; service will re-check and add row info.
            raise ValueError("Both Debit and Credit values cannot be zero.")
        if (d > 0) and (c > 0):
            # ERP-style: "You cannot credit and debit same account at the same time."
            raise ValueError("A line cannot have both debit and credit.")

        return self


class JournalEntryCreateSchema(BaseModel):
    company_id: int
    branch_id: int
    posting_date: datetime
    entry_type: JournalEntryTypeEnum = JournalEntryTypeEnum.GENERAL
    remarks: Optional[str] = None
    items: List[JournalEntryLineIn] = Field(min_length=2)


class JournalEntryUpdateSchema(BaseModel):
    posting_date: Optional[datetime] = None
    entry_type: Optional[JournalEntryTypeEnum] = None
    remarks: Optional[str] = None
    items: Optional[List[JournalEntryLineIn]] = Field(default=None, min_length=2)


class JournalEntrySubmitSchema(BaseModel):
    pass


class JournalEntryCancelSchema(BaseModel):
    reason: Optional[str] = None


# ------------------------ Period Closing Voucher ------------------------


class PeriodClosingVoucherCreateSchema(BaseModel):
    company_id: int
    branch_id: int
    closing_fiscal_year_id: int
    closing_account_head_id: int
    posting_date: Optional[datetime] = None  # defaults to FY end_date in service
    remarks: Optional[str] = None


class PeriodClosingVoucherUpdateSchema(BaseModel):
    posting_date: Optional[datetime] = None
    closing_account_head_id: Optional[int] = None
    remarks: Optional[str] = None


class PeriodClosingVoucherSubmitSchema(BaseModel):
    pass


class PeriodClosingVoucherCancelSchema(BaseModel):
    reason: Optional[str] = None
