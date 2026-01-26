from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, case, false
from sqlalchemy.orm import Session

from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids


# ──────────────────────────────────────────────────────────────────────────────
# Context helpers
# ──────────────────────────────────────────────────────────────────────────────

def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _user_branch(ctx: AffiliationContext) -> Optional[int]:
    # You already have this in ctx in many places; fallback to None
    return getattr(ctx, "branch_id", None)


def _deny_dropdown():
    # consistent empty dropdown
    return select(Warehouse.id.label("value")).where(false())


def _ensure_company_scope(ctx: AffiliationContext, company_id: int) -> None:
    # company-wide view (admins bypass inside guard)
    ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=None)


# ──────────────────────────────────────────────────────────────────────────────
# Ordering strategy (advanced)
# ──────────────────────────────────────────────────────────────────────────────
def _order_user_branch_first(W, B, user_branch_id: Optional[int]):
    """
    Ranking:
      0 -> current user's branch
      1 -> other branches
      2 -> global (branch_id is null)
    Then: newest first, then name
    """
    # If user has no branch, treat "other branches" as same group (1),
    # and global still last (2).
    branch_rank = case(
        (W.branch_id == user_branch_id, 0),
        (W.branch_id.isnot(None), 1),
        else_=2,
    )

    # Branch name in ordering needs outerjoin Branch; if global -> null, it sorts last anyway
    return (
        branch_rank.asc(),
        B.name.asc(),
        W.created_at.desc(),
        W.name.asc(),
    )


def _location_display(W, B):
    return case((W.branch_id.is_(None), "Global"), else_=B.name).label("branch_name")


# ──────────────────────────────────────────────────────────────────────────────
# 1) ALL WAREHOUSES (default dropdown)
# ──────────────────────────────────────────────────────────────────────────────
def build_all_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all ACTIVE warehouses in the company.

    Visibility:
      - Any user inside the company sees ALL warehouses (global + all branches).
      - No other-company leakage.

    Ordering (best UX):
      - User's branch first
      - then other branches
      - then Global
      - newest first within each
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny_dropdown()

    _ensure_company_scope(ctx, co_id)

    W = Warehouse
    B = Branch
    user_branch_id = _user_branch(ctx)

    q = (
        select(
            W.id.label("value"),
            W.name.label("label"),
            W.name.label("name"),
            W.code.label("code"),
            W.is_group.label("is_group"),
            _location_display(W, B),
            W.status.label("status"),
            W.created_at.label("created_at"),
        )
        .select_from(W)
        .outerjoin(B, B.id == W.branch_id)
        .where(
            W.company_id == co_id,
            W.status == StatusEnum.ACTIVE,
        )
        .order_by(*_order_user_branch_first(W, B, user_branch_id))
    )

    return q


# ──────────────────────────────────────────────────────────────────────────────
# 2) PHYSICAL WAREHOUSES ONLY
# ──────────────────────────────────────────────────────────────────────────────
def build_physical_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: ACTIVE physical warehouses (is_group=False) in the company.
    (Used for stock moves, issues, receipts, etc.)

    Visibility:
      - Any user inside company can see all physical warehouses (all branches).
    Ordering:
      - user's branch first, newest first
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny_dropdown()

    _ensure_company_scope(ctx, co_id)

    W = Warehouse
    B = Branch
    user_branch_id = _user_branch(ctx)

    q = (
        select(
            W.id.label("value"),
            W.name.label("label"),
            W.name.label("name"),
            W.code.label("code"),
            B.name.label("branch_name"),
            W.created_at.label("created_at"),
        )
        .select_from(W)
        .join(B, B.id == W.branch_id)  # physical warehouses must have branch_id
        .where(
            W.company_id == co_id,
            W.status == StatusEnum.ACTIVE,
            W.is_group.is_(False),
        )
        .order_by(*_order_user_branch_first(W, B, user_branch_id))
    )

    return q


# ──────────────────────────────────────────────────────────────────────────────
# 3) GROUPS ONLY
# ──────────────────────────────────────────────────────────────────────────────
def build_warehouse_groups_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: ACTIVE groups only (is_group=True) in the company.

    Visibility:
      - Any user inside company can see all groups (global + branches).
    Ordering:
      - user's branch first
      - then other branches
      - then Global
      - newest first
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny_dropdown()

    _ensure_company_scope(ctx, co_id)

    W = Warehouse
    B = Branch
    user_branch_id = _user_branch(ctx)

    q = (
        select(
            W.id.label("value"),
            W.name.label("label"),
            W.name.label("name"),
            W.code.label("code"),
            _location_display(W, B),
            W.created_at.label("created_at"),
        )
        .select_from(W)
        .outerjoin(B, B.id == W.branch_id)
        .where(
            W.company_id == co_id,
            W.status == StatusEnum.ACTIVE,
            W.is_group.is_(True),
        )
        .order_by(*_order_user_branch_first(W, B, user_branch_id))
    )

    return q


# ──────────────────────────────────────────────────────────────────────────────
# 4) CHILD WAREHOUSES (under parent)
# ──────────────────────────────────────────────────────────────────────────────
def build_child_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: ACTIVE children under a given parent.
    Expects: params['parent_warehouse_id'] (required)

    Visibility:
      - Parent must belong to the user's company (enforced via company scope check).
    Ordering:
      - groups first, then newest, then name
      - BUT also keeps user's-branch-first ordering when branches exist
    """
    co_id = _co(ctx)
    parent_id = params.get("parent_warehouse_id")
    if not co_id or not parent_id:
        return _deny_dropdown()

    _ensure_company_scope(ctx, co_id)

    W = Warehouse
    B = Branch
    user_branch_id = _user_branch(ctx)

    q = (
        select(
            W.id.label("value"),
            W.name.label("label"),
            W.name.label("name"),
            W.code.label("code"),
            W.is_group.label("is_group"),
            _location_display(W, B),
        )
        .select_from(W)
        .outerjoin(B, B.id == W.branch_id)
        .where(
            W.company_id == co_id,
            W.parent_warehouse_id == int(parent_id),
            W.status == StatusEnum.ACTIVE,
        )
        .order_by(
            W.is_group.desc(),
            *_order_user_branch_first(W, B, user_branch_id),
        )
    )

    return q


# ──────────────────────────────────────────────────────────────────────────────
# 5) ACTIVE WAREHOUSES (transaction optimized)
# ──────────────────────────────────────────────────────────────────────────────
def build_active_warehouses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: ACTIVE warehouses optimized for transaction UI usage.

    Visibility:
      - Any user in company sees all.
    Ordering:
      - user's branch first
      - newest first globally
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny_dropdown()

    _ensure_company_scope(ctx, co_id)

    W = Warehouse
    B = Branch
    user_branch_id = _user_branch(ctx)

    q = (
        select(
            W.id.label("value"),
            W.name.label("label"),
            W.name.label("name"),
            W.code.label("code"),
            W.is_group.label("is_group"),
            B.name.label("branch_name"),
            W.created_at.label("created_at"),
        )
        .select_from(W)
        .outerjoin(B, B.id == W.branch_id)
        .where(
            W.company_id == co_id,
            W.status == StatusEnum.ACTIVE,
        )
        .order_by(*_order_user_branch_first(W, B, user_branch_id))
    )

    return q
