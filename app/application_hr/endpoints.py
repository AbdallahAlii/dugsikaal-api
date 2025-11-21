# # app/hr/endpoints.py
# from __future__ import annotations
# import json
# from typing import Optional
# from flask import Blueprint, request, g
#
# from app.application_hr.schemas.schemas import EmployeeCreate, EmployeeUpdate
# from app.application_hr.services.services import HrService
# from app.common.api_response import api_success, api_error
# from app.security.rbac_guards import require_permission
# from app.security.rbac_effective import AffiliationContext
# from app.auth.deps import get_current_user  # ensures session/profile present
#
#
# bp = Blueprint("hr", __name__, url_prefix="/api/hr")
# svc = HrService()
#
#
# @bp.post("/employees/create")
# @require_permission("Employee", "Create")
# def create_employee():
#     """
#     Accepts:
#       - application/json (body = EmployeeCreate)
#       - multipart/form-data (payload=<json EmployeeCreate>, file=<image>)
#
#     Rules:
#       - System Admin MUST provide company_id; can choose any branch that belongs to that company.
#       - Global “*:*” can create in any branch of their own company (DB-checked).
#       - Regular users can create ONLY in their own branch(es) (checked against affiliations, no DB).
#     """
#     _ = get_current_user()  # ensures session/profile and sets g.current_user
#     ctx: AffiliationContext = getattr(g, "auth", None)
#     if not ctx:
#         return api_error("Unauthorized", status_code=401)
#
#     # Parse body
#     file_storage = None
#     if request.content_type and "multipart/form-data" in request.content_type:
#         payload_raw = request.form.get("payload")
#         if not payload_raw:
#             return api_error("Missing 'payload' JSON in form-data.", status_code=422)
#         try:
#             payload = EmployeeCreate.model_validate(json.loads(payload_raw))
#         except Exception as e:
#             return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
#         file_storage = request.files.get("file")
#     else:
#         try:
#             payload = EmployeeCreate.model_validate(request.get_json(silent=True) or {})
#         except Exception as e:
#             return api_error(f"Invalid JSON body: {e}", status_code=422)
#
#     ok, msg, resp = svc.create_employee(
#         payload=payload,
#         context=ctx,
#         file_storage=file_storage,
#     )
#     if not ok or not resp:
#         return api_error(msg, status_code=400)
#
#     return api_success(message=resp.message, data={"employee": resp.employee}, status_code=201)
#
#
# @bp.put("/employees/update/<int:employee_id>")
# @require_permission("Employee", "UPDATE")
# def update_employee(employee_id: int):
#     """
#     Update employee details.
#
#     Rules:
#       - Only fields like full_name, status, phone_number, img_key, dob, etc., can be updated.
#       - Code, ID, and Username cannot be updated.
#     """
#     _ = get_current_user()  # ensures session/profile and sets g.current_user
#     ctx: AffiliationContext = getattr(g, "auth", None)
#     if not ctx:
#         return api_error("Unauthorized", status_code=401)
#
#     # Parse body
#     file_storage = None
#     if request.content_type and "multipart/form-data" in request.content_type:
#         payload_raw = request.form.get("payload")
#         if not payload_raw:
#             return api_error("Missing 'payload' JSON in form-data.", status_code=422)
#         try:
#             payload = EmployeeUpdate.model_validate(json.loads(payload_raw))
#         except Exception as e:
#             return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
#         file_storage = request.files.get("file")
#     else:
#         try:
#             payload = EmployeeUpdate.model_validate(request.get_json(silent=True) or {})
#         except Exception as e:
#             return api_error(f"Invalid JSON body: {e}", status_code=422)
#
#     ok, msg, resp = svc.update_employee(
#         employee_id=employee_id,
#         payload=payload,
#         context=ctx,
#         file_storage=file_storage,
#     )
#     if not ok or not resp:
#         return api_error(msg, status_code=400)
#
#     return api_success(message=resp.message, data={"employee": resp.employee}, status_code=200)
# app/application_hr/endpoints.py
from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, request, g

from app.application_hr.schemas.schemas import (
    EmployeeCreate,
    EmployeeUpdate,
    AttendanceCreate,
    EmployeeCheckinCreate,
    HolidayListCreate,
    HolidayListUpdate,
    ShiftTypeCreate,
    ShiftTypeUpdate,
    ShiftAssignmentCreate,
    ShiftAssignmentUpdate,
)
from app.application_hr.services.attendance_service import AttendanceService
from app.application_hr.services.services import HrService
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user  # ensures session/profile present


bp = Blueprint("hr", __name__, url_prefix="/api/hr")
svc = HrService()
attendance_svc = AttendanceService()

# ======================================================================
# EMPLOYEE ENDPOINTS
# ======================================================================

@bp.post("/employees/create")
@require_permission("Employee", "Create")
def create_employee():
    """
    Accepts:
      - application/json (body = EmployeeCreate)
      - multipart/form-data (payload=<json EmployeeCreate>, file=<image>)
    """
    _ = get_current_user()  # ensures session/profile and sets g.current_user
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    # Parse body
    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = EmployeeCreate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = EmployeeCreate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, resp = svc.create_employee(
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not resp:
        return api_error(msg, status_code=400)

    return api_success(
        message=resp.message,
        data={"employee": resp.employee, "user": resp.user},
        status_code=201,
    )


@bp.put("/employees/update/<int:employee_id>")
@require_permission("Employee", "Update")
def update_employee(employee_id: int):
    """
    Update employee details.

    Rules:
      - Only fields like full_name, status, phone_number, img_key, dob, etc., can be updated.
      - Code, ID, and Username cannot be updated.
    """
    _ = get_current_user()  # ensures session/profile and sets g.current_user
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    # Parse body
    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = EmployeeUpdate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = EmployeeUpdate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, resp = svc.update_employee(
        employee_id=employee_id,
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not resp:
        return api_error(msg, status_code=400)

    return api_success(
        message=resp.message,
        data={"employee": resp.employee},
        status_code=200,
    )


# ======================================================================
# HOLIDAY LIST ENDPOINTS
# ======================================================================

@bp.post("/holiday-lists")
@require_permission("Holiday List", "Create")
def create_holiday_list():
    """
    Create Holiday List + holidays (similar to ERPNext Holiday List doctype).
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = HolidayListCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, hl = svc.create_holiday_list(payload=payload, context=ctx)
    if not ok or not hl:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"holiday_list_id": hl.id},
        status_code=201,
    )


@bp.put("/holiday-lists/<int:holiday_list_id>")
@require_permission("Holiday List", "Update")
def update_holiday_list(holiday_list_id: int):
    """
    Update Holiday List and optionally replace holidays.
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = HolidayListUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, hl = svc.update_holiday_list(
        holiday_list_id=holiday_list_id,
        payload=payload,
        context=ctx,
    )
    if not ok or not hl:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"holiday_list_id": hl.id},
        status_code=200,
    )


# ======================================================================
# SHIFT TYPE ENDPOINTS
# ======================================================================

@bp.post("/shift-types")
@require_permission("Shift Type", "Create")
def create_shift_type():
    """
    Create a Shift Type (start_time/end_time, night shift, etc.).
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShiftTypeCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, st = svc.create_shift_type(payload=payload, context=ctx)
    if not ok or not st:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"shift_type_id": st.id},
        status_code=201,
    )


@bp.put("/shift-types/<int:shift_type_id>")
@require_permission("Shift Type", "Update")
def update_shift_type(shift_type_id: int):
    """
    Update a Shift Type.
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShiftTypeUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, st = svc.update_shift_type(
        shift_type_id=shift_type_id,
        payload=payload,
        context=ctx,
    )
    if not ok or not st:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"shift_type_id": st.id},
        status_code=200,
    )


# ======================================================================
# SHIFT ASSIGNMENT ENDPOINTS
# ======================================================================

@bp.post("/shift-assignments")
@require_permission("Shift Assignment", "Create")
def create_shift_assignment():
    """
    Assign a Shift Type to an employee for a date range.
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShiftAssignmentCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, sa = svc.create_shift_assignment(payload=payload, context=ctx)
    if not ok or not sa:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"shift_assignment_id": sa.id},
        status_code=201,
    )


@bp.put("/shift-assignments/<int:shift_assignment_id>")
@require_permission("Shift Assignment", "Update")
def update_shift_assignment(shift_assignment_id: int):
    """
    Update an existing Shift Assignment.
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShiftAssignmentUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, sa = svc.update_shift_assignment(
        shift_assignment_id=shift_assignment_id,
        payload=payload,
        context=ctx,
    )
    if not ok or not sa:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"shift_assignment_id": sa.id},
        status_code=200,
    )


# ======================================================================
# ATTENDANCE (MANUAL) ENDPOINT
# ======================================================================

@bp.post("/attendance/manual")
@require_permission("Attendance", "Create")
def create_manual_attendance():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = AttendanceCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, att = attendance_svc.create_manual_attendance(
        payload=payload,
        context=ctx,
    )
    if not ok or not att:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"attendance_id": att.id}, status_code=201)
@bp.post("/employee-checkin")
def create_employee_checkin():
    """
    Endpoint for:
    - biometric_sync.py (ZK devices)
    - mobile app checkins
    - other integrations

    Accepts EmployeeCheckinCreate JSON body.
    """
    # optional: if you put auth in front, call get_current_user() here
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = EmployeeCheckinCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    # If no context (device script, no login), create minimal context with company_id
    if not ctx and payload.company_id:
        ctx = AffiliationContext(
            user_id=None,
            company_id=payload.company_id,
            branch_id=None,
            is_global_admin=False,
            is_sys_admin=False,
            scopes=[],
        )

    if not ctx:
        return api_error("Company context is required.", status_code=400)

    ok, msg, checkin = attendance_svc.create_employee_checkin(
        payload=payload,
        context=ctx,
    )
    if not ok or not checkin:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"checkin_id": checkin.id},
        status_code=201,
    )

@bp.post("/attendance/auto-run")
@require_permission("Attendance", "Create")
def run_auto_attendance():
    """
    Trigger auto attendance for a given date & company.

    Body:
      {
        "company_id": 1,        # optional, uses ctx.company_id
        "date": "2025-11-21"    # optional, uses today's date if missing
      }
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    body = request.get_json(silent=True) or {}
    company_id = body.get("company_id") or ctx.company_id
    if not company_id:
        return api_error("company_id is required.", status_code=422)

    date_str = body.get("date")
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return api_error("Invalid 'date' format, expected YYYY-MM-DD.", status_code=422)
    else:
        target_date = date.today()

    ok, msg = attendance_svc.run_auto_attendance_for_date(
        company_id=company_id,
        target_date=target_date,
    )
    status = 200 if ok else 400
    return api_success(message=msg, data={}, status_code=status)

@bp.get("/biometric-devices/agent-config")

def biometric_devices_agent_config():
    """
    Endpoint used by biometric_sync agent to discover devices.

    Optional query param: ?company_id=1
    If omitted, returns all active devices.
    """
    company_id = request.args.get("company_id", type=int)
    devices = attendance_svc.list_biometric_devices_for_agent(company_id=company_id)

    data = [
        {
            "id": d.id,
            "company_id": d.company_id,
            "device_code": d.code,
            "name": d.name,
            "ip": d.ip_address,
            "port": d.port,
            "password": d.password,
            "timeout": d.timeout,
        }
        for d in devices
    ]
    return api_success(data=data)