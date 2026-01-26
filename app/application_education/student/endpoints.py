from __future__ import annotations

import logging
import json

from flask import Blueprint, request, g

from app.auth.deps import get_current_user
from app.common.api_response import api_success, api_error

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

from app.application_education.student.schemas import (
    GuardianCreate,
    GuardianUpdate,
    StudentCreate,
    StudentUpdate,
    BulkDeleteIn,
)
from app.application_education.student.student_service import StudentService

log = logging.getLogger(__name__)

bp = Blueprint("education_student", __name__, url_prefix="/api/student")
svc = StudentService()


# ============================
# GUARDIAN
# ============================

@bp.post("/guardians/create")
@require_permission("Guardian", "Create")
def create_guardian():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = GuardianCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_guardian(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=201)


@bp.put("/guardians/update/<int:guardian_id>")
@require_permission("Guardian", "Update")
def update_guardian(guardian_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = GuardianUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_guardian(guardian_id=guardian_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


@bp.post("/guardians/delete-bulk")
@require_permission("Guardian", "Delete")
def delete_guardians_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_guardians_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


# ============================
# STUDENT
# ============================

@bp.post("/students/create")
@require_permission("Student", "Create")
def create_student():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_student(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=201)


@bp.put("/students/update/<int:student_id>")
@require_permission("Student", "Update")
def update_student(student_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_student(student_id=student_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


@bp.post("/students/delete-bulk")
@require_permission("Student", "Delete")
def delete_students_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_students_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)
