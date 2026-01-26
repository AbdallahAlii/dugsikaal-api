# app/application_hr/services/adapters.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

from config.database import db
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.application_hr.services.services import HrService
from app.application_hr.schemas.schemas import EmployeeCreate, EmployeeUpdate


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build AffiliationContext for HR imports.

    - company_id / branch_id / created_by_id are injected from DataImport
      via pipeline._inject_context().
    - We mark is_system_admin=True because authorization was already
      enforced at Data Import endpoint.
    """
    company_id = int(row.get("company_id") or 0)

    branch_id_raw = row.get("branch_id")
    branch_id = int(branch_id_raw) if branch_id_raw is not None else None

    user_id_raw = row.get("created_by_id")
    user_id = int(user_id_raw) if user_id_raw is not None else 0

    return AffiliationContext(
        user_id=user_id,
        user_type=row.get("user_type") or "user",
        company_id=company_id,
        branch_id=branch_id,
        roles=set(),
        affiliations=[],
        permissions=set(),
        is_system_admin=True,
    )


def _build_employee_assignments_for_import(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    For simple Employee imports we don't ask the user for from_date / is_primary.

    Minimal Excel requirement:
        - full_name
        - date_of_joining
        - branch: taken from DataImport.branch_id (injected into row)

    Logic:
        - branch_id: row["branch_id"]
        - from_date: row["from_date"] or row["date_of_joining"]
        - is_primary: True
    """
    branch_id = row.get("branch_id")
    if not branch_id:
        raise BizValidationError(
            "Branch is required for Employee import. "
            "Please set Branch on the Data Import form."
        )

    doj = row.get("date_of_joining")
    if doj is None:
        raise BizValidationError("Date of Joining is required for Employee import.")

    from_date = row.get("from_date") or doj

    assignment: Dict[str, Any] = {
        "branch_id": branch_id,
        "from_date": from_date,
        "to_date": row.get("to_date"),
        "is_primary": True,  # default primary assignment
        "job_title": row.get("job_title"),
        "department_id": row.get("department_id"),
        "extra": row.get("assignment_extra") or {},
    }
    return [assignment]


def _build_employee_payload_from_row(row: Dict[str, Any]) -> EmployeeCreate:
    """
    Map flat row dict → EmployeeCreate schema.

    All fields except the minimal ones are optional.
    """
    full_name = row.get("full_name")
    if not full_name:
        raise BizValidationError("Full Name is required for Employee import.")

    if row.get("date_of_joining") is None:
        raise BizValidationError("Date of Joining is required for Employee import.")

    assignments = _build_employee_assignments_for_import(row)

    payload_dict: Dict[str, Any] = {
        "company_id": row.get("company_id"),
        "code": row.get("code"),
        "full_name": full_name,
        "personal_email": row.get("personal_email"),
        "phone_number": row.get("phone_number"),
        "dob": row.get("dob"),
        "date_of_joining": row.get("date_of_joining"),
        "sex": row.get("sex"),
        "employment_type": row.get("employment_type"),
        "holiday_list_id": row.get("holiday_list_id"),
        "default_shift_type_id": row.get("default_shift_type_id"),
        "attendance_device_id": row.get("attendance_device_id"),
        "assignments": assignments,
        # Simple imports usually don't send emergency contacts / roles.
        "emergency_contacts": row.get("emergency_contacts"),
        "roles": row.get("roles"),
    }

    return EmployeeCreate(**payload_dict)


def create_employee_via_import(row: Dict[str, Any]) -> None:
    """
    Data Import adapter for Employee INSERT.

    - One row → one Employee document (+ user + primary assignment).
    - Uses DataImport.company_id / branch_id / created_by_id as context.
    - Minimal required columns in file: full_name, date_of_joining.
    - Branch is taken from DataImport form (row.branch_id).
    """
    ctx = _ctx_from_row(row)
    svc = HrService(session=db.session)

    # Drop Meta flags that Data Import runner injects
    row.pop("_submit_after_import", None)
    row.pop("_mute_emails", None)

    payload = _build_employee_payload_from_row(row)

    ok, msg, _resp = svc.create_employee(
        payload=payload,
        context=ctx,
        file_storage=None,
        bytes_=None,
        filename=None,
        content_type=None,
    )
    if not ok:
        # Data Import expects an exception to mark row as failed.
        raise BizValidationError(msg or "Employee import failed.")


def _build_employee_update_payload_from_row(row: Dict[str, Any]) -> EmployeeUpdate:
    """
    Build EmployeeUpdate from row for UPDATE imports.

    We keep it simple:
      - allow updating basic fields (full_name, personal_email, phone, dob,
        date_of_joining, sex, employment_type, holiday_list, default_shift_type,
        attendance_device_id).
      - You can extend later to cover assignments / contacts via explicit columns.
    """
    payload_dict: Dict[str, Any] = {}

    # Basic fields (optional)
    for key in [
        "full_name",
        "personal_email",
        "phone_number",
        "dob",
        "date_of_joining",
        "sex",
        "employment_type",
        "holiday_list_id",
        "default_shift_type_id",
        "attendance_device_id",
        "status",
    ]:
        if key in row and row[key] is not None:
            payload_dict[key] = row[key]

    # Assignments / emergency_contacts / roles can be added later when needed
    return EmployeeUpdate(**payload_dict)


def update_employee_by_id(row: Dict[str, Any]) -> None:
    """
    Data Import adapter for Employee UPDATE by internal ID.
    """
    employee_id = row.get("id")
    if not employee_id:
        raise BizValidationError("Employee ID is required for update-by-id import.")

    ctx = _ctx_from_row(row)
    svc = HrService(session=db.session)

    payload = _build_employee_update_payload_from_row(row)

    ok, msg, _resp = svc.update_employee(
        employee_id=int(employee_id),
        payload=payload,
        context=ctx,
        file_storage=None,
        bytes_=None,
        filename=None,
        content_type=None,
    )
    if not ok:
        raise BizValidationError(msg or "Employee update (by ID) failed.")


def update_employee_by_code(row: Dict[str, Any]) -> None:
    """
    Data Import adapter for Employee UPDATE by Employee Code.

    Uses (company_id, code) to locate the employee.
    """
    company_id = row.get("company_id")
    code = row.get("code")

    if not company_id:
        raise BizValidationError("Company is required for update-by-code import.")
    if not code:
        raise BizValidationError("Employee Code is required for update-by-code import.")

    ctx = _ctx_from_row(row)
    svc = HrService(session=db.session)

    emp = svc.repo.find_employee_by_code(company_id=int(company_id), code=str(code))
    if not emp:
        raise BizValidationError(
            f"Employee with code '{code}' not found in this company."
        )

    payload = _build_employee_update_payload_from_row(row)

    ok, msg, _resp = svc.update_employee(
        employee_id=emp.id,
        payload=payload,
        context=ctx,
        file_storage=None,
        bytes_=None,
        filename=None,
        content_type=None,
    )
    if not ok:
        raise BizValidationError(msg or "Employee update (by Code) failed.")
