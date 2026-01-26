# app/application_stock/helpers/warehouse_validation.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any

from app.business_validation.item_validation import BizValidationError


class WarehouseRuleError(BizValidationError):
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"message": self.message, **({"field": self.field} if self.field else {})}


MSG_COMPANY_ROOT_EXISTS = "This company already has a root warehouse."
MSG_DUP_NAME_IN_BRANCH = "Warehouse name already exists in this branch."
MSG_DUP_CODE = "Warehouse code already exists."
MSG_PARENT_MUST_BE_GROUP = "Parent must be a group warehouse."
MSG_PARENT_CHILD_BRANCH_MISMATCH = "Parent and child must be in the same branch."
MSG_HAS_CHILDREN = "Cannot proceed: this warehouse has children."
MSG_STOCK_PRESENT = "Cannot delete: this warehouse contains stock."
MSG_SELF_PARENT = "A warehouse cannot be its own parent."
MSG_CANNOT_DELETE_ROOT = "Cannot delete: this is the company root warehouse."
MSG_LINKED_DOC = "Cannot delete: this warehouse is linked with {doctype} {code}."
MSG_BRANCH_REQUIRED_FOR_LEAF = "branch is required to create a  warehouse."


def validate_company_root_absent(has_root: bool) -> None:
    if has_root:
        raise WarehouseRuleError(MSG_COMPANY_ROOT_EXISTS, field="parent_warehouse_id")


def validate_unique_name_in_branch(is_duplicate: bool) -> None:
    if is_duplicate:
        raise WarehouseRuleError(MSG_DUP_NAME_IN_BRANCH, field="name")


def validate_unique_code_global(is_duplicate: bool) -> None:
    if is_duplicate:
        raise WarehouseRuleError(MSG_DUP_CODE, field="code")


def validate_parent_is_group(parent_id: Optional[int], parent_is_group: Optional[bool]) -> None:
    if parent_id is not None and parent_is_group is False:
        raise WarehouseRuleError(MSG_PARENT_MUST_BE_GROUP, field="parent_warehouse_id")


def validate_branch_required_for_leaf(is_group: bool, branch_id: Optional[int]) -> None:
    if not is_group and not branch_id:
        raise WarehouseRuleError(MSG_BRANCH_REQUIRED_FOR_LEAF, field="branch_id")


def validate_branch_consistency_with_parent(
    is_group: bool,
    parent_branch_id: Optional[int],
    child_branch_id: Optional[int],
) -> None:
    if not is_group and parent_branch_id and child_branch_id and parent_branch_id != child_branch_id:
        raise WarehouseRuleError(MSG_PARENT_CHILD_BRANCH_MISMATCH, field="branch_id")


def validate_no_child_warehouses(has_children: bool) -> None:
    if has_children:
        raise WarehouseRuleError(MSG_HAS_CHILDREN)


def validate_empty_stock_before_delete(stock_qty: Optional[Decimal | int | float]) -> None:
    if stock_qty is not None and Decimal(str(stock_qty)) > 0:
        raise WarehouseRuleError(MSG_STOCK_PRESENT)


def validate_not_self_parent(warehouse_id: Optional[int], parent_id: Optional[int]) -> None:
    if warehouse_id is not None and parent_id is not None and warehouse_id == parent_id:
        raise WarehouseRuleError(MSG_SELF_PARENT, field="parent_warehouse_id")


def validate_not_company_root(is_root: bool) -> None:
    if is_root:
        raise WarehouseRuleError(MSG_CANNOT_DELETE_ROOT)


def validate_not_linked_to_document(link: Optional[Dict[str, Any]]) -> None:
    if link:
        raise WarehouseRuleError(MSG_LINKED_DOC.format(doctype=link.get("doctype"), code=link.get("code")))
