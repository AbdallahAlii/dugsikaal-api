from __future__ import annotations

from datetime import date
from app.business_validation.item_validation import BizValidationError

# short + clear
ERR_SETTINGS_EXISTS = "Education settings already exist."
ERR_SETTINGS_NOT_FOUND = "Education settings not found."

ERR_YEAR_NOT_FOUND = "Academic year not found."
ERR_TERM_NOT_FOUND = "Academic term not found."

ERR_YEAR_NAME_EXISTS = "Academic year name exists."
ERR_TERM_NAME_EXISTS = "Academic term name exists."

ERR_YEAR_DATE_RANGE = "Invalid academic year dates."
ERR_TERM_DATE_RANGE = "Invalid academic term dates."
ERR_TERM_OUTSIDE_YEAR = "Term must be within its academic year dates."

ERR_INVALID_HOLIDAY_LIST = "Invalid holiday list."
ERR_INVALID_DEFAULT_YEAR = "Invalid default academic year."
ERR_INVALID_DEFAULT_TERM = "Invalid default academic term."


def validate_year_dates(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise BizValidationError(ERR_YEAR_DATE_RANGE)


def validate_term_dates(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise BizValidationError(ERR_TERM_DATE_RANGE)


def validate_term_within_year(
    *,
    term_start: date,
    term_end: date,
    year_start: date,
    year_end: date,
) -> None:
    if term_start < year_start or term_end > year_end:
        raise BizValidationError(ERR_TERM_OUTSIDE_YEAR)
