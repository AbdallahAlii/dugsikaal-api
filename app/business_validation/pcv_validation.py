from __future__ import annotations

from app.business_validation.item_validation import BizValidationError
from app.application_accounting.chart_of_accounts.schemas.pcv_schemas import PCVCreate

# Single short, ERP-style header
ERR_PCV_MISSING_FIELDS_HEADER = "Mandatory fields required in Period Closing Voucher"


def validate_pcv_create(payload: PCVCreate) -> None:
    """
    Business-level mandatory field checks for PCV create.

    We deliberately only check the PCV-specific fields here.
    Company / scope is handled via resolve_company_branch_and_scope.
    """
    missing: list[str] = []

    if payload.closing_fiscal_year_id is None:
        missing.append("Closing Fiscal Year")

    if payload.closing_account_head_id is None:
        missing.append("Closing Account Head")

    if payload.posting_date is None:
        missing.append("Posting Date")

    # 🔴 Remarks is now mandatory
    if not (payload.remarks or "").strip():
        missing.append("Remarks")

    if missing:
        # e.g. "Mandatory fields required in Period Closing Voucher: Closing Fiscal Year, Posting Date"
        msg = f"{ERR_PCV_MISSING_FIELDS_HEADER}: {', '.join(missing)}"
        raise BizValidationError(msg)
