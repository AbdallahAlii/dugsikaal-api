from __future__ import annotations

import logging
from flask import Blueprint, request, g
from pydantic import ValidationError

from app.auth.deps import get_current_user
from app.common.api_response import api_success, api_error
from app.common.pydantic_utils import humanize_pydantic_error
from app.navigation_workspace.services.subscription_guards import check_workspace_subscription
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

from app.application_education.programs.program_service import ProgramService
from app.application_education.programs.schemas import (
    ProgramCreate, ProgramUpdate,
    CourseCreate, CourseUpdate,
    BulkIds,
)

bp = Blueprint("education_program", __name__, url_prefix="/api/program")
svc = ProgramService()

WORKSPACE_SLUG = "academics"
log = logging.getLogger(__name__)


@bp.before_request
def _guard_subscription():
    if request.method == "OPTIONS":
        return
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Authentication required.", status_code=401)

    ok, msg = check_workspace_subscription(ctx, workspace_slug=WORKSPACE_SLUG)
    if not ok:
        return api_error(msg, status_code=403)


# ---------------- PROGRAM ----------------

@bp.post("/programs/create")
@require_permission("Program", "CREATE")
def create_program():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = ProgramCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.create_program(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"program": out}, status_code=201)


@bp.put("/programs/<int:program_id>/update")
@require_permission("Program", "UPDATE")
def update_program(program_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = ProgramUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.update_program(program_id=program_id, payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"program": out}, status_code=200)


@bp.delete("/programs/<int:program_id>/delete")
@require_permission("Program", "DELETE")
def delete_program(program_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    ok, msg, out = svc.delete_program(program_id=program_id, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"program": out}, status_code=200)


@bp.post("/programs/bulk-delete")
@require_permission("Program", "DELETE")
def bulk_delete_programs():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = BulkIds.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.bulk_delete_programs(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


# ---------------- COURSE ----------------

@bp.post("/courses/create")
@require_permission("Course", "CREATE")
def create_course():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = CourseCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.create_course(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"course": out}, status_code=201)


@bp.put("/courses/<int:course_id>/update")
@require_permission("Course", "UPDATE")
def update_course(course_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = CourseUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.update_course(course_id=course_id, payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"course": out}, status_code=200)


@bp.delete("/courses/<int:course_id>/delete")
@require_permission("Course", "DELETE")
def delete_course(course_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    ok, msg, out = svc.delete_course(course_id=course_id, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"course": out}, status_code=200)


@bp.post("/courses/bulk-delete")
@require_permission("Course", "DELETE")
def bulk_delete_courses():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)

    try:
        payload = BulkIds.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)

    ok, msg, out = svc.bulk_delete_courses(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)
