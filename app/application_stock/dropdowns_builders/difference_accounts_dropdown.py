from __future__ import annotations

from typing import Mapping, Any, List

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.application_org.models.company import Company
from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.models import Account


# --- Common scoping helpers (same style as warehouses) ---


def _co(ctx: AffiliationContext) -> int | None:
    """Current company_id from context (if any)."""
    return getattr(ctx, "company_id", None)


def _is_system_admin(ctx: AffiliationContext) -> bool:
    return getattr(ctx, "is_system_admin", False)


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    """
    Check if user has company-wide access (Owner/Super Admin roles).

    NOTE: For now we don't branch-scope accounts (Account has no branch_id),
    but we keep this helper for future use if you add branch dimension.
    """
    if _is_system_admin(ctx):
        return True

    roles: List[str] = list(getattr(ctx, "roles", []) or [])
    company_wide_roles = {"Owner", "Super Admin", "Operations Manager"}
    return any(role in company_wide_roles for role in roles)


def _get_user_branch_ids(ctx: AffiliationContext) -> list[int]:
    """Get list of branch IDs the user has access to (future use)."""
    return list(getattr(ctx, "branch_ids", []) or [])


# --- Difference Accounts dropdown builder ---


def build_difference_accounts_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Difference Accounts (Stock Adjustment accounts) for Stock Reconciliation.

    Rules:
    - Only for the current company.
    - Only ENABLED accounts.
    - Always include:
        * Account.name == "Temporary Opening"
        * Account.name == "Stock Adjustments"
    - PLUS any account that has ever been used as a difference account
      on Stock Reconciliation (via relationship Account.stock_reconciliations).

    This matches Frappe-style behaviour: show "standard" difference accounts
    and also any accounts that have been used on this doctype historically.
    """

    co_id = _co(ctx)
    if not co_id:
        # Return an empty selectable to keep signature consistent
        return select(Account.id.label("value")).where(Account.id == -1)

    # Subquery: all Account IDs that are linked to any Stock Reconciliation
    # via the relationship Account.stock_reconciliations.
    #
    # We don't need the StockReconciliation class explicitly here:
    # the relationship is enough for SQLAlchemy to generate the join.
    used_diff_accounts_subq = (
        select(Account.id)
        .join(Account.stock_reconciliations)  # relationship-based join
        .distinct()
    )

    # Main query
    q = (
        select(
            Account.id.label("value"),
            Account.name.label("label"),  # clean label for dropdown
            Account.name.label("name"),
            Account.code.label("code"),
        )
        .select_from(Account)
        .join(Company, Company.id == Account.company_id)
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
            or_(
                # Standard difference accounts by name
                Account.name.in_(["Temporary Opening", "Stock Adjustments"]),
                # Any account that has ever been used as difference_account
                Account.id.in_(used_diff_accounts_subq),
            ),
        )
        .order_by(
            Account.code.asc(),
            Account.name.asc(),
        )
    )

    # NOTE:
    # For now we do NOT filter by branch, because Account has no branch_id.
    # If later you add Account.branch_id, you can add branch scoping similar
    # to the warehouses builders using _has_company_wide_access() and
    # _get_user_branch_ids().

    return q
