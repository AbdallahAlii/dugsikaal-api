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
# ERR_ACCEPTED_QTY_RANGE = (
#     "Accepted quantity must be positive and not exceed the received quantity"
# )
ERR_ACCEPTED_QTY_RANGE = (
    "Accepted quantity must be > 0 and ≤ received for receipts, or < 0 and ≥ received for returns."
)
ERR_RATE_MUST_BE_NON_NEGATIVE = "Rate must be a non-negative value"
ERR_PRICE_MUST_BE_POSITIVE = "Unit price must be a positive value"
ERR_SUBMIT_EMPTY = "Cannot submit a document with no items"
# add next to the other ERR_* messages
ERR_INVALID_CUSTOMER = "Customer is invalid or inactive"

ERR_RETURN_AGAINST_INVALID = "Return can only be made against a Submitted Purchase Receipt."
ERR_RETURN_ITEM_NOT_FOUND = "Invalid item selected for return."
ERR_RETURN_QTY_EXCEEDED = "Return quantity exceeds balance quantity for an item."


ERR_PAID_AMOUNT_EXCEEDED = "Paid amount cannot exceed total amount"
ERR_POS_REQUIRES_PAYMENT = "POS invoices require immediate payment"
ERR_STOCK_ITEM_OUT_OF_STOCK = "Insufficient stock for item"
ERR_WAREHOUSE_REQUIRED_FOR_STOCK = "Warehouse is required when updating stock"
ERR_VAT_CONSISTENCY = "VAT requires VAT account and rate when VAT amount > 0"
ERR_PAYMENT_CONSISTENCY = "Payment method and account required when amount is paid"
ERR_OUTSTANDING_CONSISTENCY = "Outstanding amount must equal total minus paid amount"
ERR_QUANTITY_DIRECTION = "Invoice items require positive quantities, returns require negative quantities"
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


# def validate_accepted_quantity_logic(
#     received_qty: Decimal, accepted_qty: Decimal
# ) -> None:
#     """Validates that accepted qty is > 0 and <= received qty."""
#     if not isinstance(received_qty, Decimal):
#         received_qty = Decimal(str(received_qty))
#     if not isinstance(accepted_qty, Decimal):
#         accepted_qty = Decimal(str(accepted_qty))
#
#     if not (Decimal(0) < accepted_qty <= received_qty):
#         raise BizValidationError(ERR_ACCEPTED_QTY_RANGE)
def validate_accepted_quantity_logic(received_qty: Decimal, accepted_qty: Decimal) -> None:
    """Receipts:   0 < accepted ≤ received  (both positive)
       Returns:  received ≤ accepted < 0     (both negative)
       If received = 0, only accepted = 0 is allowed (defensive)."""
    if not isinstance(received_qty, Decimal):
        received_qty = Decimal(str(received_qty))
    if not isinstance(accepted_qty, Decimal):
        accepted_qty = Decimal(str(accepted_qty))

    zero = Decimal("0")

    if received_qty > zero:
        ok = zero < accepted_qty <= received_qty
    elif received_qty < zero:
        ok = received_qty <= accepted_qty < zero
    else:
        # received_qty == 0
        ok = accepted_qty == zero

    if not ok:
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

    # --- Sales-Specific Validators ---
    def validate_customer_is_active(is_valid: bool) -> None:
        """Checks the result of a repository call for customer validity."""
        if not is_valid:
            raise BizValidationError(ERR_INVALID_CUSTOMER)

    def validate_paid_amount_consistency(paid_amount: Decimal, total_amount: Decimal) -> None:
        """Validates that paid amount doesn't exceed total amount."""
        if paid_amount < Decimal('0'):
            raise BizValidationError("Paid amount cannot be negative")

        if paid_amount > total_amount:
            raise BizValidationError(ERR_PAID_AMOUNT_EXCEEDED)

    def validate_outstanding_consistency(total_amount: Decimal, paid_amount: Decimal,
                                         outstanding_amount: Decimal) -> None:
        """Validates that outstanding = total - paid."""
        expected_outstanding = total_amount - paid_amount
        if outstanding_amount != expected_outstanding:
            raise BizValidationError(ERR_OUTSTANDING_CONSISTENCY)

    def validate_pos_payment_required(is_pos: bool, paid_amount: Decimal, total_amount: Decimal) -> None:
        """Validates that POS invoices require full payment."""
        if is_pos and paid_amount != total_amount:
            raise BizValidationError(ERR_POS_REQUIRES_PAYMENT)

    def validate_stock_availability(quantity: Decimal, available_stock: Decimal, item_code: str = "") -> None:
        """Validates that requested quantity doesn't exceed available stock."""
        if quantity > available_stock:
            item_ref = f" for item {item_code}" if item_code else ""
            raise BizValidationError(
                f"{ERR_STOCK_ITEM_OUT_OF_STOCK}{item_ref} (Available: {available_stock}, Requested: {quantity})")

    def validate_warehouse_for_stock_update(update_stock: bool, warehouse_id: Optional[int]) -> None:
        """Validates that warehouse is provided when stock update is enabled."""
        if update_stock and not warehouse_id:
            raise BizValidationError(ERR_WAREHOUSE_REQUIRED_FOR_STOCK)

    def validate_vat_consistency(vat_amount: Decimal, vat_account_id: Optional[int]) -> None:
        """Validates VAT field consistency."""
        if vat_amount > Decimal('0') and not vat_account_id:
            raise BizValidationError(ERR_VAT_CONSISTENCY)

        if vat_amount == Decimal('0') and vat_account_id:
            raise BizValidationError("VAT account should not be set when VAT amount is zero")

    def validate_payment_consistency(paid_amount: Decimal, mode_of_payment_id: Optional[int],
                                     cash_bank_account_id: Optional[int]) -> None:
        """Validates payment method consistency."""
        if paid_amount > Decimal('0'):
            if not mode_of_payment_id:
                raise BizValidationError("Payment method is required when amount is paid")
            if not cash_bank_account_id:
                raise BizValidationError("Cash/Bank account is required when amount is paid")
        else:
            if mode_of_payment_id or cash_bank_account_id:
                raise BizValidationError("Payment method and account should not be set when no amount is paid")

    def validate_quantity_direction(is_return: bool, quantity: Decimal) -> None:
        """Validates that quantities have correct sign based on document type."""
        if is_return:
            if quantity >= Decimal('0'):
                raise BizValidationError(ERR_QUANTITY_DIRECTION)
        else:
            if quantity <= Decimal('0'):
                raise BizValidationError(ERR_QUANTITY_DIRECTION)

    # --- Comprehensive Sales Validation Gates ---

    def validate_sales_document_basics(customer_id: Optional[int], items: List[Dict[str, Any]]) -> None:
        """Validates basic requirements for any sales document."""
        if not customer_id:
            raise BizValidationError("Customer is required")

        validate_list_not_empty(items, "item")
        validate_unique_items(items, "item_id")

    def validate_sales_amounts(total_amount: Decimal, paid_amount: Decimal, outstanding_amount: Decimal) -> None:
        """Validates sales amount consistency."""
        validate_paid_amount_consistency(paid_amount, total_amount)
        validate_outstanding_consistency(total_amount, paid_amount, outstanding_amount)

    def validate_sales_payment_setup(is_pos: bool, paid_amount: Decimal, total_amount: Decimal,
                                     mode_of_payment_id: Optional[int], cash_bank_account_id: Optional[int]) -> None:
        """Validates payment-related business rules."""
        validate_payment_consistency(paid_amount, mode_of_payment_id, cash_bank_account_id)

        if is_pos:
            validate_pos_payment_required(is_pos, paid_amount, total_amount)

    def validate_sales_stock_requirements(update_stock: bool, warehouse_id: Optional[int],
                                          items: List[Dict[str, Any]], stock_checker=None) -> None:
        """Validates stock-related business rules."""
        validate_warehouse_for_stock_update(update_stock, warehouse_id)

        # If we have a stock checker and warehouse, validate stock availability
        if update_stock and warehouse_id and stock_checker:
            for item in items:
                if item.get('is_stock_item', True):  # Default to True for safety
                    available_stock = stock_checker(item['item_id'], warehouse_id)
                    validate_stock_availability(
                        abs(item.get('quantity', Decimal('0'))),  # Use absolute value for stock check
                        available_stock,
                        item.get('item_code', str(item['item_id']))
                    )

    def validate_sales_items_direction(is_return: bool, items: List[Dict[str, Any]]) -> None:
        """Validates that items have correct quantity direction."""
        for item in items:
            validate_quantity_direction(is_return, item.get('quantity', Decimal('0')))