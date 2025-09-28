# app/business_validation/item_validation.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# Adjust the import path to match your project structure
from app.application_stock.stock_models import DocStatusEnum

# --- Domain Exceptions (User-Friendly for APIs and UI) ---


class BizValidationError(ValueError):
    """Represents a business rule violation that is safe to display to the end-user."""

    pass


class DocumentStateError(BizValidationError):
    """Raised for an operation invalid in the document's current state."""

    pass


# --- User-Facing Messages (for UI Toasts/Alerts) ---

ERR_ADD_AT_LEAST_ONE = "Add at least one {name}"
ERR_DUPLICATE_ITEM = "Item is entered more than once"
ERR_INVALID_SUPPLIER = "Supplier is invalid or inactive"
ERR_INVALID_WAREHOUSE = (
    "Select an active, transactional warehouse. Group warehouses are not allowed."
)
ERR_ITEM_NOT_FOUND = "Item not found"
ERR_ITEM_INACTIVE = "Item is not active"
ERR_UOM_NOT_FOUND = "Unit of Measure is invalid"
ERR_UOM_REQUIRED = "Unit of Measure is required for stock items"
ERR_UOM_INCOMPATIBLE = "Unit of Measure is not valid for this item"
ERR_SERVICE_ITEM_NOT_ALLOWED = "Only stock items are allowed in this document"
ERR_QTY_MUST_BE_POSITIVE = "Quantity must be greater than zero"
ERR_ACCEPTED_QTY_RANGE = (
    "Accepted quantity must be positive and not exceed the received quantity"
)
ERR_RATE_MUST_BE_NON_NEGATIVE = "Rate must be a non-negative value"
ERR_PRICE_MUST_BE_POSITIVE = "Unit price must be a positive value"
ERR_SUBMIT_EMPTY = "Cannot submit a document with no items"
# add next to the other ERR_* messages
ERR_INVALID_CUSTOMER = "Customer is invalid or inactive"


# --- Document Status Guards ---


def guard_draft_only(status: DocStatusEnum) -> None:
    """Raise an error if the document is not in 'Draft' status."""
    if status != DocStatusEnum.DRAFT:
        raise DocumentStateError("This operation is only allowed on Draft documents.")


def guard_submittable_state(status: DocStatusEnum) -> None:
    """Raise an error if the document cannot be submitted (i.e., is not 'Draft')."""
    if status != DocStatusEnum.DRAFT:
        raise DocumentStateError("Only Draft documents can be submitted.")


def guard_cancellable_state(status: DocStatusEnum) -> None:
    """Raise an error if the document cannot be cancelled (i.e., is not 'Submitted')."""
    if status != DocStatusEnum.SUBMITTED:
        raise DocumentStateError("Only Submitted documents can be cancelled.")

def validate_customer_is_active(is_valid: bool) -> None:
    """Checks the result of a repository call for customer validity."""
    if not is_valid:
        raise BizValidationError(ERR_INVALID_CUSTOMER)

# --- Field & List Validators ---


def validate_list_not_empty(items: Iterable[Any], entity_name: str) -> None:
    """Checks if an iterable (list, generator) contains at least one item."""
    is_empty = True
    try:
        # Efficiently check for the first item without consuming the whole iterable
        for _ in items:
            is_empty = False
            break
    except TypeError:
        # The object is not iterable, hence it's considered empty for this context.
        pass
    if is_empty:
        raise BizValidationError(ERR_ADD_AT_LEAST_ONE.format(name=entity_name))


def validate_unique_items(items: List[Dict[str, Any]], key: str = "item_id") -> None:
    """Ensures all items in a list are unique based on a specific key."""
    seen: Set[Any] = set()
    for item in items:
        value = item.get(key)
        if value is None:
            # This indicates a schema issue, but we validate defensively.
            raise BizValidationError(ERR_ITEM_NOT_FOUND)
        if value in seen:
            raise BizValidationError(ERR_DUPLICATE_ITEM)
        seen.add(value)


def validate_positive_quantity(quantity: Decimal) -> None:
    """Validates that a given quantity is greater than zero."""
    if not isinstance(quantity, Decimal):
        quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise BizValidationError(ERR_QTY_MUST_BE_POSITIVE)


def validate_accepted_quantity_logic(
    received_qty: Decimal, accepted_qty: Decimal
) -> None:
    """Validates that accepted qty is > 0 and <= received qty."""
    if not isinstance(received_qty, Decimal):
        received_qty = Decimal(str(received_qty))
    if not isinstance(accepted_qty, Decimal):
        accepted_qty = Decimal(str(accepted_qty))

    if not (Decimal(0) < accepted_qty <= received_qty):
        raise BizValidationError(ERR_ACCEPTED_QTY_RANGE)


def validate_positive_price(unit_price: Optional[Decimal]) -> None:
    """Validates that the unit price, if provided, is a positive number."""
    if unit_price is not None:
        if not isinstance(unit_price, Decimal):
            unit_price = Decimal(str(unit_price))
        if unit_price <= 0:
            raise BizValidationError(ERR_PRICE_MUST_BE_POSITIVE)

def validate_non_negative_rate(rate: Optional[Decimal]) -> None:
    """Validates that the rate, if provided, is not negative."""
    if rate is not None:
        if not isinstance(rate, Decimal):
            rate = Decimal(str(rate))
        if rate < 0:
            raise BizValidationError(ERR_RATE_MUST_BE_NON_NEGATIVE)
# --- Master-Data & Business Logic Gates ---


def validate_supplier_is_active(is_valid: bool) -> None:
    """Checks the result of a repository call for supplier validity."""
    if not is_valid:
        raise BizValidationError(ERR_INVALID_SUPPLIER)


def validate_warehouse_is_transactional(is_valid: bool) -> None:
    """
    Checks the result of a repository call for warehouse validity.
    A transactional warehouse is active and not a 'group' warehouse.
    """
    if not is_valid:
        raise BizValidationError(ERR_INVALID_WAREHOUSE)


def validate_items_are_active(item_batch: List[Tuple[Any, bool]]) -> None:
    """
    Validates a batch of items from a repository check.
    Each tuple should be (item_identifier, is_active_flag).
    """
    for item_id, is_active in item_batch:
        if item_id is None:
            raise BizValidationError(ERR_ITEM_NOT_FOUND)
        if not is_active:
            raise BizValidationError(ERR_ITEM_INACTIVE)


def validate_uoms_exist(uom_batch: List[Tuple[Optional[Any], bool]]) -> None:
    """
    Validates a batch of UOMs from a repository check.
    Each tuple should be (uom_identifier, exists_flag).
    """
    for uom_id, exists in uom_batch:
        # We only care about UOMs that are provided but don't exist.
        if uom_id is not None and not exists:
            raise BizValidationError(ERR_UOM_NOT_FOUND)


def validate_uom_present_for_stock_items(lines: List[Dict[str, Any]]) -> None:
    """Ensures that any line marked as a stock item also has a UOM specified."""
    for line in lines:
        if line.get("is_stock_item") and not line.get("uom_id"):
            raise BizValidationError(ERR_UOM_REQUIRED)


def validate_no_service_items(lines: List[Dict[str, Any]]) -> None:
    """Ensures no lines are for service items (where 'is_stock_item' is False)."""
    for line in lines:
        if line.get("is_stock_item") is False:
            raise BizValidationError(ERR_SERVICE_ITEM_NOT_ALLOWED)


def validate_item_uom_compatibility(lines: List[Dict[str, Any]]) -> None:
    """
    Ensures the selected UOM is valid for the item.
    Assumes each line dict contains:
      - 'is_stock_item': bool
      - 'uom_ok': bool (Result of a check if UOM is base or convertible for the item)
    """
    for line in lines:
        # This validation only applies to stock items with a specified UOM.
        if line.get("is_stock_item") and not line.get("uom_ok", False):
            raise BizValidationError(ERR_UOM_INCOMPATIBLE)