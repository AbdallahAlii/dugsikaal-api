# app/business_validation/shareholder_validation.py
from __future__ import annotations

from typing import Optional

from app.business_validation.item_validation import BizValidationError
from app.application_shareholder.models import ShareholderCategoryEnum

# -------------------------
# User-facing error strings
# -------------------------

ERR_SH_COMPANY_REQUIRED = "Company is required for Shareholder."
ERR_SH_FULL_NAME_REQUIRED = "Full name is required for Shareholder."
ERR_SH_CATEGORY_REQUIRED = "Shareholder category is required."
ERR_SH_COMPANY_REG_REQUIRED = (
    "Registration number is required when Shareholder category is 'Company'."
)
ERR_SH_INDIVIDUAL_NATIONAL_ID_RECOMMENDED = (
    "National ID is recommended when Shareholder category is 'Individual'."
)
ERR_SH_INVALID_CATEGORY = "Selected Shareholder category is not valid."


# -------------------------
# Validations
# -------------------------

def validate_shareholder_basic(
    *,
    company_id: Optional[int],
    full_name: Optional[str],
    category: Optional[ShareholderCategoryEnum],
    national_id: Optional[str],
    registration_no: Optional[str],
) -> None:
    """
    Basic ERP-style validations for Shareholder master.
    You can tighten these rules later if needed.
    """
    if not company_id:
        raise BizValidationError(ERR_SH_COMPANY_REQUIRED)

    if not full_name or not full_name.strip():
        raise BizValidationError(ERR_SH_FULL_NAME_REQUIRED)

    if category is None:
        raise BizValidationError(ERR_SH_CATEGORY_REQUIRED)

    # Type-specific rules (soft but helpful)
    if category == ShareholderCategoryEnum.COMPANY:
        if not registration_no or not registration_no.strip():
            raise BizValidationError(ERR_SH_COMPANY_REG_REQUIRED)

    # for Individuals we don't strictly enforce national_id,
    # but we can recommend it via a gentle error later if needed.
    if category == ShareholderCategoryEnum.INDIVIDUAL:
        # You can make this a warning later instead of a hard error.
        # For now we accept missing national_id, so we do nothing.
        pass
