from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.business_validation.item_validation import BizValidationError
from app.application_nventory.inventory_models import PriceListType

# -----------------------
# Price List Errors (ERPNext-style)
# -----------------------
ERR_PL_REQUIRED_FIELDS = "Price List Name and Type are required."
ERR_PL_NAME_REQUIRED = "Price List Name is required."
ERR_PL_LIST_TYPE_INVALID = "Price List Type must be Buying, Selling, or Both."
ERR_PL_NOT_FOUND = "Price List not found."
ERR_PL_INACTIVE_DEFAULT = "Default Price List must be Active."
ERR_PL_DEFAULT_EXISTS = "A Default Price List already exists."
ERR_PL_NAME_EXISTS = "Price List already exists."

# -----------------------
# Item Price Errors (ERPNext-style)
# -----------------------
ERR_IP_MANDATORY = "Item, Price List and Rate are required."
ERR_IP_NOT_FOUND = "Item Price not found."
ERR_IP_DUPLICATE = "Duplicate Item Price."
ERR_IP_ITEM_INVALID = "Item not found."
ERR_IP_UOM_INVALID = "Unit of Measure not found."
ERR_IP_UOM_NOT_ALLOWED = "Unit of Measure not valid for this item."
ERR_IP_BRANCH_COMPANY_MISMATCH = "Branch not found."
ERR_IP_PRICE_LIST_INVALID = "Price List not found or inactive."
ERR_IP_VALIDITY_RANGE = "Valid Upto must be greater than or equal to Valid From."


def validate_price_list_basic(*, name: Optional[str], list_type: Optional[str]) -> PriceListType:
    nm = (name or "").strip()
    lt_raw = (list_type or "").strip()

    if not nm and not lt_raw:
        raise BizValidationError(ERR_PL_REQUIRED_FIELDS)
    if not nm:
        raise BizValidationError(ERR_PL_NAME_REQUIRED)
    if not lt_raw:
        raise BizValidationError(ERR_PL_LIST_TYPE_INVALID)

    s = lt_raw.lower()
    if s not in {"buying", "selling", "both"}:
        raise BizValidationError(ERR_PL_LIST_TYPE_INVALID)

    if s == "buying":
        return PriceListType.BUYING
    if s == "selling":
        return PriceListType.SELLING
    return PriceListType.BOTH


def validate_item_price_mandatory(*, item_id: Optional[int], price_list_id: Optional[int], rate: Optional[float]) -> None:
    if not item_id or not price_list_id or rate is None:
        raise BizValidationError(ERR_IP_MANDATORY)


def validate_validity_range(vf_utc: Optional[datetime], vu_utc: Optional[datetime]) -> None:
    if vf_utc and vu_utc and vf_utc > vu_utc:
        raise BizValidationError(ERR_IP_VALIDITY_RANGE)
