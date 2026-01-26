from __future__ import annotations

from typing import Optional, Iterable

from app.business_validation.item_validation import BizValidationError


# -----------------------
# Item Group Errors (ERPNext-style)
# -----------------------
ERR_IG_NAME_REQUIRED = "Item Group Name is required."
ERR_IG_NAME_EXISTS = "Item Group name already exists."
ERR_IG_NOT_FOUND = "Item Group not found."
ERR_IG_CODE_EXISTS = "Item Group Code already exists."
ERR_IG_PARENT_INVALID = "Invalid parent item group."
ERR_IG_PARENT_NOT_GROUP = "Parent Item Group must be a group."
ERR_IG_CYCLE = "Invalid parent item group."
ERR_IG_HAS_CHILD_GROUPS = "Item Group has child groups."
ERR_IG_ACCOUNT_INVALID = "Invalid account selected."
ERR_IG_CANNOT_DELETE_ROOT = "Cannot delete root Item Group."


def validate_item_group_name(name: Optional[str]) -> str:
    """Optimized: Validate item group name."""
    if not name or not (nm := str(name).strip()):
        raise BizValidationError(ERR_IG_NAME_REQUIRED)
    return nm


def validate_accounts_all_belong(*, missing_ids: Iterable[int]) -> None:
    """Optimized: Validate accounts with generator."""
    # Use any() with generator for early exit
    if any(True for _ in missing_ids):
        raise BizValidationError(ERR_IG_ACCOUNT_INVALID)
