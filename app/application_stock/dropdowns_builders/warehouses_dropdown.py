# app/application_stock/dropdown_builders/warehouses_dropdown.py
from __future__ import annotations
from sqlalchemy import select, case
from sqlalchemy.orm import Session
from typing import Mapping, Any

from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch, Company
from app.security.rbac_effective import AffiliationContext


# --- Common scoping helpers ---
def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)


def _br(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "branch_id", None)


def _is_system_admin(ctx: AffiliationContext) -> bool:
    return getattr(ctx, "is_system_admin", False)


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    """Check if user has company-wide access (Owner/Super Admin roles)"""
    if _is_system_admin(ctx):
        return True

    roles = getattr(ctx, "roles", []) or []
    return any(role in ["Owner", "Super Admin"] for role in roles)


def _get_user_branch_ids(ctx: AffiliationContext) -> list[int]:
    """Get list of branch IDs the user has access to"""
    return list(getattr(ctx, "branch_ids", []) or [])


# Warehouse Groups Dropdown (is_group = True)
def build_warehouse_groups_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for warehouse groups (is_group = True)
    - System admins & company owners: all groups in company
    - Regular users: global groups + groups from their branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    # Build location display
    location_display = case(
        (Warehouse.branch_id.is_(None), "Global"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),
            location_display,
            Warehouse.code.label("code"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.is_group.is_(True)  # Only groups
        )
        .order_by(
            # Global first, then by branch name, then by warehouse name
            case((Warehouse.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Warehouse.name.asc()
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: global groups + groups from their branches
            q = q.where(
                (Warehouse.branch_id.is_(None)) |  # Global groups
                (Warehouse.branch_id.in_(branch_ids))  # Groups from their branches
            )
        else:
            # Users with no branch access: only global groups
            q = q.where(Warehouse.branch_id.is_(None))

    return q


# Physical Warehouses Dropdown (is_group = False)
def build_physical_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for physical warehouses (is_group = False)
    - System admins & company owners: all physical warehouses in company
    - Regular users: only physical warehouses from their branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    # Build location display
    location_display = case(
        (Warehouse.branch_id.is_(None), "Global"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),
            location_display,
            Warehouse.code.label("code"),
            Warehouse.parent_warehouse_id.label("parent_id"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.is_group.is_(False)  # Only physical warehouses
        )
        .order_by(
            Branch.name.asc(),
            Warehouse.name.asc()
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: only physical warehouses from their branches
            q = q.where(Warehouse.branch_id.in_(branch_ids))
        else:
            # Users with no branch access: no physical warehouses (they're all branch-specific)
            q = q.where(Warehouse.id == -1)  # Empty result

    return q


# All Warehouses Dropdown (both groups and physical)
def build_all_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for all warehouses (both groups and physical)
    - System admins & company owners: all warehouses in company
    - Regular users: global groups + warehouses from their branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    # Build location display and type indicator
    location_display = case(
        (Warehouse.branch_id.is_(None), "Global"),
        else_=Branch.name
    ).label("location")

    type_display = case(
        (Warehouse.is_group.is_(True), "Group"),
        else_="Physical"
    ).label("type")

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),
            location_display,
            type_display,
            Warehouse.code.label("code"),
            Warehouse.is_group.label("is_group"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(Warehouse.company_id == co_id)
        .order_by(
            # Groups first, then physical
            case((Warehouse.is_group.is_(True), 0), else_=1),
            # Global first, then by branch
            case((Warehouse.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Warehouse.name.asc()
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: global groups + warehouses from their branches
            q = q.where(
                (Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True)) |  # Global groups only
                (Warehouse.branch_id.in_(branch_ids))  # All warehouses from their branches
            )
        else:
            # Users with no branch access: only global groups
            q = q.where(Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True))

    return q


# Child Warehouses Dropdown (for a specific parent)
def build_child_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for child warehouses of a specific parent
    Expects: params['parent_warehouse_id'] (required)
    """
    co_id = _co(ctx)
    parent_id = params.get("parent_warehouse_id")
    if not co_id or not parent_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    # Build location display
    location_display = case(
        (Warehouse.branch_id.is_(None), "Global"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),
            location_display,
            Warehouse.code.label("code"),
            Warehouse.is_group.label("is_group"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.parent_warehouse_id == int(parent_id)
        )
        .order_by(
            Warehouse.is_group.desc(),  # Groups first
            Warehouse.name.asc()
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: only warehouses from their branches
            q = q.where(Warehouse.branch_id.in_(branch_ids))
        else:
            # Users with no branch access: no warehouses
            q = q.where(Warehouse.id == -1)

    return q