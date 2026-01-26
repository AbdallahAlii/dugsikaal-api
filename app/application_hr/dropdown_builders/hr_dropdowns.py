from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_hr.models.hr import (
    Employee,
    EmployeeAssignment,
    HolidayList,
    ShiftType,
    SalaryStructure,
    PayrollPeriod,
    BiometricDevice,
)
from app.application_org.models.company import Branch, Department


# -------- Common helper --------

def _co(ctx: AffiliationContext) -> Optional[int]:
    """Get active company_id from context (None if not set)."""
    return getattr(ctx, "company_id", None)


# -------- Employees dropdown --------

def build_employees_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Employee dropdown.

    - One row per employee in the company.
    - Uses current PRIMARY assignment (is_primary & to_date IS NULL) to show branch/department.
    - Any user belonging to the company can see all employees in that company.
    """
    co_id = _co(ctx)
    if not co_id:
        # no company in context → return empty query
        return select(Employee.id.label("value")).where(Employee.id == -1)

    ea = EmployeeAssignment
    b = Branch
    d = Department

    q = (
        select(
            Employee.id.label("value"),
            Employee.full_name.label("label"),
            Employee.code.label("code"),
            b.name.label("branch_name"),
            d.name.label("department_name"),
            Employee.status.label("status"),
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
        .order_by(Employee.full_name.asc())
    )

    return q


# -------- Holiday List dropdown --------

def build_holiday_lists_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Holiday Lists.
    - All holiday lists for the user's company.
    - No branch restriction.
    """
    co_id = _co(ctx)
    if not co_id:
        return select(HolidayList.id.label("value")).where(HolidayList.id == -1)

    q = (
        select(
            HolidayList.id.label("value"),
            HolidayList.name.label("label"),
            HolidayList.from_date,
            HolidayList.to_date,
            HolidayList.is_default,
        )
        .select_from(HolidayList)
        .where(HolidayList.company_id == co_id)
        .order_by(HolidayList.is_default.desc(), HolidayList.name.asc())
    )
    return q


# -------- Shift Type dropdown --------

def build_shift_types_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Shift Types.
    - All shift types defined for the company.
    """
    co_id = _co(ctx)
    if not co_id:
        return select(ShiftType.id.label("value")).where(ShiftType.id == -1)

    q = (
        select(
            ShiftType.id.label("value"),
            ShiftType.name.label("label"),
            ShiftType.start_time,
            ShiftType.end_time,
            ShiftType.is_night_shift,
            ShiftType.enable_auto_attendance,
            ShiftType.holiday_list_id,
        )
        .select_from(ShiftType)
        .where(ShiftType.company_id == co_id)
        .order_by(ShiftType.name.asc())
    )
    return q


# -------- Salary Structure dropdown --------

def build_salary_structures_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Salary Structures.
    - Only active structures by default (is_active = True).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(SalaryStructure.id.label("value")).where(SalaryStructure.id == -1)

    q = (
        select(
            SalaryStructure.id.label("value"),
            SalaryStructure.name.label("label"),
            SalaryStructure.payment_frequency,
            SalaryStructure.currency,
            SalaryStructure.is_active,
        )
        .select_from(SalaryStructure)
        .where(
            SalaryStructure.company_id == co_id,
            SalaryStructure.is_active.is_(True),
        )
        .order_by(SalaryStructure.name.asc())
    )
    return q


# -------- Payroll Period dropdown --------

def build_payroll_periods_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Payroll Periods.
    - By default, only open (is_closed = False) periods.
    """
    co_id = _co(ctx)
    if not co_id:
        return select(PayrollPeriod.id.label("value")).where(PayrollPeriod.id == -1)

    q = (
        select(
            PayrollPeriod.id.label("value"),
            PayrollPeriod.name.label("label"),
            PayrollPeriod.start_date,
            PayrollPeriod.end_date,
            PayrollPeriod.is_closed,
        )
        .select_from(PayrollPeriod)
        .where(
            PayrollPeriod.company_id == co_id,
            PayrollPeriod.is_closed.is_(False),
        )
        .order_by(PayrollPeriod.start_date.desc())
    )
    return q


# -------- Biometric Device dropdown --------

def build_biometric_devices_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
):
    """
    Company-scoped Biometric Devices.
    - Only active devices (is_active = True) for the company.
    """
    co_id = _co(ctx)
    if not co_id:
        return select(BiometricDevice.id.label("value")).where(BiometricDevice.id == -1)

    q = (
        select(
            BiometricDevice.id.label("value"),
            BiometricDevice.name.label("label"),
            BiometricDevice.code,
            BiometricDevice.ip_address,
            BiometricDevice.port,
            BiometricDevice.location,
            BiometricDevice.is_active,
        )
        .select_from(BiometricDevice)
        .where(
            BiometricDevice.company_id == co_id,
            BiometricDevice.is_active.is_(True),
        )
        .order_by(BiometricDevice.name.asc())
    )
    return q
