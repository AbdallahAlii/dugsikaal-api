from __future__ import annotations
import logging
from flask import Blueprint, request, g
from werkzeug.exceptions import HTTPException

from app.application_rbac.schemas import (
    RoleCreateRequest, BulkDeleteRolesRequest,
    SetUserRolesRequest,
    OverrideCreateRequest, OverrideDeleteRequest,
    UserConstraintCreateRequest, UserConstraintDeleteRequest,
)
from app.application_rbac.service import RbacService
from app.auth.deps import get_current_user
from app.common.api_response import api_error, api_success
from app.security.rbac_guards import require_permission

log = logging.getLogger(__name__)

bp = Blueprint("rbac", __name__, url_prefix="/api/rbac")
svc = RbacService()

# ---------- Roles ----------

@bp.post("/roles/create")
@require_permission("Role", "Create")
def create_role():
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = RoleCreateRequest(**payload)
        svc.create_role(
            name=req.name,
            scope=req.scope,
            description=req.description,
            company_id=req.company_id,   # may be None; service will default from g.auth
            context=g.auth,
        )
        return api_success(message="Role created", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("create_role failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)


@bp.delete("/roles/bulk")
@require_permission("Role", "Delete")
def delete_roles_bulk():
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = BulkDeleteRolesRequest(**payload)
        svc.delete_roles_bulk(role_ids=req.role_ids, context=g.auth)
        # ERP/Frappe-style: message only, no data
        return api_success(message="Roles deleted successfully.", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("delete_roles_bulk failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)


# ---------- Set user roles (assign/unassign together) ----------

@bp.put("/set/user/<int:user_id>/roles")
@require_permission("Role", "Assign")
def set_user_roles(user_id: int):
    _ = get_current_user()  # ensures session; g.auth set by middleware
    payload = request.get_json(silent=True) or {}
    try:
        req = SetUserRolesRequest(**payload)
        svc.set_user_roles_for_user(
            target_user_id=user_id,
            role_ids=req.role_ids,
            context=g.auth,
        )
        return api_success(message="User roles updated.", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("set_user_roles failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)

# ---------- Permission overrides ----------

@bp.post("/users/<int:user_id>/overrides")
@require_permission("PermissionOverride", "Manage")
def upsert_override(user_id: int):
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = OverrideCreateRequest(**payload)
        svc.upsert_override(
            target_user_id=user_id,
            permission_id=req.permission_id,
            is_allowed=req.is_allowed,
            reason=req.reason,
            company_id=req.company_id,
            branch_id=req.branch_id,
            context=g.auth,
        )
        return api_success(message="Override upserted", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("upsert_override failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)


@bp.delete("/users/<int:user_id>/overrides")
@require_permission("PermissionOverride", "Manage")
def delete_override(user_id: int):
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = OverrideDeleteRequest(**payload)
        svc.delete_override(
            target_user_id=user_id,
            permission_id=req.permission_id,
            company_id=req.company_id,
            branch_id=req.branch_id,
            context=g.auth,
        )
        return api_success(message="Override deleted", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("delete_override failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)

# ---------- User constraints ----------

@bp.post("/users/<int:user_id>/constraints")
@require_permission("UserConstraint", "Manage")
def create_user_constraint(user_id: int):
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = UserConstraintCreateRequest(**payload)
        svc.create_user_constraint(
            target_user_id=user_id,
            doctype_id=req.doctype_id,
            field_name=req.field_name,
            ref_doctype_id=req.ref_doctype_id,
            ref_id=req.ref_id,
            allow_children=req.allow_children,
            context=g.auth,
        )
        return api_success(message="User constraint created", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("create_user_constraint failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)


@bp.delete("/users/<int:user_id>/constraints")
@require_permission("UserConstraint", "Manage")
def delete_user_constraint(user_id: int):
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = UserConstraintDeleteRequest(**payload)
        svc.delete_user_constraint(
            target_user_id=user_id,
            doctype_id=req.doctype_id,
            field_name=req.field_name,
            ref_doctype_id=req.ref_doctype_id,
            ref_id=req.ref_id,
            context=g.auth,
        )
        return api_success(message="User constraint deleted", data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except Exception as e:
        log.exception("delete_user_constraint failed: %s", e)
        return api_error("Unexpected server error.", status_code=500)
