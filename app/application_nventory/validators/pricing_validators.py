from __future__ import annotations
from datetime import datetime
from typing import Optional

from app.business_validation.item_validation import BizValidationError

ERR_PL_NAME_REQUIRED = "Price List name is required"
ERR_PL_TYPE_REQUIRED = "Price List must be applicable for Buying or Selling"
ERR_PL_DUPLICATE = "Price List already exists"

ERR_IP_MANDATORY = "Mandatory fields required in Item Price"
ERR_IP_DUPLICATE = "Item Price already exists"
ERR_IP_RATE_POSITIVE = "Rate must be greater than 0"
ERR_IP_PL_DISABLED = "Price List is disabled"
ERR_IP_DATE_ORDER = "Valid Upto must be on or after Valid From"

class PriceListValidator:
    @staticmethod
    def validate_name_and_type(name: str, list_type: Optional[str]) -> None:
        if not (name or "").strip():
            raise BizValidationError(ERR_PL_NAME_REQUIRED)
        if not list_type:
            raise BizValidationError(ERR_PL_TYPE_REQUIRED)

class ItemPriceValidator:
    @staticmethod
    def validate_mandatory(price_list_id: Optional[int], item_id: Optional[int], rate: Optional[float]) -> None:
        if not price_list_id or not item_id or rate is None:
            raise BizValidationError(ERR_IP_MANDATORY)

    @staticmethod
    def validate_rate(rate: float) -> None:
        try:
            r = float(rate)
        except Exception:
            raise BizValidationError(ERR_IP_RATE_POSITIVE)
        if r <= 0:
            raise BizValidationError(ERR_IP_RATE_POSITIVE)

    @staticmethod
    def validate_validity(from_dt: Optional[datetime], upto_dt: Optional[datetime]) -> None:
        if from_dt and upto_dt and upto_dt < from_dt:
            raise BizValidationError(ERR_IP_DATE_ORDER)
