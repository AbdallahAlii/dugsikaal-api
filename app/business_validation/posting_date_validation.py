# app/business_validation/posting_date_validation.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.business_validation.item_validation import BizValidationError
from app.application_accounting.chart_of_accounts.models import FiscalYear, FiscalYearStatusEnum, PeriodClosingVoucher
from app.application_stock.stock_models import DocStatusEnum

# Short, user-friendly error messages
ERR_POSTING_DATE_BEFORE_ORIGINAL = "Cannot post return before original document date"
ERR_POSTING_DATE_FUTURE = "Posting date cannot be in the future"
ERR_POSTING_DATE_TOO_OLD = "Posting date is too old"
ERR_POSTING_DATE_CLOSED_PERIOD = "Posting date is in a closed accounting period"
ERR_NO_OPEN_FISCAL_YEAR = "No open fiscal year found for the posting date"


def _normalize_date(dt: datetime) -> datetime:
    """Remove timezone for consistent comparison."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _get_open_fiscal_year_for_date(s: Session, posting_date: datetime, company_id: int) -> Optional[FiscalYear]:
    """Find an open fiscal year that contains the posting date."""
    posting_date_naive = _normalize_date(posting_date)

    return s.query(FiscalYear).filter(
        FiscalYear.company_id == company_id,
        FiscalYear.status == FiscalYearStatusEnum.OPEN,
        FiscalYear.start_date <= posting_date_naive,
        FiscalYear.end_date >= posting_date_naive
    ).first()


def _get_latest_period_closing(s: Session, company_id: int) -> Optional[PeriodClosingVoucher]:
    """Get the latest SUBMITTED period closing voucher for a company."""
    return s.query(PeriodClosingVoucher).filter(
        PeriodClosingVoucher.company_id == company_id,
        PeriodClosingVoucher.doc_status == DocStatusEnum.SUBMITTED
    ).order_by(PeriodClosingVoucher.posting_date.desc()).first()


class PostingDateValidator:
    """
    Comprehensive posting date validator for all transactional documents.
    """

    @staticmethod
    def validate_return_against_original(
            s: Session,
            current_posting_date: datetime,
            original_document_date: datetime,
            company_id: int,
    ) -> None:
        """Validate return document with all business rules."""
        PostingDateValidator._validate_fiscal_period(s, current_posting_date, company_id)
        PostingDateValidator._validate_against_original(current_posting_date, original_document_date)
        PostingDateValidator._validate_basic_rules(current_posting_date)

    @staticmethod
    def validate_standalone_document(
            s: Session,
            posting_date: datetime,
            company_id: int,
    ) -> None:
        """Validate standalone document with all business rules."""
        PostingDateValidator._validate_fiscal_period(s, posting_date, company_id)
        PostingDateValidator._validate_basic_rules(posting_date)

    @staticmethod
    def _validate_fiscal_period(s: Session, posting_date: datetime, company_id: int) -> None:
        """Core check against open fiscal years and closed periods."""
        open_fiscal_year = _get_open_fiscal_year_for_date(s, posting_date, company_id)
        if not open_fiscal_year:
            raise BizValidationError(ERR_NO_OPEN_FISCAL_YEAR)

        latest_closing = _get_latest_period_closing(s, company_id)
        if latest_closing:
            closing_date_naive = _normalize_date(latest_closing.posting_date)
            posting_date_naive = _normalize_date(posting_date)

            if posting_date_naive <= closing_date_naive:
                raise BizValidationError(ERR_POSTING_DATE_CLOSED_PERIOD)

    @staticmethod
    def _validate_against_original(posting_date: datetime, original_document_date: datetime) -> None:
        """Check that return is not dated before the original document."""
        if _normalize_date(posting_date) < _normalize_date(original_document_date):
            raise BizValidationError(ERR_POSTING_DATE_BEFORE_ORIGINAL)

    @staticmethod
    def _validate_basic_rules(posting_date: datetime) -> None:
        """Validate general rules like not in future or too far in the past."""
        now_naive = _normalize_date(datetime.now())
        posting_date_naive = _normalize_date(posting_date)

        if posting_date_naive > now_naive:
            raise BizValidationError(ERR_POSTING_DATE_FUTURE)

        # This rule can be made configurable in Company Settings
        two_years_ago = now_naive.replace(year=now_naive.year - 2)
        if posting_date_naive < two_years_ago:
            raise BizValidationError(ERR_POSTING_DATE_TOO_OLD)