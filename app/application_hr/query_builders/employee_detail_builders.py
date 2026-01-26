# app/application_hr/employee_detail_builders.py
from __future__ import annotations

from datetime import date, datetime, time as dt_time
from typing import Dict, Any, Optional, List

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_hr.models.hr import (
    Employee,
    EmployeeAssignment,
    EmployeeEmergencyContact,
    HolidayList,
    Holiday,
    ShiftType,
    PayrollPeriod,
)
from app.application_org.models.company import Branch, Department, Company
from app.auth.models.users import User
from app.application_rbac.rbac_models import Role, UserRole


# ───────────────────────────
# Date / time helpers (ERP-style)
# ───────────────────────────

# Match your display helper (mm/dd/YYYY)
_DISPLAY_FMT = "%m/%d/%Y"


def _format_date_out(v: date | datetime | None) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        v = v.date()
    return v.strftime(_DISPLAY_FMT)


def _format_time_out(v: dt_time | None) -> Optional[str]:
    if v is None:
        return None
    # Simple 24h HH:MM (09:00, 17:30)
    return v.strftime("%H:%M")


def _status_slug(v) -> str:
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return (s or "inactive").lower()


# ───────────────────────────
# Common helpers
# ───────────────────────────


def _ensure_company_scope(ctx: AffiliationContext, company_id: Optional[int]) -> None:
    """
    Enforce company-level scope using central guard.

    - System Admin / Super Admin: guard will allow according to your RBAC logic.
    - Company-scoped roles: restricted to their company.
    - Branch-scoped roles: won't normally have these HR permission_tags.
    """
    if not company_id:
        raise Forbidden("Out of scope.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=int(company_id),
        target_branch_id=None,  # HR docs are company-level
    )


def _first_or_404(session: Session, stmt, label: str) -> Any:
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return row


# ───────────────────────────
# Generic resolvers
# ───────────────────────────


def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


# ───────────────────────────
# Employee resolvers
# ───────────────────────────


def resolve_employee_by_code(
    s: Session,
    ctx: AffiliationContext,
    code: str,
) -> int:
    code = (code or "").strip()
    if not code:
        raise BadRequest("Code required.")

    co_id = getattr(ctx, "company_id", None)

    if not getattr(ctx, "is_system_admin", False):
        if not co_id:
            raise Forbidden("Out of scope.")
        row = s.execute(
            select(Employee.id, Employee.company_id).where(
                and_(Employee.company_id == int(co_id), Employee.code == code)
            )
        ).first()
    else:
        row = s.execute(
            select(Employee.id, Employee.company_id).where(Employee.code == code)
        ).first()

    if not row:
        raise NotFound("Employee not found.")

    _ensure_company_scope(ctx, row.company_id)
    return int(row.id)


# ───────────────────────────
# Employee detail loader
# ───────────────────────────


def load_employee_detail(
    s: Session,
    ctx: AffiliationContext,
    employee_id: int,
) -> Dict[str, Any]:
    """
    Returns Frappe-style grouped JSON for Employee:

      - identity
      - company
      - contacts
      - employment
      - assignment
      - schedule (holiday list, default shift, device id)
      - login (user + roles)
      - emergency_contacts

    Dates are formatted using mm/dd/YYYY (no time).
    """

    # --- base employee (single lightweight row) ---
    base = s.execute(
        select(
            Employee.id,
            Employee.company_id,
            Employee.code,
            Employee.full_name,
            Employee.status,
            Employee.personal_email,
            Employee.phone_number,
            Employee.img_key,
            Employee.dob,
            Employee.date_of_joining,
            Employee.sex,
            Employee.employment_type,
            Employee.holiday_list_id,
            Employee.default_shift_type_id,
            Employee.attendance_device_id,
            Employee.user_id,
        ).where(Employee.id == employee_id)
    ).mappings().first()

    if not base:
        raise NotFound("Employee not found.")

    _ensure_company_scope(ctx, base.company_id)

    # --- company info (id + name) ---
    company_name = s.execute(
        select(Company.name).where(Company.id == base.company_id)
    ).scalar()

    # --- username (from user_id) ---
    username = None
    if base.user_id:
        username = s.execute(
            select(User.username).where(User.id == base.user_id)
        ).scalar()

    # --- current primary assignment ---
    assign = s.execute(
        select(
            EmployeeAssignment.branch_id,
            EmployeeAssignment.department_id,
            EmployeeAssignment.job_title,
            EmployeeAssignment.from_date,
            EmployeeAssignment.to_date,
            EmployeeAssignment.is_primary,
        ).where(
            and_(
                EmployeeAssignment.employee_id == employee_id,
                EmployeeAssignment.is_primary.is_(True),
                EmployeeAssignment.to_date.is_(None),
            )
        )
    ).mappings().first()

    branch = None
    dept = None
    if assign and assign.branch_id:
        bname = s.execute(
            select(Branch.name).where(Branch.id == assign.branch_id)
        ).scalar()
        if bname:
            branch = {"id": int(assign.branch_id), "name": bname}
    if assign and assign.department_id:
        dname = s.execute(
            select(Department.name).where(Department.id == assign.department_id)
        ).scalar()
        if dname:
            dept = {"id": int(assign.department_id), "name": dname}

    # --- holiday list (id + name) ---
    holiday_list = None
    if base.holiday_list_id:
        hl_row = s.execute(
            select(HolidayList.id, HolidayList.name).where(
                HolidayList.id == base.holiday_list_id
            )
        ).mappings().first()
        if hl_row:
            holiday_list = {
                "id": int(hl_row.id),
                "name": hl_row.name,
            }

    # --- default shift type (id + name + times) ---
    default_shift_type = None
    if base.default_shift_type_id:
        st_row = s.execute(
            select(
                ShiftType.id,
                ShiftType.name,
                ShiftType.start_time,
                ShiftType.end_time,
            ).where(ShiftType.id == base.default_shift_type_id)
        ).mappings().first()
        if st_row:
            default_shift_type = {
                "id": int(st_row.id),
                "name": st_row.name,
                "start_time": _format_time_out(st_row.start_time),
                "end_time": _format_time_out(st_row.end_time),
            }

    # --- roles (via RBAC) ---
    roles: List[Dict[str, Any]] = []
    if base.user_id:
        role_rows = s.execute(
            select(Role.id, Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == base.user_id)
            .order_by(Role.name)
        ).mappings().all()
        roles = [
            {
                "id": int(r.id),
                "name": r.name,
            }
            for r in role_rows
        ]

    # --- emergency contacts (sorted by relationship/name) ---
    ec_rows = s.execute(
        select(
            EmployeeEmergencyContact.id,
            EmployeeEmergencyContact.full_name,
            EmployeeEmergencyContact.relationship_type,
            EmployeeEmergencyContact.phone_number,
        ).where(EmployeeEmergencyContact.employee_id == employee_id)
    ).mappings().all()

    emergency_contacts: List[Dict[str, Any]] = [
        {
            "id": int(r.id),
            "name": r.full_name,
            "relationship": (
                r.relationship_type.value
                if hasattr(r.relationship_type, "value")
                else str(r.relationship_type)
            ),
            "phone": r.phone_number,
        }
        for r in ec_rows
    ]

    # --- grouped ERP-style response ---

    identity = {
        "employee_id": int(base.id),
        "company_id": int(base.company_id),
        "code": base.code,
        "full_name": base.full_name,
        "status": _status_slug(base.status),
        "img_key": base.img_key,
    }

    company = {
        "id": int(base.company_id),
        "name": company_name,
    }

    contacts = {
        "email": base.personal_email,
        "phone": base.phone_number,
        "username": username,
    }

    employment = {
        "dob": _format_date_out(base.dob),
        "date_of_joining": _format_date_out(base.date_of_joining),
        "gender": (
            base.sex.value
            if getattr(base, "sex", None) is not None and hasattr(base.sex, "value")
            else (str(base.sex) if getattr(base, "sex", None) is not None else None)
        ),
        "employment_type": (
            base.employment_type.value
            if getattr(base, "employment_type", None) is not None
            and hasattr(base.employment_type, "value")
            else (
                str(base.employment_type)
                if getattr(base, "employment_type", None) is not None
                else None
            )
        ),
        "status": _status_slug(base.status),
    }

    assignment = {
        "branch": branch,   # {"id":..,"name":..} or None
        "department": dept, # {"id":..,"name":..} or None
        "job_title": (assign.job_title if assign else None),
        "from_date": _format_date_out(assign.from_date) if assign else None,
        "to_date": _format_date_out(assign.to_date) if assign else None,
        "is_primary": bool(assign.is_primary) if assign else None,
    }

    schedule = {
        "holiday_list": holiday_list,                 # {"id","name"} or None
        "default_shift_type": default_shift_type,     # {"id","name","start_time","end_time"} or None
        "attendance_device_id": base.attendance_device_id,
    }

    login = {
        "user_id": int(base.user_id) if base.user_id else None,
        "username": username,
        "roles": roles,  # list of {"id","name"}
    }

    return {
        "identity": identity,
        "company": company,
        "contacts": contacts,
        "employment": employment,
        "assignment": assignment,
        "schedule": schedule,
        "login": login,
        "emergency_contacts": emergency_contacts,
    }


# ───────────────────────────
# Holiday List resolvers + detail
# ───────────────────────────


def resolve_holiday_list_by_name(
    s: Session,
    ctx: AffiliationContext,
    name: str,
) -> int:
    name = (name or "").strip()
    if not name:
        raise BadRequest("Name required.")

    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Out of scope.")

    HL = HolidayList
    row = s.execute(
        select(HL.id, HL.company_id).where(
            and_(HL.name == name, HL.company_id == int(co_id))
        )
    ).first()

    if not row:
        raise NotFound("Holiday List not found.")

    _ensure_company_scope(ctx, row.company_id)
    return int(row.id)


def load_holiday_list_detail(
    s: Session,
    ctx: AffiliationContext,
    holiday_list_id: int,
) -> Dict[str, Any]:
    """
    ERP-style Holiday List detail:

      - basic_details
      - holidays[]

    Dates are formatted mm/dd/YYYY.
    """
    HL = HolidayList
    C = Company
    H = Holiday

    # Header
    stmt = (
        select(
            HL.id,
            HL.name,
            HL.company_id,
            HL.from_date,
            HL.to_date,
            HL.is_default,
            C.name.label("company_name"),
        )
        .select_from(HL)
        .join(C, C.id == HL.company_id)
        .where(HL.id == holiday_list_id)
    )
    hdr = _first_or_404(s, stmt, "Holiday List")
    _ensure_company_scope(ctx, hdr.company_id)

    # Holidays
    rows = s.execute(
        select(
            H.id,
            H.holiday_date,
            H.description,
            H.is_full_day,
            H.is_weekly_off,
        )
        .where(H.holiday_list_id == holiday_list_id)
        .order_by(H.holiday_date.asc())
    ).mappings().all()

    holidays: List[Dict[str, Any]] = [
        {
            "id": int(r.id),
            "date": _format_date_out(r.holiday_date),
            "description": r.description,
            "is_full_day": bool(r.is_full_day),
            "is_weekly_off": bool(r.is_weekly_off),
        }
        for r in rows
    ]

    basic_details = {
        "id": int(hdr.id),
        "name": hdr.name,
        "company_id": int(hdr.company_id),
        "company_name": hdr.company_name,
        "from_date": _format_date_out(hdr.from_date),
        "to_date": _format_date_out(hdr.to_date),
        "is_default": bool(hdr.is_default),
        "total_holidays": len(holidays),
    }

    return {
        "basic_details": basic_details,
        "holidays": holidays,
    }


# ───────────────────────────
# Shift Type resolvers + detail
# ───────────────────────────


def resolve_shift_type_by_name(
    s: Session,
    ctx: AffiliationContext,
    name: str,
) -> int:
    name = (name or "").strip()
    if not name:
        raise BadRequest("Name required.")

    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Out of scope.")

    S = ShiftType
    row = s.execute(
        select(S.id, S.company_id).where(
            and_(S.name == name, S.company_id == int(co_id))
        )
    ).first()

    if not row:
        raise NotFound("Shift Type not found.")

    _ensure_company_scope(ctx, row.company_id)
    return int(row.id)


def load_shift_type_detail(
    s: Session,
    ctx: AffiliationContext,
    shift_type_id: int,
) -> Dict[str, Any]:
    """
    ERP-style Shift Type detail:

      - basic_details
      - settings

    Times are strings (HH:MM).
    Dates formatted mm/dd/YYYY.
    """
    S = ShiftType
    C = Company
    HL = HolidayList

    stmt = (
        select(
            S.id,
            S.name,
            S.company_id,
            S.start_time,
            S.end_time,
            S.enable_auto_attendance,
            S.process_attendance_after,
            S.is_night_shift,
            S.holiday_list_id,
            C.name.label("company_name"),
            HL.name.label("holiday_list_name"),
        )
        .select_from(S)
        .join(C, C.id == S.company_id)
        .outerjoin(HL, HL.id == S.holiday_list_id)
        .where(S.id == shift_type_id)
    )
    hdr = _first_or_404(s, stmt, "Shift Type")
    _ensure_company_scope(ctx, hdr.company_id)

    basic_details = {
        "id": int(hdr.id),
        "name": hdr.name,
        "company_id": int(hdr.company_id),
        "company_name": hdr.company_name,
        "start_time": _format_time_out(hdr.start_time),
        "end_time": _format_time_out(hdr.end_time),
        "is_night_shift": bool(hdr.is_night_shift),
    }

    holiday_list = (
        {
            "id": int(hdr.holiday_list_id),
            "name": hdr.holiday_list_name,
        }
        if hdr.holiday_list_id
        else None
    )

    settings = {
        "enable_auto_attendance": bool(hdr.enable_auto_attendance),
        "process_attendance_after": _format_date_out(hdr.process_attendance_after),
        "holiday_list": holiday_list,  # optional override list for this shift
    }

    return {
        "basic_details": basic_details,
        "settings": settings,
    }


# ───────────────────────────
# Payroll Period resolvers + detail
# ───────────────────────────


def resolve_payroll_period_by_name(
    s: Session,
    ctx: AffiliationContext,
    name: str,
) -> int:
    name = (name or "").strip()
    if not name:
        raise BadRequest("Name required.")

    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Out of scope.")

    P = PayrollPeriod
    row = s.execute(
        select(P.id, P.company_id).where(
            and_(P.name == name, P.company_id == int(co_id))
        )
    ).first()

    if not row:
        raise NotFound("Payroll Period not found.")

    _ensure_company_scope(ctx, row.company_id)
    return int(row.id)


def load_payroll_period_detail(
    s: Session,
    ctx: AffiliationContext,
    payroll_period_id: int,
) -> Dict[str, Any]:
    """
    ERP-style Payroll Period detail:

      - basic_details

    Dates formatted mm/dd/YYYY.
    """
    P = PayrollPeriod
    C = Company

    stmt = (
        select(
            P.id,
            P.name,
            P.company_id,
            P.start_date,
            P.end_date,
            P.is_closed,
            C.name.label("company_name"),
        )
        .select_from(P)
        .join(C, C.id == P.company_id)
        .where(P.id == payroll_period_id)
    )
    hdr = _first_or_404(s, stmt, "Payroll Period")
    _ensure_company_scope(ctx, hdr.company_id)

    status_label = "Closed" if hdr.is_closed else "Open"

    basic_details = {
        "id": int(hdr.id),
        "name": hdr.name,
        "company_id": int(hdr.company_id),
        "company_name": hdr.company_name,
        "start_date": _format_date_out(hdr.start_date),
        "end_date": _format_date_out(hdr.end_date),
        "is_closed": bool(hdr.is_closed),
        "status": status_label,
    }

    return {
        "basic_details": basic_details,
    }
