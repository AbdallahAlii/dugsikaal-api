from __future__ import annotations
from typing import Mapping, Any

from sqlalchemy import select, literal
from sqlalchemy.orm import Session
from app.application_org.models.company import Company, Branch, Department
from app.security.rbac_effective import AffiliationContext  # signature parity with others


def build_companies_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown to show companies that the current user is affiliated with.
      • value: Company.id
      • label: Company.name

    Optional filters (via params):
      - status: exact match filter (str)
    """
    co_id = ctx.company_id  # Fetch the company_id from the current user context

    if not co_id:
        return select(Company.id.label("value")).where(Company.id == -1)

    q = (
        select(
            Company.id.label("value"),
            Company.name.label("label"),
        )
        .where(Company.id == co_id)  # Filter to include only the company the user is affiliated with
        .order_by(Company.name.asc())
    )

    status = params.get("status")
    if status:
        q = q.where(Company.status == status)

    return q


def build_branches_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for branches, scoped to the companies the current user is affiliated with.
      • value: Branch.id
      • label: Branch.name

    Optional filters (via params):
      - company_id: Filter by company
    """
    co_id = ctx.company_id  # Fetch the company_id from the current user context

    if not co_id:
        return select(Branch.id.label("value")).where(Branch.id == -1)

    q = (
        select(
            Branch.id.label("value"),
            Branch.name.label("label"),
        )
        .where(Branch.company_id == co_id)  # Filter to include only branches from the user's affiliated company
        .order_by(Branch.name.asc())
    )

    return q


def build_departments_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown to show departments that belong to the current user's company or predefined departments.
      • value: Department.id
      • label: Department.name

    Optional filters (via params):
      - is_system_defined: Filter by predefined departments
    """
    co_id = ctx.company_id  # Fetch the company_id from the current user context

    if not co_id:
        return select(Department.id.label("value")).where(Department.id == -1)

    # Fetch departments for the company the user is affiliated with
    q = (
        select(
            Department.id.label("value"),
            Department.name.label("label"),
        )
        .where(Department.company_id == co_id)  # Filter to include only departments from the user's company
        .order_by(Department.name.asc())
    )

    # Optionally, filter by predefined departments (if needed)
    is_system_defined = params.get("is_system_defined")
    if is_system_defined is not None:
        q = q.where(Department.is_system_defined == is_system_defined)

    return q