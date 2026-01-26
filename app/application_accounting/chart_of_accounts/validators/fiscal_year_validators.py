# from __future__ import annotations
# from datetime import datetime, timedelta
# from typing import Optional
# import logging
#
# from app.business_validation.item_validation import BizValidationError
#
# log = logging.getLogger(__name__)
#
# # User-friendly error messages
# ERR_FISCAL_YEAR_END_BEFORE_START = "Fiscal Year End Date must be after Fiscal Year Start Date"
# ERR_FISCAL_YEAR_TOO_LONG = "Fiscal Year period should not exceed 370 days"
# ERR_FISCAL_YEAR_TOO_SHORT = "Fiscal Year period should be at least 1 month"
# ERR_FISCAL_YEAR_OVERLAP = "Fiscal year dates overlap with an existing fiscal year"
# ERR_OPEN_FISCAL_YEAR_EXISTS = "Cannot create new fiscal year while another is open"
# ERR_INVALID_STATUS_CHANGE = "Invalid fiscal year status change"
#
#
# class FiscalYearValidator:
#     """Fiscal Year specific business validators"""
#
#     @staticmethod
#     def validate_date_range(start_date: datetime, end_date: datetime) -> None:
#         """Validate fiscal year date range constraints"""
#         # Check end date is after start date
#         if end_date <= start_date:
#             raise BizValidationError(ERR_FISCAL_YEAR_END_BEFORE_START)
#
#         # Check period length
#         days_diff = (end_date - start_date).days
#
#         # Should be at least 1 month
#         if days_diff < 28:
#             raise BizValidationError(ERR_FISCAL_YEAR_TOO_SHORT)
#
#         # Should not exceed 370 days (allowing for leap years and short extensions)
#         if days_diff > 370:
#             raise BizValidationError(ERR_FISCAL_YEAR_TOO_LONG)
#
#     @staticmethod
#     def validate_status_transition(current_status: str, new_status: str) -> None:
#         """Validate fiscal year status transitions"""
#         # Only allow Open -> Closed and Closed -> Open transitions
#         valid_transitions = {
#             'Open': ['Closed'],
#             'Closed': ['Open']
#         }
#
#         allowed_new_statuses = valid_transitions.get(current_status, [])
#         if new_status not in allowed_new_statuses:
#             raise BizValidationError(ERR_INVALID_STATUS_CHANGE)
from __future__ import annotations
from datetime import datetime
from typing import Optional
import logging

from app.business_validation.item_validation import BizValidationError

log = logging.getLogger(__name__)

ERR_FISCAL_YEAR_END_BEFORE_START = "Fiscal Year End Date must be after Fiscal Year Start Date"
ERR_FISCAL_YEAR_TOO_LONG = "Fiscal Year period should not exceed 370 days"
ERR_FISCAL_YEAR_TOO_SHORT = "Fiscal Year period should be at least 1 month"
ERR_FISCAL_YEAR_OVERLAP = "Fiscal year dates overlap with an existing fiscal year"
ERR_OPEN_FISCAL_YEAR_EXISTS = "Cannot create new fiscal year while another is open"
ERR_INVALID_STATUS_CHANGE = "Invalid fiscal year status change"
ERR_FISCAL_YEAR_IN_USE = "Fiscal year with existing transactions can not be deleted."


class FiscalYearValidator:
    """Fiscal Year specific business validators"""

    @staticmethod
    def validate_date_range(start_date: datetime, end_date: datetime) -> None:
        """Validate fiscal year date range constraints"""
        if end_date <= start_date:
            raise BizValidationError(ERR_FISCAL_YEAR_END_BEFORE_START)

        days_diff = (end_date - start_date).days

        if days_diff < 28:
            raise BizValidationError(ERR_FISCAL_YEAR_TOO_SHORT)

        if days_diff > 370:
            raise BizValidationError(ERR_FISCAL_YEAR_TOO_LONG)

    @staticmethod
    def validate_status_transition(current_status: str, new_status: str) -> None:
        """Validate fiscal year status transitions"""
        valid_transitions = {
            "Open": ["Closed"],
            "Closed": ["Open"],
        }

        allowed_new_statuses = valid_transitions.get(current_status, [])
        if new_status not in allowed_new_statuses:
            raise BizValidationError(ERR_INVALID_STATUS_CHANGE)

    @staticmethod
    def ensure_deletable(
        *,
        has_journal_entries: bool,
        has_gl_entries: bool,
        has_closing_vouchers: bool,
    ) -> None:
        """
        Ensure a fiscal year can be safely deleted.
        We do not allow delete when there is any financial activity.
        """
        if has_journal_entries or has_gl_entries or has_closing_vouchers:
            raise BizValidationError(ERR_FISCAL_YEAR_IN_USE)
