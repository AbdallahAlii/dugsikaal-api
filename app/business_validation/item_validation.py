
# app/business_validation/item_validation.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
    "Accepted quantity must be > 0 and ≤ received for receipts, or < 0 and ≥ received for returns."
)
ERR_RATE_MUST_BE_NON_NEGATIVE = "Rate must be a non-negative value"
ERR_PRICE_MUST_BE_POSITIVE = "Unit price must be a positive value"
ERR_SUBMIT_EMPTY = "Cannot submit a document with no items"
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

ERR_ACCOUNT_NOT_FOUND = "Account not found"
ERR_ACCOUNT_DISABLED = "Account is disabled"
ERR_ACCOUNT_WRONG_COMPANY = "Account does not belong to this company"
ERR_GROUP_ACCOUNT_NOT_ALLOWED = "Cannot use group account for transactions"

ERR_JE_MIN_LINES = "At least two lines are required in Journal Entry."
ERR_JE_ACCOUNT_MANDATORY = "Mandatory fields required in Journal Entry lines, Row {row}: Account."
ERR_JE_ZERO_DR_CR = "Row {row}: Both Debit and Credit values cannot be zero."
ERR_JE_PARTY_REQUIRED = (
    "Row {row}: Party Type and Party are required for Receivable / Payable account {account_name}."
)
ERR_JE_SAME_ACCOUNT_DR_CR = (
    "You cannot credit and debit the same account {account_name} for the same party at the same time."
)
ERR_JE_TOTAL_NOT_BALANCED = (
    "Total Debit must be equal to Total Credit. The difference is {diff}."
)
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
        for _ in items:
            is_empty = False
            break
    except TypeError:
        pass
    if is_empty:
        raise BizValidationError(ERR_ADD_AT_LEAST_ONE.format(name=entity_name))


def validate_unique_items(items: List[Dict[str, Any]], key: str = "item_id") -> None:
    """Ensures all items in a list are unique based on a specific key."""
    seen: Set[Any] = set()
    for item in items:
        value = item.get(key)
        if value is None:
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

def validate_paid_writeoff_ceiling(
    *, grand_total: Decimal, paid_amount: Decimal, write_off_amount: Decimal
) -> None:
    """
    ERPNext-style: Paid + Write Off must not exceed Grand Total.
    This function is SIGN-AWARE:
      - Normal invoices (grand_total >= 0): enforce paid + writeoff <= grand_total
      - Returns (grand_total < 0): enforce |paid| + |writeoff| <= |grand_total|
    """
    zero = Decimal("0")
    paid = Decimal(str(paid_amount or zero))
    woff = Decimal(str(write_off_amount or zero))
    gt = Decimal(str(grand_total or zero))

    # paid can't be negative for normal invoices; can't be positive for returns
    if gt >= zero and paid < zero:
        raise BizValidationError("Paid amount cannot be negative for normal invoices.")
    if gt < zero and paid > zero:
        raise BizValidationError("Paid amount must be negative for returns (refund to customer).")

    if gt >= zero:
        if paid + woff > gt + Decimal("0.0000001"):
            raise BizValidationError("Paid Amount + Write Off Amount cannot be greater than Grand Total.")
    else:
        # returns: compare absolute values
        if (abs(paid) + abs(woff)) > abs(gt) + Decimal("0.0000001"):
            raise BizValidationError("Paid Amount + Write Off Amount cannot exceed absolute Grand Total for returns.")
def guard_updatable_state(status: DocStatusEnum):
    if status != DocStatusEnum.DRAFT:
        raise BizValidationError("Only DRAFT documents can be updated.")

def validate_return_requirements(
    *, is_return: bool, return_against_id: Optional[int]
) -> None:
    if is_return and not return_against_id:
        raise BizValidationError("Return Against is required for a return Sales Invoice.")


def validate_items_quantity_direction(is_return: bool, items: List[Dict[str, Any]]) -> None:
    """
    Enforce ERPNext sign convention:
      - Normal invoice: quantities MUST be positive.
      - Return (credit note): quantities MUST be negative.
    """
    zero = Decimal("0")
    for it in items:
        q = Decimal(str(it.get("quantity", zero)))
        if is_return and q >= zero:
            raise BizValidationError("Return invoice items must have negative quantities.")
        if not is_return and q <= zero:
            raise BizValidationError("Sales invoice items must have positive quantities.")
# --- Master-Data & Business Logic Gates (Purchasing/Inventory) ---


def validate_supplier_is_active(is_valid: bool) -> None:
    """Checks the result of a repository call for supplier validity."""
    if not is_valid:
        raise BizValidationError(ERR_INVALID_SUPPLIER)


def validate_warehouse_is_transactional(is_valid: bool) -> None:
    """Checks the result of a repository call for warehouse validity."""
    if not is_valid:
        raise BizValidationError(ERR_INVALID_WAREHOUSE)


def validate_items_are_active(item_batch: List[Tuple[Any, bool]]) -> None:
    """Validates a batch of items: (item_identifier, is_active_flag)."""
    for item_id, is_active in item_batch:
        if item_id is None:
            raise BizValidationError(ERR_ITEM_NOT_FOUND)
        if not is_active:
            raise BizValidationError(ERR_ITEM_INACTIVE)


def validate_uoms_exist(uom_batch: List[Tuple[Optional[Any], bool]]) -> None:
    """Validates a batch of UOMs: (uom_identifier, exists_flag)."""
    for uom_id, exists in uom_batch:
        if uom_id is not None and not exists:
            raise BizValidationError(ERR_UOM_NOT_FOUND)


def validate_uom_present_for_stock_items(lines: List[Dict[str, Any]]) -> None:
    """Ensures that any line marked as a stock item also has a UOM specified."""
    for line in lines:
        if line.get("is_stock_item") and not line.get("uom_id"):
            raise BizValidationError(ERR_UOM_REQUIRED)


def validate_no_service_items(lines: List[Dict[str, Any]]) -> None:
    """Ensures no lines are for service items."""
    for line in lines:
        if line.get("is_stock_item") is False:
            raise BizValidationError(ERR_SERVICE_ITEM_NOT_ALLOWED)


def validate_item_uom_compatibility(lines: List[Dict[str, Any]]) -> None:
    """
    Ensures the selected UOM is valid for the item.
    Requires:
      - 'is_stock_item': bool
      - 'uom_ok': bool (Result of a check if UOM is base or convertible for the item)
    """
    for line in lines:
        if line.get("is_stock_item") and not line.get("uom_ok", False):
            raise BizValidationError(ERR_UOM_INCOMPATIBLE)

# --- NEW: Account Validation Gates ---

def validate_account_exists(account_exists: bool) -> None:
    """Validates that an account exists."""
    if not account_exists:
        raise BizValidationError(ERR_ACCOUNT_NOT_FOUND)

def validate_account_enabled(account_enabled: bool) -> None:
    """Validates that an account is enabled."""
    if not account_enabled:
        raise BizValidationError(ERR_ACCOUNT_DISABLED)

def validate_account_belongs_to_company(account_belongs: bool) -> None:
    """Validates that an account belongs to the current company."""
    if not account_belongs:
        raise BizValidationError(ERR_ACCOUNT_WRONG_COMPANY)
# --- Sales-Specific Validators (TOP-LEVEL) ---


def validate_customer_is_active(is_valid: bool) -> None:
    """Checks the result of a repository call for customer validity."""
    if not is_valid:
        raise BizValidationError(ERR_INVALID_CUSTOMER)


def validate_paid_amount_consistency(paid_amount: Decimal, total_amount: Decimal) -> None:
    """Validates that paid amount doesn't exceed total amount."""
    if paid_amount < Decimal("0"):
        raise BizValidationError("Paid amount cannot be negative")
    if paid_amount > total_amount:
        raise BizValidationError(ERR_PAID_AMOUNT_EXCEEDED)


def validate_outstanding_consistency(total_amount: Decimal, paid_amount: Decimal, outstanding_amount: Decimal) -> None:
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
            f"{ERR_STOCK_ITEM_OUT_OF_STOCK}{item_ref} (Available: {available_stock}, Requested: {quantity})"
        )


def validate_warehouse_for_stock_update(update_stock: bool, warehouse_id: Optional[int]) -> None:
    """Validates that warehouse is provided when stock update is enabled."""
    if update_stock and not warehouse_id:
        raise BizValidationError(ERR_WAREHOUSE_REQUIRED_FOR_STOCK)


def validate_vat_consistency(vat_amount: Decimal, vat_account_id: Optional[int]) -> None:
    """Validates VAT field consistency."""
    if vat_amount > Decimal("0") and not vat_account_id:
        raise BizValidationError(ERR_VAT_CONSISTENCY)
    if vat_amount == Decimal("0") and vat_account_id:
        raise BizValidationError("VAT account should not be set when VAT amount is zero")


# def validate_payment_consistency(paid_amount: Decimal, mode_of_payment_id: Optional[int],
#                                  cash_bank_account_id: Optional[int]) -> None:
#     """Validates payment method consistency."""
#     if paid_amount > Decimal("0"):
#         if not mode_of_payment_id:
#             raise BizValidationError("Payment method is required when amount is paid")
#         if not cash_bank_account_id:
#             raise BizValidationError("Cash/Bank account is required when amount is paid")
#     else:
#         if mode_of_payment_id or cash_bank_account_id:
#             raise BizValidationError("Payment method and account should not be set when no amount is paid")
# app/business_validation/item_validation.py  (just this function)

from decimal import Decimal
from typing import Optional

# ... existing code & BizValidationError, etc.


def validate_payment_consistency(
    paid_amount: Decimal,
    mode_of_payment_id: Optional[int],
    cash_bank_account_id: Optional[int],
) -> None:
    """
    Validates payment method consistency.

    - If paid_amount == 0: no mode_of_payment_id / cash_bank_account_id allowed.
    - If paid_amount != 0 (positive for normal invoice, negative for return):
        both mode_of_payment_id and cash_bank_account_id are required.

    Sign rules (positive vs negative) are handled separately by:
      - _coerce_signed_paid_for_return (service layer)
      - DB constraints (ck_sin_payment_consistency_signed).
    """
    paid = Decimal(str(paid_amount or 0))

    # No payment / no refund
    if paid == 0:
        if mode_of_payment_id or cash_bank_account_id:
            raise BizValidationError(
                "Payment method and account should not be set when no amount is paid"
            )
        return

    # Some payment or refund exists → require both IDs
    if not mode_of_payment_id:
        raise BizValidationError("Payment method is required when amount is paid")
    if not cash_bank_account_id:
        raise BizValidationError(
            "Cash/Bank account is required when amount is paid"
        )


def validate_quantity_direction(is_return: bool, quantity: Decimal) -> None:
    """Validates that quantities have correct sign based on document type."""
    if is_return:
        if quantity >= Decimal("0"):
            raise BizValidationError(ERR_QUANTITY_DIRECTION)
    else:
        if quantity <= Decimal("0"):
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
    if update_stock and warehouse_id and stock_checker:
        for item in items:
            if item.get("is_stock_item", True):
                available_stock = stock_checker(item["item_id"], warehouse_id)
                validate_stock_availability(
                    abs(item.get("quantity", Decimal("0"))),
                    available_stock,
                    item.get("item_code", str(item["item_id"]))
                )


def validate_sales_items_direction(is_return: bool, items: List[Dict[str, Any]]) -> None:
    """Validates that items have correct quantity direction."""
    for item in items:
        validate_quantity_direction(is_return, item.get("quantity", Decimal("0")))
def validate_stock_entry_rate(entry_type: str, row_idx: int, rate: Decimal) -> None:
    """
    Business rule for Stock Entry rate.

    - Rate must be non-negative for all types.
    - For Material Receipt, rate must be strictly > 0
      (we are introducing value to stock, ERPNext-style).
    """
    r = Decimal(str(rate or "0"))
    validate_non_negative_rate(r)

    if entry_type == "Material Receipt" and r <= 0:
        raise BizValidationError(
            f"Row {row_idx}: Rate must be greater than zero for Material Receipt."
        )


def validate_stock_entry_warehouses(
    entry_type: str,
    row_idx: int,
    source_warehouse_id: Optional[int],
    target_warehouse_id: Optional[int],
) -> None:
    """
    Structural validation for Stock Entry warehouses by type.

    - Material Receipt:
        source_warehouse_id = NULL
        target_warehouse_id = REQUIRED

    - Material Issue:
        source_warehouse_id = REQUIRED
        target_warehouse_id = NULL

    - Material Transfer:
        source_warehouse_id = REQUIRED
        target_warehouse_id = REQUIRED
        source_warehouse_id != target_warehouse_id
    """
    if entry_type == "Material Receipt":
        if source_warehouse_id is not None:
            raise BizValidationError(
                f"Row {row_idx}: Source Warehouse must be empty for Material Receipt."
            )
        if not target_warehouse_id:
            raise BizValidationError(
                f"Row {row_idx}: Target Warehouse is required for Material Receipt."
            )

    elif entry_type == "Material Issue":
        if not source_warehouse_id:
            raise BizValidationError(
                f"Row {row_idx}: Source Warehouse is required for Material Issue."
            )
        if target_warehouse_id is not None:
            raise BizValidationError(
                f"Row {row_idx}: Target Warehouse must be empty for Material Issue."
            )

    elif entry_type == "Material Transfer":
        if not source_warehouse_id or not target_warehouse_id:
            raise BizValidationError(
                f"Row {row_idx}: Both Source and Target Warehouse are required for Material Transfer."
            )
        if source_warehouse_id == target_warehouse_id:
            raise BizValidationError(
                f"Row {row_idx}: Source and Target Warehouse cannot be the same for Material Transfer."
            )