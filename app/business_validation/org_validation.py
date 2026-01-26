# app/business_validation/org_validation.py
from __future__ import annotations

from typing import Optional

from app.business_validation.item_validation import BizValidationError

# ---- User-facing messages (ORG specific) ----

ERR_COMPANY_NAME_REQUIRED = "Company name is required."
ERR_COMPANY_PREFIX_REQUIRED = "Company prefix is required."
ERR_COMPANY_TIMEZONE_REQUIRED = "Company timezone is required."
ERR_COMPANY_PREFIX_FORMAT = "Company prefix must be 2–20 uppercase letters or digits."

ERR_BRANCH_COMPANY_REQUIRED = "Branch must be linked to a company."
ERR_BRANCH_NAME_REQUIRED = "Branch name is required."
ERR_BRANCH_CODE_REQUIRED = "Branch code is required."
ERR_BRANCH_HQ_ALREADY_EXISTS = "This company already has an HQ branch."


# ----------------------------------------------------------------------
# Company validations
# ----------------------------------------------------------------------


def validate_company_basic(
    *,
    name: Optional[str],
    prefix: Optional[str],
    timezone: Optional[str],
) -> None:
    if not (name or "").strip():
        raise BizValidationError(ERR_COMPANY_NAME_REQUIRED)
    if not (prefix or "").strip():
        raise BizValidationError(ERR_COMPANY_PREFIX_REQUIRED)
    if not (timezone or "").strip():
        raise BizValidationError(ERR_COMPANY_TIMEZONE_REQUIRED)


def validate_company_prefix_format(prefix: str) -> None:
    """
    Simple ERP-style rule:
    - 2..20 chars
    - Only A–Z and 0–9
    """
    p = (prefix or "").strip()
    if not p:
        raise BizValidationError(ERR_COMPANY_PREFIX_REQUIRED)
    if not (2 <= len(p) <= 20):
        raise BizValidationError(ERR_COMPANY_PREFIX_FORMAT)
    if not p.isalnum() or not p.upper() == p:
        # allow digits but require uppercase letters
        raise BizValidationError(ERR_COMPANY_PREFIX_FORMAT)


# ----------------------------------------------------------------------
# Branch validations
# ----------------------------------------------------------------------


def validate_branch_basic(
    *,
    company_id: Optional[int],
    name: Optional[str],
    code: Optional[str],
) -> None:
    if not company_id:
        raise BizValidationError(ERR_BRANCH_COMPANY_REQUIRED)
    if not (name or "").strip():
        raise BizValidationError(ERR_BRANCH_NAME_REQUIRED)
    if not (code or "").strip():
        raise BizValidationError(ERR_BRANCH_CODE_REQUIRED)


def validate_branch_hq_flag(
    *,
    is_hq: bool,
    has_existing_hq: bool,
) -> None:
    if is_hq and has_existing_hq:
        raise BizValidationError(ERR_BRANCH_HQ_ALREADY_EXISTS)
