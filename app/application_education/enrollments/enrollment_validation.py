from __future__ import annotations

from datetime import date
from typing import Optional, Iterable, List

from app.business_validation.item_validation import BizValidationError
from app.application_education.enrollments.enrollment_model import (
    EnrollmentStatusEnum,
    EnrollmentResultEnum,
)

# ----------------------------
# Not found (better wording)
# ----------------------------
ERR_SELECTED_STUDENT_NOT_FOUND = "Selected student was not found."
ERR_SELECTED_PROGRAM_NOT_FOUND = "Selected program was not found."
ERR_SELECTED_ACADEMIC_YEAR_NOT_FOUND = "Selected academic year was not found."
ERR_SELECTED_ACADEMIC_TERM_NOT_FOUND = "Selected academic term was not found."
ERR_SELECTED_BRANCH_NOT_FOUND = "Selected branch was not found."
ERR_SELECTED_BATCH_NOT_FOUND = "Selected batch was not found."
ERR_SELECTED_GROUP_NOT_FOUND = "Selected student group was not found."
ERR_SELECTED_COURSE_NOT_FOUND = "Selected course was not found."

# ----------------------------
# Status / enums
# ----------------------------
ERR_INVALID_ENROLLMENT_STATUS = "Invalid enrollment status."
ERR_INVALID_RESULT_STATUS = "Invalid result status."

# ----------------------------
# Business rules
# ----------------------------
def err_student_already_enrolled(program_name: str, year_name: str) -> str:
    return f"Student is already enrolled in {program_name} for {year_name}."

ERR_GROUP_NOT_IN_PROGRAM = "Selected Student Group does not belong to this Program."
ERR_GROUP_YEAR_MISMATCH = "Selected Student Group does not match the selected Academic Year."
ERR_GROUP_TERM_MISMATCH = "Selected Student Group does not match the selected Academic Term."

ERR_COURSE_SELECTED_MULTIPLE_TIMES = "Course is selected multiple times."
ERR_COURSE_NOT_FOUND_IDS = "Course not found: {ids}"

ERR_COURSE_ENROLLMENT_EXISTS = (
    "Student is already enrolled in this course for the selected academic period."
)

ERR_NO_CURRICULUM_FOUND = "No curriculum found for this program."

# ----------------------------
# Date sanity (extra guard)
# ----------------------------
ERR_ADMISSION_AFTER_ENROLLMENT = "Admission date cannot be after enrollment date."
ERR_ENROLLMENT_AFTER_COMPLETION = "Enrollment date cannot be after completion date."
ERR_ENROLLMENT_AFTER_CANCELLATION = "Enrollment date cannot be after cancellation date."
ERR_CANCEL_AFTER_COMPLETION = "Cancellation date cannot be after completion date."

ERR_ONLY_DRAFT_CAN_BE_SUBMITTED = "Only Draft records can be submitted."
ERR_PROGRAM_ENROLLMENT_NOT_FOUND = "Selected program enrollment was not found."
ERR_COURSE_ENROLLMENT_NOT_FOUND = "Selected course enrollment was not found."


def validate_program_enrollment_dates(
    *,
    admission_date: Optional[date],
    enrollment_date: Optional[date],
    completion_date: Optional[date],
    cancellation_date: Optional[date],
) -> None:
    if admission_date and enrollment_date and admission_date > enrollment_date:
        raise BizValidationError(ERR_ADMISSION_AFTER_ENROLLMENT)
    if enrollment_date and completion_date and enrollment_date > completion_date:
        raise BizValidationError(ERR_ENROLLMENT_AFTER_COMPLETION)
    if enrollment_date and cancellation_date and enrollment_date > cancellation_date:
        raise BizValidationError(ERR_ENROLLMENT_AFTER_CANCELLATION)
    if cancellation_date and completion_date and cancellation_date > completion_date:
        raise BizValidationError(ERR_CANCEL_AFTER_COMPLETION)


def validate_course_enrollment_dates(
    *,
    enrollment_date: Optional[date],
    completion_date: Optional[date],
    cancellation_date: Optional[date],
) -> None:
    if enrollment_date and completion_date and enrollment_date > completion_date:
        raise BizValidationError(ERR_ENROLLMENT_AFTER_COMPLETION)
    if enrollment_date and cancellation_date and enrollment_date > cancellation_date:
        raise BizValidationError(ERR_ENROLLMENT_AFTER_CANCELLATION)
    if cancellation_date and completion_date and cancellation_date > completion_date:
        raise BizValidationError(ERR_CANCEL_AFTER_COMPLETION)


def validate_enrollment_status(v) -> EnrollmentStatusEnum:
    if isinstance(v, EnrollmentStatusEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in EnrollmentStatusEnum:
            if s == m.value or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_ENROLLMENT_STATUS)


def validate_result_status(v) -> EnrollmentResultEnum:
    if isinstance(v, EnrollmentResultEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in EnrollmentResultEnum:
            if s == m.value or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_RESULT_STATUS)


def ensure_no_duplicate_ids(ids: Optional[Iterable[int]], *, err_msg: str) -> List[int]:
    """
    Returns de-duplicated list while preserving first-seen order.
    Raises if duplicates exist (your requirement).
    """
    if not ids:
        return []
    seen = set()
    out = []
    dup_found = False
    for x in ids:
        xi = int(x)
        if xi in seen:
            dup_found = True
        else:
            seen.add(xi)
            out.append(xi)
    if dup_found:
        raise BizValidationError(err_msg)
    return out
