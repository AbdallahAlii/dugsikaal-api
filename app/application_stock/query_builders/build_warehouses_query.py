# app/application_stock/query_builders/build_warehouses_query.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, and_, func, false, or_, case
from sqlalchemy.orm import Session, aliased

from app.application_stock.stock_models import Warehouse
from app.security.rbac_effective import AffiliationContext
from app.application_org.models.company import Branch, Company


def build_warehouses_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of warehouses with ERP-style presentation

    Uses the same RBAC logic as detail views for consistency
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(Warehouse.id).where(false())

    w = Warehouse
    b = Branch
    c = Company

    # Build location display: "Global" for company-level, branch name for branch-level
    location_display = case(
        (w.branch_id.is_(None), "Global"),
        else_=b.name
    ).label("location")

    # Build the main query with ERP-style columns
    q = (
        select(
            w.id.label("id"),
            w.code.label("code"),
            w.name.label("warehouse_name"),
            w.status.label("status"),
            location_display,
            w.is_group.label("is_group"),
        )
        .select_from(w)
        .join(c, c.id == w.company_id)
        .outerjoin(b, b.id == w.branch_id)
        .where(w.company_id == co_id)
    )

    # For list views, we don't need additional filtering because:
    # 1. System admins and company owners should see everything in their company
    # 2. The context.company_id already ensures they only see their company's warehouses
    # 3. Your RBAC system handles the initial context setup

    # If you want branch-level filtering for non-admin users, use this:
    if not getattr(context, "is_system_admin", False):
        # Check if user has company-wide access (Owner/Super Admin roles)
        roles = getattr(context, "roles", []) or []
        has_company_wide_access = any(role in ["Owner", "Super Admin"] for role in roles)

        if not has_company_wide_access:
            branch_ids = list(getattr(context, "branch_ids", []) or [])
            if branch_ids:
                # Regular users: their branches + global warehouses
                q = q.where(
                    or_(
                        w.branch_id.in_(branch_ids),
                        w.branch_id.is_(None)  # Global warehouses
                    )
                )
            else:
                # Users with no branch access: only global warehouses
                q = q.where(w.branch_id.is_(None))

    return q