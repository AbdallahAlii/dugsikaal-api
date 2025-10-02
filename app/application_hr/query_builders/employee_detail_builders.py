from __future__ import annotations
from typing import Dict, Any, Optional, List

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.application_hr.models.hr import Employee, EmployeeAssignment, EmployeeEmergencyContact
from app.application_org.models.company import Branch, Department, Company
from app.auth.models.users import User


# ---------- utils ----------
def _date(v) -> Optional[str]:
    return v.isoformat() if v else None

def _status_slug(v) -> str:
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return (s or "inactive").lower()

def _ensure_company(ctx: AffiliationContext, employee_company_id: Optional[int]):
    if getattr(ctx, "is_system_admin", False):
        return
    if not employee_company_id or int(employee_company_id) != int(getattr(ctx, "company_id", 0)):
        raise Forbidden("Out of scope.")


# ---------- resolvers ----------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)

def resolve_employee_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    code = (code or "").strip()
    if not code:
        raise BadRequest("Code required.")
    if not getattr(ctx, "is_system_admin", False):
        co_id = getattr(ctx, "company_id", None)
        if not co_id:
            raise Forbidden("Out of scope.")
        row = s.execute(
            select(Employee.id).where(and_(Employee.company_id == int(co_id), Employee.code == code))
        ).first()
    else:
        row = s.execute(select(Employee.id).where(Employee.code == code)).first()
    if not row:
        raise NotFound("Employee not found.")
    return int(row.id)


# ---------- loader ----------
def load_employee_detail(s: Session, ctx: AffiliationContext, employee_id: int) -> Dict[str, Any]:
    """
    Returns Frappe-style grouped JSON:
      identity, contacts, employment, assignment, emergency_contacts
    Dates are YYYY-MM-DD (no time).
    """
    # base employee
    base = s.execute(
        select(
            Employee.id, Employee.company_id, Employee.code, Employee.full_name, Employee.status,
            Employee.personal_email, Employee.phone_number, Employee.img_key,
            Employee.dob, Employee.date_of_joining,
            Employee.user_id,
        ).where(Employee.id == employee_id)
    ).mappings().first()
    if not base:
        raise NotFound("Employee not found.")

    _ensure_company(ctx, base.company_id)

    # username (from user_id)
    username = None
    if base.user_id:
        username = s.execute(select(User.username).where(User.id == base.user_id)).scalar()

    # current primary assignment
    assign = s.execute(
        select(
            EmployeeAssignment.branch_id, EmployeeAssignment.department_id,
            EmployeeAssignment.job_title, EmployeeAssignment.from_date,
            EmployeeAssignment.to_date, EmployeeAssignment.is_primary
        )
        .where(
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
        bname = s.execute(select(Branch.name).where(Branch.id == assign.branch_id)).scalar()
        if bname:
            branch = {"id": int(assign.branch_id), "name": bname}
    if assign and assign.department_id:
        dname = s.execute(select(Department.name).where(Department.id == assign.department_id)).scalar()
        if dname:
            dept = {"id": int(assign.department_id), "name": dname}

    # emergency contacts (sorted by relationship/name)
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
            "relationship": (r.relationship_type.value if hasattr(r.relationship_type, "value") else str(r.relationship_type)),
            "phone": r.phone_number,
        }
        for r in ec_rows
    ]

    # assemble response
    identity = {
        "employee_id": int(base.id),
        "company_id": int(base.company_id),
        "code": base.code,
        "full_name": base.full_name,
        "status": _status_slug(base.status),
        "img_key": base.img_key,
    }

    contacts = {
        "email": base.personal_email,
        "phone": base.phone_number,
        "username": username,          # resolved from user_id
    }

    employment = {
        "dob": _date(base.dob),
        "date_of_joining": _date(base.date_of_joining),
    }

    assignment = {
        "branch": branch,              # {"id":..,"name":..} or None
        "department": dept,            # {"id":..,"name":..} or None
        "job_title": (assign.job_title if assign else None),
        "from_date": _date(assign.from_date) if assign else None,
        "to_date": _date(assign.to_date) if assign else None,  # should be None for current
        "is_primary": (bool(assign.is_primary) if assign else None),
    }

    return {
        "identity": identity,
        "contacts": contacts,
        "employment": employment,
        "assignment": assignment,
        "emergency_contacts": emergency_contacts,
    }
