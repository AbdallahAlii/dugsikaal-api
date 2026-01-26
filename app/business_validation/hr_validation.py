# app/business_validation/hr_validation.py
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Dict, Any, Optional

from app.business_validation.item_validation import BizValidationError

# ---- User-facing messages (HR specific) ----

ERR_EMP_PRIMARY_ASSIGNMENT_REQUIRED = (
    "At least one primary assignment is required for an employee."
)
ERR_EMP_JOINING_DATE_REQUIRED = "Date of joining is required."
ERR_EMP_DOB_AFTER_JOINING = "Date of birth cannot be on or after the date of joining."
ERR_EMP_GENDER_INVALID = "Selected gender is not valid."
ERR_EMP_HOLIDAY_LIST_INVALID = (
    "Selected Holiday List is invalid or does not belong to this company."
)
ERR_EMP_SHIFT_TYPE_INVALID = (
    "Selected Shift Type is invalid or does not belong to this company."
)
ERR_EMP_ASSIGNMENT_COMPANY_MISMATCH = (
    "All assignments must belong to the same company as the employee."
)

ERR_HOLIDAY_LIST_RANGE = "Holiday List 'To Date' cannot be before 'From Date'."
ERR_HOLIDAY_OUT_OF_RANGE = "Holiday date must be within the Holiday List range."
ERR_HOLIDAY_DUPLICATE_DATE = "Holiday date is already present in this Holiday List."

ERR_SHIFT_ASSIGN_RANGE = "Shift Assignment 'To Date' cannot be before 'From Date'."

ERR_ATTENDANCE_DATE_REQUIRED = "Attendance date is required."
ERR_ATTENDANCE_STATUS_REQUIRED = "Attendance status is required."
ERR_ATTENDANCE_DUPLICATE = "Attendance is already marked for this employee on this date."

ERR_CHECKIN_LOG_TIME_REQUIRED = "Log time is required for Employee Checkin."
ERR_CHECKIN_LOG_TYPE_REQUIRED = "Log type is required for Employee Checkin."
ERR_CHECKIN_EMP_NOT_FOUND = "Employee not found for the provided identifier."
ERR_CHECKIN_UNSUPPORTED_SOURCE = "Unsupported source for Employee Checkin."
ERR_CHECKIN_DUPLICATE = "This employee already has a log with the same timestamp."


# ----------------------------------------------------------------------
# Employee validations
# ----------------------------------------------------------------------


def validate_employee_basic(*, dob: Optional[date], date_of_joining: Optional[date]) -> None:
    if not date_of_joining:
        raise BizValidationError(ERR_EMP_JOINING_DATE_REQUIRED)
    if dob and dob >= date_of_joining:
        raise BizValidationError(ERR_EMP_DOB_AFTER_JOINING)


def validate_employee_assignments(assignments: Iterable[Dict[str, Any]]) -> None:
    """
    - At least one primary assignment.
    - from_date present.
    - If to_date given, to_date >= from_date.
    """
    assignments = list(assignments)
    if not assignments:
        raise BizValidationError(ERR_EMP_PRIMARY_ASSIGNMENT_REQUIRED)

    has_primary = False
    for a in assignments:
        if a.get("is_primary"):
            has_primary = True
        fd = a.get("from_date")
        td = a.get("to_date")
        if fd and td and td < fd:
            raise BizValidationError("Assignment 'To Date' cannot be before 'From Date'.")

    if not has_primary:
        raise BizValidationError(ERR_EMP_PRIMARY_ASSIGNMENT_REQUIRED)


# ----------------------------------------------------------------------
# Holiday List validations
# ----------------------------------------------------------------------


def validate_holiday_list_range(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise BizValidationError(ERR_HOLIDAY_LIST_RANGE)


def validate_holiday_rows_within_range(
    from_date: date,
    to_date: date,
    holidays: Iterable[Dict[str, Any]],
) -> None:
    seen_dates: set[date] = set()
    for h in holidays:
        hd: date = h["holiday_date"]
        if hd < from_date or hd > to_date:
            raise BizValidationError(ERR_HOLIDAY_OUT_OF_RANGE)
        if hd in seen_dates:
            raise BizValidationError(ERR_HOLIDAY_DUPLICATE_DATE)
        seen_dates.add(hd)


# ----------------------------------------------------------------------
# Shift Assignment validations
# ----------------------------------------------------------------------


def validate_shift_assignment_range(from_date: date, to_date: Optional[date]) -> None:
    if from_date and to_date and to_date < from_date:
        raise BizValidationError(ERR_SHIFT_ASSIGN_RANGE)


# ----------------------------------------------------------------------
# Attendance validations
# ----------------------------------------------------------------------


def validate_attendance_basic(
    *,
    attendance_date: Optional[date],
    status: Optional[str],
) -> None:
    if not attendance_date:
        raise BizValidationError(ERR_ATTENDANCE_DATE_REQUIRED)
    if not status:
        raise BizValidationError(ERR_ATTENDANCE_STATUS_REQUIRED)


# ----------------------------------------------------------------------
# Checkin validations
# ----------------------------------------------------------------------


def validate_checkin_basic(
    *,
    log_time: Optional[datetime],
    log_type: Optional[str],
    source: Optional[str],
) -> None:
    if not log_time:
        raise BizValidationError(ERR_CHECKIN_LOG_TIME_REQUIRED)
    if not log_type:
        raise BizValidationError(ERR_CHECKIN_LOG_TYPE_REQUIRED)
    if source is None:
        return
    # keep aligned with CheckinSourceEnum values
    if source not in ("Manual", "Device", "Mobile", "Other"):
        raise BizValidationError(ERR_CHECKIN_UNSUPPORTED_SOURCE)
