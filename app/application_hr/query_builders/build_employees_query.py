# app/hr/query_builders/build_hr_queries.py
from __future__ import annotations

from typing import Optional, Iterable
from sqlalchemy import select, false
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.application_hr.models.hr import EmployeeAssignment, Employee
from app.security.rbac_effective import AffiliationContext

from app.application_org.models.company import Branch


def _scope_predicates(co_id: Optional[int], branch_ids: Iterable[int]) -> ColumnElement[bool]:
    if co_id is None:
        return false()
    # Base predicate: tenant scope
    pred = (Employee.company_id == co_id)

    # If branches are scoped, restrict to those via the primary, active assignment
    branch_ids = list(branch_ids or [])
    if branch_ids:
        pred = pred & (EmployeeAssignment.branch_id.in_(branch_ids))
    return pred


def _company_and_branch(context: AffiliationContext) -> tuple[Optional[int], list[int]]:
    return getattr(context, "company_id", None), list(getattr(context, "branch_ids", []) or [])


def build_employees_query(session: Session, context: AffiliationContext):
    """
    Build employees list query:
    - columns: id, code, full_name, status, company_id, branch_id, branch_name
    - scope: company + (optional) branch_ids via primary active assignment
    - joins: Employee -> EmployeeAssignment (primary, active) -> Branch
    """
    co_id, branch_ids = _company_and_branch(context)

    EA = EmployeeAssignment
    E = Employee
    B = Branch

    pred = _scope_predicates(co_id, branch_ids)

    return (
        select(
            E.id.label("id"),
            E.code.label("code"),
            E.full_name.label("full_name"),
            E.status.label("status"),
            E.company_id.label("company_id"),
            EA.branch_id.label("branch_id"),
            B.name.label("branch_name"),
        )
        .select_from(E)
        .join(
            EA,
            (EA.employee_id == E.id)
            & (EA.is_primary.is_(True))
            & (EA.to_date.is_(None)),
        )
        .join(B, B.id == EA.branch_id)
        .where(pred)
    )