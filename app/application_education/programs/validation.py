from __future__ import annotations

from datetime import date
from typing import Optional

from app.business_validation.item_validation import BizValidationError


# ----------------------------
# Generic (ERPNext style)
# ----------------------------
def cannot_delete_linked(doc: str, linked: str) -> str:
    return f"Cannot delete or cancel because {doc} is linked with {linked}."


# ----------------------------
# Messages
# ----------------------------
ERR_PROGRAM_NOT_FOUND = "Program not found."
ERR_COURSE_NOT_FOUND = "Course not found."
ERR_PROGRAM_NAME_EXISTS = "Program already exists with this name."
ERR_COURSE_NAME_EXISTS = "Course already exists with this name."
ERR_COURSE_IN_USE = cannot_delete_linked("Course", "Program Course")
ERR_PROGRAM_IN_USE = cannot_delete_linked("Program", "other documents")
ERR_DUPLICATE_COURSE_IN_LIST = "Course already selected in this Program."


# ----------------------------
# Validators
# ----------------------------
def validate_credit_hours(v: Optional[int]) -> None:
    if v is None:
        return
    try:
        iv = int(v)
    except Exception:
        raise BizValidationError("Credit hours must be a number.")
    if iv < 0:
        raise BizValidationError("Credit hours cannot be negative.")
