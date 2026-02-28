# app/application_education/groups/routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, g

from app.auth.deps import get_current_user
from app.common.api_response import api_success, api_error
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

from app.application_education.groups.schemas import (
    BatchCreate, BatchUpdate,
    StudentCategoryCreate, StudentCategoryUpdate,
    StudentGroupCreate, StudentGroupUpdate,
    GetStudentsIn, SaveStudentsIn,
    BulkDeleteIn,
)
from app.application_education.groups.group_service import GroupService

log = logging.getLogger(__name__)

bp = Blueprint("education_groups", __name__, url_prefix="/api/edu")
svc = GroupService()

# ----------------------------
# Batch
# ----------------------------
@bp.post("/batches")
@require_permission("Batch", "Create")
def create_batch():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BatchCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_batch(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=201)


@bp.patch("/batches/<int:batch_id>")
@require_permission("Batch", "Update")
def update_batch(batch_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BatchUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_batch(batch_id=batch_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/batches/delete-bulk")
@require_permission("Batch", "Delete")
def delete_batches_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_batches_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ----------------------------
# Student Category
# ----------------------------
@bp.post("/student-categories")
@require_permission("StudentCategory", "Create")
def create_category():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentCategoryCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_category(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=201)


@bp.patch("/student-categories/<int:category_id>")
@require_permission("StudentCategory", "Update")
def update_category(category_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentCategoryUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_category(category_id=category_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


@bp.post("/student-categories/delete-bulk")
@require_permission("StudentCategory", "Delete")
def delete_categories_bulk():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = BulkDeleteIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.delete_categories_bulk(ids=payload.ids, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=out, status_code=200)


# ----------------------------
# Student Group (Frappe-style master)
# ----------------------------
@bp.post("/student-groups")
@require_permission("StudentGroup", "Create")
def create_student_group():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentGroupCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_student_group(payload=payload.model_dump(), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    # EXACT response you wanted:
    return api_success(
        message="Student group created successfully",
        data={"id": out["id"], "name": out["name"]},
        status_code=201
    )


@bp.patch("/student-groups/<int:group_id>")
@require_permission("StudentGroup", "Update")
def update_student_group(group_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = StudentGroupUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_student_group(group_id=group_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(
        message="Student group updated successfully",
        data={"id": out["id"], "name": out["name"]},
        status_code=200
    )


@bp.delete("/student-groups/<int:group_id>")
@require_permission("StudentGroup", "Delete")
def delete_student_group(group_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    ok, msg, out = svc.delete_student_group(group_id=group_id, context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


# ----------------------------
# Button action: Get Students (preview)
# ----------------------------
@bp.post("/student-groups/<int:group_id>/get-students")
@require_permission("StudentGroup", "Update")
def get_students_preview(group_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = GetStudentsIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.get_students_preview(group_id=group_id, payload=payload.model_dump(), context=ctx)
    if not ok or out is None:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)


# ----------------------------
# Save roster (final list semantics)
# ----------------------------
@bp.put("/student-groups/<int:group_id>/students")
@require_permission("StudentGroup", "Update")
def save_students_list(group_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = SaveStudentsIn.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.save_students_list(
        group_id=group_id,
        effective_on=payload.effective_on,
        students=payload.students,
        context=ctx
    )
    if not ok or out is None:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data=out, status_code=200)