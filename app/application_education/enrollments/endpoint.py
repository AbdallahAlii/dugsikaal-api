from __future__ import annotations

import logging
from datetime import date

from flask import Blueprint, request, g

from app.auth.deps import get_current_user
from app.common.api_response import api_success, api_error
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

from app.application_education.enrollments.enrollment_service import EnrollmentService
from app.application_education.enrollments.schemas import (
    ProgramEnrollmentCreate,
    ProgramEnrollmentUpdate,
    CourseEnrollmentCreate,
    CourseEnrollmentUpdate,
    BulkDeleteIn,
)

log = logging.getLogger(__name__)

bp = Blueprint("education_enrollments", __name__, url_prefix="/api/edu")
svc = EnrollmentService()


# ============================
# Program Enrollment
# ============================

@bp.post("/program-enrollments/create")
@require_permission("Program Enrollment", "Create")
def create_program_enrollment():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ProgramEnrollmentCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_program_enrollment(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=201)


@bp.put("/program-enrollments/update/<int:program_enrollment_id>")
@require_permission("Program Enrollment", "Update")
def update_program_enrollment(program_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ProgramEnrollmentUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_program_enrollment(
        program_enrollment_id=program_enrollment_id,
        payload=payload.model_dump(exclude_unset=True),
        context=ctx,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/program-enrollments/delete/<int:program_enrollment_id>")
@require_permission("Program Enrollment", "Delete")
def delete_program_enrollment_single(program_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    ok, msg, out = svc.delete_program_enrollment_single(program_enrollment_id=program_enrollment_id, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/program-enrollments/delete-bulk")
@require_permission("Program Enrollment", "Delete")
def delete_program_enrollment_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_program_enrollment_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ============================
# Course Enrollment
# ============================

@bp.post("/course-enrollments/create")
@require_permission("Course Enrollment", "Create")
def create_course_enrollment():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = CourseEnrollmentCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_course_enrollment(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=201)


@bp.put("/course-enrollments/update/<int:course_enrollment_id>")
@require_permission("Course Enrollment", "Update")
def update_course_enrollment(course_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = CourseEnrollmentUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_course_enrollment(
        course_enrollment_id=course_enrollment_id,
        payload=payload.model_dump(exclude_unset=True),
        context=ctx,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/course-enrollments/delete/<int:course_enrollment_id>")
@require_permission("Course Enrollment", "Delete")
def delete_course_enrollment_single(course_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    ok, msg, out = svc.delete_course_enrollment_single(course_enrollment_id=course_enrollment_id, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/course-enrollments/delete-bulk")
@require_permission("Course Enrollment", "Delete")
def delete_course_enrollment_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_course_enrollment_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ============================
# Curriculum Courses (UI auto-fill)
# ============================

@bp.get("/programs/<int:program_id>/curriculum-courses")
@require_permission("Program", "Read")
def get_program_curriculum_courses(program_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    curriculum_version = int(request.args.get("curriculum_version", 1))
    on_date_str = request.args.get("on_date")
    on_date_val = None
    if on_date_str:
        try:
            on_date_val = date.fromisoformat(on_date_str)
        except Exception:
            return api_error("Invalid on_date format. Use YYYY-MM-DD.", status_code=422)

    ok, msg, out = svc.get_program_curriculum_courses(
        program_id=program_id,
        context=ctx,
        curriculum_version=curriculum_version,
        on_date=on_date_val,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ============================
# Program Enrollment Submit
# ============================

@bp.post("/program-enrollments/submit/<int:program_enrollment_id>")
@require_permission("Program Enrollment", "Submit")
def submit_program_enrollment(program_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    # optional body: allow adding courses at submit moment
    body = request.get_json(silent=True) or {}
    enrolled_course_ids = body.get("enrolled_course_ids")  # optional list

    ok, msg, out = svc.submit_program_enrollment(
        program_enrollment_id=program_enrollment_id,
        enrolled_course_ids=enrolled_course_ids,
        context=ctx,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ============================
# Course Enrollment Submit
# ============================

@bp.post("/course-enrollments/submit/<int:course_enrollment_id>")
@require_permission("Course Enrollment", "Submit")
def submit_course_enrollment(course_enrollment_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    ok, msg, out = svc.submit_course_enrollment(
        course_enrollment_id=course_enrollment_id,
        context=ctx,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)
