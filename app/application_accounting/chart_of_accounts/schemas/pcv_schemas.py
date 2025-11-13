# app/application_accounting/chart_of_accounts/schemas/pcv_schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

class PCVCreate(BaseModel):
    company_id: int = Field(..., gt=0)
    closing_fiscal_year_id: int = Field(..., gt=0)
    closing_account_head_id: int = Field(..., gt=0, description="Retained Earnings (Equity) account id")
    posting_date: datetime = Field(..., description="Effective accounting date (usually FY end date)")
    code: Optional[str] = Field(None, description="Optional manual code (must be next)")
    remarks: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class PCVSubmitSchema(BaseModel):
    """Empty schema for submit - no payload needed"""
    model_config = ConfigDict(extra="forbid")


# Add the missing cancel schema
class PCVCancelSchema(BaseModel):
    reason: Optional[str] = Field(None, description="Reason for cancellation")

    model_config = ConfigDict(extra="forbid")
class PCVUpdate(BaseModel):
    posting_date: Optional[datetime] = None
    closing_account_head_id: Optional[int] = Field(None, gt=0)
    remarks: Optional[str] = None

    model_config = ConfigDict(extra="forbid")

class PCVOut(BaseModel):
    id: int
    company_id: int
    closing_fiscal_year_id: int
    closing_account_head_id: int
    generated_journal_entry_id: Optional[int]
    code: str
    posting_date: datetime
    doc_status: str
    auto_prepared: bool
    submitted_by_id: Optional[int]
    submitted_at: Optional[datetime]
    total_profit_loss: float
    remarks: Optional[str]

    model_config = ConfigDict(from_attributes=True)
