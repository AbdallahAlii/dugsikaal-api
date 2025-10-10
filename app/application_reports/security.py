# app/application_reports/security.py
from __future__ import annotations
from werkzeug.exceptions import Forbidden, BadRequest
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

def validate_report_access(*, context: AffiliationContext, company_id: int | None, branch_id: int | None = None) -> None:
    """
    Enforce tenant scope for report execution and export.
    - company_id is required for company-scoped reports
    - branch_id is optional; if supplied, enforce branch scope too
    """
    if company_id is None:
        raise BadRequest("Company parameter is required")

    ensure_scope_by_ids(
        context=context,
        target_company_id=company_id,
        target_branch_id=branch_id,
    )
