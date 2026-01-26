# app/application_org/dropdowns_builders/org_dropdowns.py
from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, false, case
from sqlalchemy.orm import Session

from app.application_org.models.company import Company, Branch, Department
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _user_branch(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "branch_id", None)


def _deny(model_id_col):
    return select(model_id_col.label("value")).where(false())


def _ensure_company_scope(ctx: AffiliationContext, company_id: int) -> None:
    # Prevent other-company leakage (admins still pass in your guard)
    ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=None)


def _branch_first_order(B, user_branch_id: Optional[int]):
    """
    Smart ordering:
      0 -> user's branch first
      1 -> other branches
    Then by name
    """
    return (
        case((B.id == user_branch_id, 0), else_=1).asc(),
        B.name.asc(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Companies
# ──────────────────────────────────────────────────────────────────────────────

def build_companies_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Companies dropdown:
      • value: Company.id
      • label: Company.name

    Scope:
      - user only sees their current company (ctx.company_id)
      - no cross-company leakage
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny(Company.id)

    _ensure_company_scope(ctx, co_id)

    q = (
        select(
            Company.id.label("value"),
            Company.name.label("label"),
        )
        .where(Company.id == co_id)
        .order_by(Company.name.asc())
    )

    status = params.get("status")
    if status is not None:
        q = q.where(Company.status == status)

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Branches
# ──────────────────────────────────────────────────────────────────────────────

def build_branches_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Branches dropdown (smart):
      • value: Branch.id
      • label: Branch.name

    Scope:
      - all branches under ctx.company_id only
      - user's branch appears first, then others
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny(Branch.id)

    _ensure_company_scope(ctx, co_id)

    user_branch_id = _user_branch(ctx)
    q = (
        select(
            Branch.id.label("value"),
            Branch.name.label("label"),
        )
        .where(Branch.company_id == co_id)
    )

    # Optional filters
    # (Keep compatible: don't change output fields)
    status = params.get("status")
    if status is not None and hasattr(Branch, "status"):
        q = q.where(Branch.status == status)

    # Smart ordering: user's branch first
    q = q.order_by(*_branch_first_order(Branch, user_branch_id))

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Departments
# ──────────────────────────────────────────────────────────────────────────────

def build_departments_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Departments dropdown:
      • value: Department.id
      • label: Department.name

    Scope:
      - departments only from ctx.company_id
      - optional filter: is_system_defined
      - smart ordering: system-defined first (optional), then name
    """
    co_id = _co(ctx)
    if not co_id:
        return _deny(Department.id)

    _ensure_company_scope(ctx, co_id)

    q = (
        select(
            Department.id.label("value"),
            Department.name.label("label"),
        )
        .where(Department.company_id == co_id)
    )

    is_system_defined = params.get("is_system_defined")
    if is_system_defined is not None:
        q = q.where(Department.is_system_defined == bool(is_system_defined))

    # Optional: put system-defined first (ERP-ish), then name
    if hasattr(Department, "is_system_defined"):
        q = q.order_by(
            case((Department.is_system_defined.is_(True), 0), else_=1).asc(),
            Department.name.asc(),
        )
    else:
        q = q.order_by(Department.name.asc())

    return q
