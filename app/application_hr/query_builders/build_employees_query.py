from __future__ import annotations

from typing import Optional

from sqlalchemy import select, and_, false, func
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_hr.models.hr import (
    Employee,
    EmployeeAssignment,
    HolidayList,
    Holiday,
    ShiftType,
    PayrollPeriod,
)
from app.application_org.models.company import Branch, Department


# SQL-side display formats to match your Python helper:
# DISPLAY_FMT = "%m/%d/%Y"  →  "MM/DD/YYYY" in Postgres
DATE_OUT_FMT_SQL = "MM/DD/YYYY"
# Time: simple HH:MM (24h) for list view
TIME_OUT_FMT_SQL = "HH24:MI"


def _get_company_id_from_context(context: AffiliationContext) -> Optional[int]:
    """
    Small helper to safely extract the current company id from the affiliation context.
    """
    return getattr(context, "company_id", None)


# ─────────────────────────────────────────────────────────────
# Employees list (company-wide, HR-style, no branch hard-coding)
# ─────────────────────────────────────────────────────────────


def build_employees_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of employees with key columns:
      id, code, full_name, status, branch_name

    Rules:
      - Enforced to a single company using context.company_id.
      - Uses CURRENT PRIMARY assignment for branch/department
        (is_primary = true AND to_date IS NULL).
      - HR can see employees across all branches within the company.
      - Visibility across companies is enforced via ensure_scope_by_ids.
    """
    co_id: Optional[int] = _get_company_id_from_context(context)
    if co_id is None:
        # No company in context → return empty query that never matches.
        return select(Employee.id).where(false())

    # Enforce that the caller is allowed to operate at this company scope.
    # Branch-level roles won't even have the "Employee" permission_tag,
    # HR Manager (COMPANY scope) will pass here.
    ensure_scope_by_ids(
        context=context,
        target_company_id=co_id,
        target_branch_id=None,  # company-wide HR visibility
    )

    ea = EmployeeAssignment
    b = Branch
    d = Department  # kept in case you later add department_name column

    branch_name_expr = b.name.label("branch_name")

    q = (
        select(
            Employee.id.label("id"),
            Employee.code.label("code"),
            Employee.full_name.label("full_name"),
            Employee.status.label("status"),
            branch_name_expr,
        )
        .select_from(Employee)
        .outerjoin(
            ea,
            and_(
                ea.employee_id == Employee.id,
                ea.company_id == co_id,
                ea.is_primary.is_(True),
                ea.to_date.is_(None),
            ),
        )
        .outerjoin(b, b.id == ea.branch_id)
        .outerjoin(d, d.id == ea.department_id)
        .where(Employee.company_id == co_id)
    )

    # NOTE:
    # - We don't add any branch_ids filter here so HR can see all branches.
    # - Uniqueness of "primary assignment" is enforced at DB level by:
    #   `uq_emp_primary_assignment (is_primary = true AND to_date IS NULL)`
    #   so we don't need GROUP BY here.
    return q


# ────────────────────────────────────────────────
# Holiday List (Name / From Date / To Date / Count)
# ────────────────────────────────────────────────


def build_holiday_lists_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of holiday lists with ERP-style columns:

      - id
      - name
      - from_date  (string, MM/DD/YYYY)
      - to_date    (string, MM/DD/YYYY)
      - total_holidays  (COUNT of Holiday rows)

    Only the current company is visible; there is no branch concept here.
    """
    co_id: Optional[int] = _get_company_id_from_context(context)
    if co_id is None:
        return select(HolidayList.id).where(false())

    ensure_scope_by_ids(
        context=context,
        target_company_id=co_id,
        target_branch_id=None,
    )

    HL = HolidayList
    H = Holiday

    total_holidays_expr = func.count(H.id).label("total_holidays")
    from_date_expr = func.to_char(HL.from_date, DATE_OUT_FMT_SQL).label("from_date")
    to_date_expr = func.to_char(HL.to_date, DATE_OUT_FMT_SQL).label("to_date")

    q = (
        select(
            HL.id.label("id"),
            HL.name.label("name"),
            from_date_expr,
            to_date_expr,
            total_holidays_expr,
        )
        .select_from(HL)
        .outerjoin(H, H.holiday_list_id == HL.id)
        .where(HL.company_id == co_id)
        .group_by(HL.id, HL.name, HL.from_date, HL.to_date)
    )

    return q


# ────────────────────────────────────────
# Shift Type (Name / Start Time / End Time)
# ────────────────────────────────────────


def build_shift_types_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of shift types with minimal list-view columns:

      - id
      - name
      - start_time  (string, HH:MM)
      - end_time    (string, HH:MM)

    HR Manager sees all shift types within the company.

    NOTE:
      We convert SQL TIME fields to strings to avoid
      `Object of type time is not JSON serializable` errors in Flask.
    """
    co_id: Optional[int] = _get_company_id_from_context(context)
    if co_id is None:
        return select(ShiftType.id).where(false())

    ensure_scope_by_ids(
        context=context,
        target_company_id=co_id,
        target_branch_id=None,
    )

    S = ShiftType

    start_time_expr = func.to_char(S.start_time, TIME_OUT_FMT_SQL).label("start_time")
    end_time_expr = func.to_char(S.end_time, TIME_OUT_FMT_SQL).label("end_time")

    q = (
        select(
            S.id.label("id"),
            S.name.label("name"),
            start_time_expr,
            end_time_expr,
        )
        .select_from(S)
        .where(S.company_id == co_id)
    )

    return q


# ──────────────────────────────────────────────
# Payroll Period (Name / Start Date / End Date)
# ──────────────────────────────────────────────


def build_payroll_periods_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of payroll periods with quick view columns:

      - id
      - name
      - start_date  (string, MM/DD/YYYY)
      - end_date    (string, MM/DD/YYYY)
      - is_closed   (bool, open vs closed periods)

    Again, company scoping is enforced; no cross-company leakage.
    """
    co_id: Optional[int] = _get_company_id_from_context(context)
    if co_id is None:
        return select(PayrollPeriod.id).where(false())

    ensure_scope_by_ids(
        context=context,
        target_company_id=co_id,
        target_branch_id=None,
    )

    P = PayrollPeriod

    start_date_expr = func.to_char(P.start_date, DATE_OUT_FMT_SQL).label("start_date")
    end_date_expr = func.to_char(P.end_date, DATE_OUT_FMT_SQL).label("end_date")

    q = (
        select(
            P.id.label("id"),
            P.name.label("name"),
            start_date_expr,
            end_date_expr,
            P.is_closed.label("is_closed"),
        )
        .select_from(P)
        .where(P.company_id == co_id)
    )

    return q
