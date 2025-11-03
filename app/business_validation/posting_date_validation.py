
# app/business_validation/posting_date_validation.py
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.business_validation.item_validation import BizValidationError
from app.application_accounting.chart_of_accounts.models import FiscalYear, FiscalYearStatusEnum, PeriodClosingVoucher
from app.application_stock.stock_models import DocStatusEnum
from app.common.timezone.service import (
    get_company_timezone,
    now_in_company_tz,
    combine_local_posting_dt,
)

# Short, user-friendly error messages
ERR_POSTING_DATE_BEFORE_ORIGINAL = "Cannot post return before original document date"
ERR_POSTING_DATE_FUTURE = "Posting date cannot be in the far future"
ERR_POSTING_DATE_TOO_OLD = "Posting date is too old"
ERR_POSTING_DATE_CLOSED_PERIOD = "Posting date is in a closed accounting period"
ERR_NO_OPEN_FISCAL_YEAR = "No open fiscal year found for the posting date"

# allow small future drift (user clock ahead of server)
_FUTURE_LEEWAY = timedelta(minutes=5)

def _naive(dt: datetime) -> datetime:
    """Naivize for date-only comparisons (fiscal windows, etc.)."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt

def _get_open_fy(s: Session, posting_dt: datetime, company_id: int) -> Optional[FiscalYear]:
    pd = _naive(posting_dt)
    return s.query(FiscalYear).filter(
        FiscalYear.company_id == company_id,
        FiscalYear.status == FiscalYearStatusEnum.OPEN,
        FiscalYear.start_date <= pd,
        FiscalYear.end_date >= pd,
    ).first()

def _latest_closing(s: Session, company_id: int) -> Optional[PeriodClosingVoucher]:
    return s.query(PeriodClosingVoucher).filter(
        PeriodClosingVoucher.company_id == company_id,
        PeriodClosingVoucher.doc_status == DocStatusEnum.SUBMITTED,
    ).order_by(PeriodClosingVoucher.posting_date.desc()).first()

class PostingDateValidator:
    """
    Normalize and validate posting date/times for all transactional docs.

    Behavior:
      - Accepts date-only or datetime (naive or aware).
      - Always converts to company timezone and returns tz-aware datetime.
      - If time is 00:00:00 or date-only, injects a realistic time-of-day and a microsecond bump.
      - If small future drift (≤ _FUTURE_LEEWAY), clamp to 'now' instead of 400.
      - Enforces fiscal year/open period rules.
    """

    @staticmethod
    def validate_standalone_document(
        s: Session,
        posting_date_or_dt: Union[datetime, "date"],
        company_id: int,
        *,
        created_at: Optional[datetime] = None,
        treat_midnight_as_date: bool = True,
    ) -> datetime:
        # 1) Normalize to company TZ with µs bump (prevents collisions)
        tz = get_company_timezone(s, company_id)
        dt = combine_local_posting_dt(
            posting_date_or_dt,
            tz_like=tz,
            created_at=created_at,                  # fallbacks to now(tz) inside
            treat_midnight_as_date=treat_midnight_as_date,
            bump_usec=None,                         # auto bump from time_ns
        )

        # 2) Small future skew → clamp to "now"
        now = now_in_company_tz(s, company_id)
        if dt > now and (dt - now) <= _FUTURE_LEEWAY:
            dt = combine_local_posting_dt(now, tz_like=tz, created_at=now, treat_midnight_as_date=False)

        # 3) (optional) prevent far future if you want
        # if dt > now + timedelta(days=1):
        #     raise BizValidationError(ERR_POSTING_DATE_FUTURE)

        # 4) Fiscal / period closing checks (by date)
        PostingDateValidator._validate_fiscal_period(s, dt, company_id)

        # 5) Too old? (keep your 2-year rule; configurable if needed)
        two_years_ago = _naive(now).replace(year=_naive(now).year - 2)
        if _naive(dt) < two_years_ago:
            raise BizValidationError(ERR_POSTING_DATE_TOO_OLD)

        return dt

    @staticmethod
    def validate_return_against_original(
        s: Session,
        current_posting_date: Union[datetime, "date"],
        original_document_date: Union[datetime, "date"],
        company_id: int,
    ) -> None:
        tz = get_company_timezone(s, company_id)
        cur = combine_local_posting_dt(current_posting_date, tz_like=tz)
        org = combine_local_posting_dt(original_document_date, tz_like=tz)
        PostingDateValidator._validate_fiscal_period(s, cur, company_id)
        if _naive(cur) < _naive(org):
            raise BizValidationError(ERR_POSTING_DATE_BEFORE_ORIGINAL)

    @staticmethod
    def _validate_fiscal_period(s: Session, posting_dt: datetime, company_id: int) -> None:
        if not _get_open_fy(s, posting_dt, company_id):
            raise BizValidationError(ERR_NO_OPEN_FISCAL_YEAR)
        latest = _latest_closing(s, company_id)
        if latest and _naive(posting_dt) <= _naive(latest.posting_date):
            raise BizValidationError(ERR_POSTING_DATE_CLOSED_PERIOD)
