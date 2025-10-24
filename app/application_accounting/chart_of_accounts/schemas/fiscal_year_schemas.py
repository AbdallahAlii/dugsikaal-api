from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, validator, model_validator

from app.application_accounting.chart_of_accounts.models import FiscalYearStatusEnum
from app.common.date_utils import parse_date_flex


class FiscalYearCreate(BaseModel):
    name: str = Field(..., description="User-friendly name (e.g., 'FY 2024' or '2024-2025')")
    start_date: str = Field(..., description="Start date in flexible format (MM/DD/YYYY, YYYY-MM-DD, etc.)")
    end_date: str = Field(..., description="End date in flexible format (MM/DD/YYYY, YYYY-MM-DD, etc.)")
    is_short_year: bool = False

    @validator('start_date', 'end_date')
    def validate_and_parse_dates(cls, v):
        """Parse and validate date strings"""
        parsed = parse_date_flex(v)
        if not parsed:
            raise ValueError(f"Invalid date format: {v}. Use MM/DD/YYYY, YYYY-MM-DD, etc.")
        return parsed

    @model_validator(mode='after')
    def validate_fiscal_year_logic(self):
        """Validate fiscal year business logic"""
        start_date = self.start_date
        end_date = self.end_date

        if start_date and end_date:
            # Convert to datetime for validation (keep time as 00:00:00)
            start_dt = datetime.combine(start_date, datetime.min.time())
            end_dt = datetime.combine(end_date, datetime.min.time())

            # Basic date validation
            if end_dt <= start_dt:
                raise ValueError("Fiscal Year End Date must be after Fiscal Year Start Date")

        return self

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class FiscalYearUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[FiscalYearStatusEnum] = None


class FiscalYearOut(BaseModel):
    id: int
    company_id: int
    name: str
    start_date: datetime
    end_date: datetime
    status: str
    is_short_year: bool

    class Config:
        from_attributes = True