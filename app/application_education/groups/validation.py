from __future__ import annotations

from datetime import date
from typing import Optional

from app.business_validation.item_validation import BizValidationError

# ============================================================
# Error Messages (Frappe-style: Direct and Clear)
# ============================================================

# --- Required ---
ERR_GROUP_NAME_REQUIRED = "Student Group name is required."
ERR_PROGRAM_REQUIRED = "Program is required."
ERR_BATCH_NAME_REQUIRED = "Batch name is required."
ERR_CATEGORY_NAME_REQUIRED = "Student Category name is required."
# --- Not Found ---
ERR_GROUP_NOT_FOUND = "Student Group not found."
ERR_PROGRAM_NOT_FOUND = "Program not found."
ERR_ACADEMIC_YEAR_NOT_FOUND = "Academic year not found."
ERR_ACADEMIC_TERM_NOT_FOUND = "Academic term not found."
ERR_BATCH_NOT_FOUND = "Batch not found."
ERR_SECTION_NOT_FOUND = "Section not found."
ERR_STUDENT_CATEGORY_NOT_FOUND = "Student category not found."
ERR_BRANCH_NOT_FOUND = "Branch not found."
ERR_STUDENT_NOT_FOUND = "Student not found."
ERR_MEMBERSHIP_NOT_FOUND = "Membership record not found."

# --- Duplicates ---
ERR_GROUP_NAME_EXISTS = "A Student Group with this name already exists."
ERR_GROUP_SETUP_EXISTS = "A Student Group with this exact Program, Year, and Section combination already exists."
ERR_MEMBER_ALREADY_EXISTS = "This student is already a member of this group."
ERR_BATCH_EXISTS = "A Batch with this name already exists."
ERR_CATEGORY_EXISTS = "A Student Category with this name already exists."
# --- Rules ---
ERR_CAPACITY_NEGATIVE = "Capacity must be zero or more."
ERR_GROUP_FULL = "Group capacity reached. Cannot add more students."
ERR_INVALID_DATES = "The Left date cannot be earlier than the Joined date."
ERR_DELETE_FORBIDDEN = "Cannot delete this group because it contains student membership history. Please disable it instead."
ERR_INVALID_GROUP_TYPE = "Invalid 'Group Based On' type selected."


# ============================================================
# Student Group Validators (No DB access)
# ============================================================

def validate_student_group_basics(
    *,
    name: Optional[str],
    program_id: Optional[int],
    capacity: Optional[int],
) -> str:
    """
    Minimal rules for create/update.
    Returns normalized name (trimmed).
    """
    nm = (name or "").strip()
    if not nm:
        raise BizValidationError(ERR_GROUP_NAME_REQUIRED)

    if not program_id:
        raise BizValidationError(ERR_PROGRAM_REQUIRED)

    if capacity is not None:
        try:
            cap = int(capacity)
        except (ValueError, TypeError):
            raise BizValidationError(ERR_CAPACITY_NEGATIVE)
        if cap < 0:
            raise BizValidationError(ERR_CAPACITY_NEGATIVE)

    return nm


def validate_group_capacity(*, current_count: int, capacity: Optional[int]) -> None:
    """0/None = unlimited."""
    if capacity is None:
        return
    cap = int(capacity)
    if cap <= 0:
        return
    if current_count >= cap:
        raise BizValidationError(ERR_GROUP_FULL)


def validate_group_based_on(v) -> Optional[str]:
    """
    Keep it minimal:
    - allow None/"" (no value)
    - allow BATCH/COURSE/ACTIVITY (string or enum-like)
    Returns normalized string (e.g. 'BATCH') or None.
    """
    if v is None or v == "":
        return None

    allowed = {"BATCH", "COURSE", "ACTIVITY"}

    if isinstance(v, str):
        s = v.strip().upper()
        if s in allowed:
            return s
        raise BizValidationError(ERR_INVALID_GROUP_TYPE)

    # enum-like
    name = getattr(v, "name", None)
    value = getattr(v, "value", None)
    if isinstance(name, str) and name.upper() in allowed:
        return name.upper()
    if isinstance(value, str) and value.upper() in allowed:
        return value.upper()

    raise BizValidationError(ERR_INVALID_GROUP_TYPE)


# ============================================================
# Membership Validators (No DB access)
# ============================================================

def validate_membership(
    *,
    already_in: bool,
    joined: Optional[date],
    left: Optional[date],
) -> None:
    """Combined membership check."""
    if already_in:
        raise BizValidationError(ERR_MEMBER_ALREADY_EXISTS)
    if joined and left and left < joined:
        raise BizValidationError(ERR_INVALID_DATES)


# ============================================================
# DB Helpers (Call from Service Layer)
# ============================================================

def validate_exists(*, exists: bool, not_found_msg: str) -> None:
    """Generic helper: if record does not exist -> raise not found message."""
    if not exists:
        raise BizValidationError(not_found_msg)


def validate_uniqueness(*, name_taken: bool = False, setup_taken: bool = False) -> None:
    """Check unique constraints before DB commit."""
    if name_taken:
        raise BizValidationError(ERR_GROUP_NAME_EXISTS)
    if setup_taken:
        raise BizValidationError(ERR_GROUP_SETUP_EXISTS)


def validate_can_delete_group(*, member_count: int) -> None:
    """Block delete if group has any membership history."""
    if member_count > 0:
        raise BizValidationError(ERR_DELETE_FORBIDDEN)