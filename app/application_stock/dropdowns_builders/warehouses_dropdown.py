from __future__ import annotations
from sqlalchemy import select, case, and_, or_
from sqlalchemy.orm import Session
from typing import Mapping, Any

from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch, Company
from app.common.models.base import StatusEnum
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
    company_wide_roles = {"Owner", "Super Admin", "Operations Manager"}
    return any(role in company_wide_roles for role in roles)


def _get_user_branch_ids(ctx: AffiliationContext) -> list[int]:
    """Get list of branch IDs the user has access to"""
    return list(getattr(ctx, "branch_ids", []) or [])


# --- ALL WAREHOUSES (Default - for most transactions) ---
def build_all_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All warehouses for user's accessible branches + global groups
    - Super Admin/Owner: All warehouses in company
    - Regular users: Global groups + warehouses from their assigned branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),  # Clean label - just the name
            Warehouse.name.label("name"),
            Warehouse.code.label("code"),
            Warehouse.is_group.label("is_group"),
            case((Warehouse.branch_id.is_(None), "Global"), else_=Branch.name).label("branch_name"),
            Warehouse.status.label("status"),
            Warehouse.created_at.label("created_at"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.status == StatusEnum.ACTIVE  # Only active warehouses
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: global groups + warehouses from their branches
            q = q.where(
                (Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True)) |  # Global groups
                (Warehouse.branch_id.in_(branch_ids))  # All warehouses from their branches
            )
        else:
            # Users with no branch access: only global groups
            q = q.where(Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True))

    # Order by: Global first, then by branch, groups before physical, then name
    q = q.order_by(
        case((Warehouse.branch_id.is_(None), 0), else_=1),  # Global first
        Branch.name.asc(),  # Then by branch name
        Warehouse.is_group.desc(),  # Groups before physical
        Warehouse.name.asc()  # Then alphabetically
    )

    return q


# --- PHYSICAL WAREHOUSES ONLY (for stock transactions) ---
def build_physical_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Physical warehouses only (is_group = False) - for stock entries, issues, receipts
    - Super Admin/Owner: All physical warehouses in company
    - Regular users: Only physical warehouses from their assigned branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),  # Clean label - just the name
            Warehouse.name.label("name"),
            Warehouse.code.label("code"),
            Branch.name.label("branch_name"),
            Warehouse.created_at.label("created_at"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .join(Branch, Branch.id == Warehouse.branch_id)  # Physical warehouses must have branch
        .where(
            Warehouse.company_id == co_id,
            Warehouse.is_group.is_(False),  # Only physical warehouses
            Warehouse.status == StatusEnum.ACTIVE
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
            q = q.where(Warehouse.branch_id.in_(branch_ids))
        else:
            q = q.where(Warehouse.id == -1)  # No access

    return q


# --- WAREHOUSE GROUPS ONLY (for organization) ---
def build_warehouse_groups_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Warehouse groups only (is_group = True) - for organizational views
    - Super Admin/Owner: All groups in company
    - Regular users: Global groups + groups from their assigned branches
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),  # Clean label - just the name
            Warehouse.name.label("name"),
            Warehouse.code.label("code"),
            case((Warehouse.branch_id.is_(None), "Global"), else_=Branch.name).label("branch_name"),
            Warehouse.created_at.label("created_at"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.is_group.is_(True),  # Only groups
            Warehouse.status == StatusEnum.ACTIVE
        )
        .order_by(
            case((Warehouse.branch_id.is_(None), 0), else_=1),  # Global first
            Branch.name.asc(),
            Warehouse.name.asc()
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            q = q.where(
                (Warehouse.branch_id.is_(None)) |  # Global groups
                (Warehouse.branch_id.in_(branch_ids))  # Groups from their branches
            )
        else:
            q = q.where(Warehouse.branch_id.is_(None))  # Only global groups

    return q


# --- CHILD WAREHOUSES (for hierarchical selection) ---
def build_child_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Child warehouses of a specific parent - for hierarchical selection
    Expects: params['parent_warehouse_id'] (required)
    """
    co_id = _co(ctx)
    parent_id = params.get("parent_warehouse_id")
    if not co_id or not parent_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),  # Clean label - just the name
            Warehouse.name.label("name"),
            Warehouse.code.label("code"),
            Warehouse.is_group.label("is_group"),
            case((Warehouse.branch_id.is_(None), "Global"), else_=Branch.name).label("branch_name"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.parent_warehouse_id == int(parent_id),
            Warehouse.status == StatusEnum.ACTIVE
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
            q = q.where(Warehouse.branch_id.in_(branch_ids))
        else:
            q = q.where(Warehouse.branch_id.is_(None))  # Only global children

    return q


# --- ACTIVE WAREHOUSES (Optimized for transactions) ---
def build_active_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active warehouses optimized for transactions - newest first
    Same access rules as all_warehouses but optimized ordering
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Warehouse.id.label("value")).where(Warehouse.id == -1)

    q = (
        select(
            Warehouse.id.label("value"),
            Warehouse.name.label("label"),  # Clean label - just the name
            Warehouse.name.label("name"),
            Warehouse.code.label("code"),
            Warehouse.is_group.label("is_group"),
            Branch.name.label("branch_name"),
            Warehouse.created_at.label("created_at"),
        )
        .select_from(Warehouse)
        .join(Company, Company.id == Warehouse.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .where(
            Warehouse.company_id == co_id,
            Warehouse.status == StatusEnum.ACTIVE
        )
    )

    # Apply branch restrictions for non-admin users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            q = q.where(
                (Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True)) |
                (Warehouse.branch_id.in_(branch_ids))
            )
        else:
            q = q.where(Warehouse.branch_id.is_(None) & Warehouse.is_group.is_(True))

    # Order by: newest first (transaction pattern), then name
    q = q.order_by(
        Warehouse.created_at.desc(),  # Newest first
        Warehouse.name.asc()
    )

    return q