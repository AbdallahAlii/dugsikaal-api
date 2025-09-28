# app/application_stock/warehouse_validation.py
from __future__ import annotations
from decimal import Decimal
from typing import Optional

# Reuse your domain-facing error base
from app.business_validation.item_validation import BizValidationError

# ──────────────────────────────────────────────────────────────────────────────
# Error type with UI-friendly payload
# ──────────────────────────────────────────────────────────────────────────────

class WarehouseRuleError(BizValidationError):
    """
    Business rule error tailored for Warehouse operations.
    Safe for UI to display. Optionally carries a `field` hint for the form.
    """

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        """Handy if your API wants `{message, field}` in responses."""
        payload = {"message": self.message}
        if self.field:
            payload["field"] = self.field
        return payload

# ──────────────────────────────────────────────────────────────────────────────
# User-facing (toast) messages — concise and clear
# ──────────────────────────────────────────────────────────────────────────────

MSG_COMPANY_ROOT_EXISTS = "This company already has a root warehouse."
MSG_BRANCH_GROUP_EXISTS = "This branch already has a warehouse group."
MSG_DUP_NAME_IN_BRANCH = "Warehouse name already exists in this branch."
MSG_DUP_CODE = "Warehouse code already exists."
MSG_LEAF_NEEDS_BRANCH_PARENT = "Physical warehouses must have a parent group and a branch."
MSG_PARENT_CHILD_BRANCH_MISMATCH = "Parent and child must be in the same branch."
MSG_PARENT_MUST_BE_GROUP = "Parent must be a group warehouse."
MSG_HAS_CHILDREN = "Cannot proceed: this warehouse has children."
MSG_STOCK_PRESENT = "Cannot delete: this warehouse contains stock."
MSG_SELF_PARENT = "A warehouse cannot be its own parent."

# ──────────────────────────────────────────────────────────────────────────────
# Validation helpers (stateless guards)
# ──────────────────────────────────────────────────────────────────────────────

def validate_company_root_absent(has_root: bool) -> None:
    """Prevents more than one root warehouse per company."""
    if has_root:
        raise WarehouseRuleError(MSG_COMPANY_ROOT_EXISTS, field="parent_warehouse_id")

def validate_branch_group_absent(has_group: bool) -> None:
    """Prevents more than one group warehouse per branch."""
    if has_group:
        raise WarehouseRuleError(MSG_BRANCH_GROUP_EXISTS, field="branch_id")

def validate_unique_name_in_branch(is_duplicate: bool) -> None:
    """Prevents duplicate warehouse names within a (company, branch)."""
    if is_duplicate:
        raise WarehouseRuleError(MSG_DUP_NAME_IN_BRANCH, field="name")

def validate_unique_code_global(is_duplicate: bool) -> None:
    """Prevents duplicate warehouse codes globally."""
    if is_duplicate:
        raise WarehouseRuleError(MSG_DUP_CODE, field="code")

def validate_leaf_requires_branch_and_parent(
    is_group: bool,
    branch_id: Optional[int],
    parent_id: Optional[int],
) -> None:
    """Ensures a physical warehouse has both a branch and a parent group assigned."""
    if not is_group and (not branch_id or not parent_id):
        raise WarehouseRuleError(MSG_LEAF_NEEDS_BRANCH_PARENT, field="branch_id")

def validate_branch_consistency_with_parent(
    is_group: bool,
    parent_branch_id: Optional[int],
    child_branch_id: Optional[int],
) -> None:
    """Ensures a physical warehouse shares a branch with its parent group."""
    if not is_group and parent_branch_id and child_branch_id:
        if parent_branch_id != child_branch_id:
            raise WarehouseRuleError(MSG_PARENT_CHILD_BRANCH_MISMATCH, field="branch_id")

def validate_parent_is_group(
    parent_id: Optional[int],
    parent_is_group: Optional[bool],
) -> None:
    """Ensures the parent of a physical warehouse is a group."""
    if parent_id is not None and parent_is_group is False:
        raise WarehouseRuleError(MSG_PARENT_MUST_BE_GROUP, field="parent_warehouse_id")

def validate_no_child_warehouses(has_children: bool) -> None:
    """Blocks an operation (e.g., delete) if the warehouse has children."""
    if has_children:
        raise WarehouseRuleError(MSG_HAS_CHILDREN)

def validate_empty_stock_before_delete(stock_qty: Optional[Decimal | int | float]) -> None:
    """Blocks a deletion if the warehouse contains any stock."""
    if stock_qty is not None and Decimal(str(stock_qty)) > 0:
        raise WarehouseRuleError(MSG_STOCK_PRESENT)

def validate_not_self_parent(warehouse_id: Optional[int], parent_id: Optional[int]) -> None:
    """Prevents a warehouse from being its own parent."""
    if warehouse_id is not None and parent_id is not None and warehouse_id == parent_id:
        raise WarehouseRuleError(MSG_SELF_PARENT, field="parent_warehouse_id")

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    "WarehouseRuleError",
    "validate_company_root_absent",
    "validate_branch_group_absent",
    "validate_unique_name_in_branch",
    "validate_unique_code_global",
    "validate_leaf_requires_branch_and_parent",
    "validate_branch_consistency_with_parent",
    "validate_parent_is_group",
    "validate_no_child_warehouses",
    "validate_empty_stock_before_delete",
    "validate_not_self_parent",
]