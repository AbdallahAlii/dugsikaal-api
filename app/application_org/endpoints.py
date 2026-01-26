# app/application_org/endpoints.py
from __future__ import annotations

import json

from flask import Blueprint, request, g

from app.application_org.schemas.org_schemas import (
    CompanyCreate,
    CompanyUpdate,
    BranchCreate,
    BranchUpdate, CompanySetPackageRequest, CompanyDeleteRequest, CompanyPackageSetRequest, CompanyRestoreRequest,
    CompanyArchiveRequest,
)
from app.application_org.services.org_service import OrgService
from app.auth.deps import get_current_user
from app.common.api_response import api_success, api_error
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission, _is_system_admin

bp = Blueprint("platform_admin_org", __name__, url_prefix="/api/platform-admin")

svc = OrgService()

# ======================================================================
# Helpers
# ======================================================================

def _get_ctx_or_unauthorized():
    _ = get_current_user()  # ensures session + g.current_user
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return None, api_error("Unauthorized", status_code=401)
    if not _is_system_admin(ctx):
        return None, api_error("Only System Admin can perform this action.", status_code=403)
    return ctx, None


# ======================================================================
# COMPANY ENDPOINTS
# ======================================================================


@bp.post("/companies/create")
@require_permission("Company", "Create")
def create_company():
    """
    Accepts:
      - application/json (body = CompanyCreate)
      - multipart/form-data (payload=<json CompanyCreate>, file=<image>)
    Only System Admin is allowed.
    """
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = CompanyCreate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = CompanyCreate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, resp = svc.create_company(
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not resp:
        return api_error(msg, status_code=400)

    return api_success(
        message=resp.message,
        data={
            "company": resp.company,
            "owner_user": resp.owner_user,
        },
        status_code=201,
    )


@bp.post("/companies/<int:company_id>/update")
@require_permission("Company", "Update")
def update_company(company_id: int):
    """
    Update company info + optional logo.
    Accepts:
      - JSON (CompanyUpdate)
      - multipart/form-data with payload + file
    """
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = CompanyUpdate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = CompanyUpdate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_company(
        company_id=company_id,
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"company": out},
        status_code=200,
    )

@bp.post("/companies/<int:company_id>/delete")
@require_permission("Company", "Delete")
def delete_company(company_id: int):
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    try:
        payload = CompanyDeleteRequest.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg = svc.delete_company(company_id=company_id, payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=None, status_code=200)

@bp.post("/companies/<int:company_id>/archive")
@require_permission("Company", "Update")
def archive_company(company_id: int):
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    try:
        payload = CompanyArchiveRequest.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg = svc.archive_company(company_id=company_id, payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=None, status_code=200)


@bp.post("/companies/<int:company_id>/restore")
@require_permission("Company", "Update")
def restore_company(company_id: int):
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    try:
        payload = CompanyRestoreRequest.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg = svc.restore_company(company_id=company_id, payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)
    return api_success(message=msg, data=None, status_code=200)
@bp.post("/companies/<int:company_id>/packages/set")
@require_permission("Company", "Update")
def set_company_package(company_id: int):
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    try:
        payload = CompanyPackageSetRequest.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.set_company_package(company_id=company_id, payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"subscription": out}, status_code=200)



# ======================================================================
# BRANCH ENDPOINTS
# ======================================================================

@bp.post("/branches/create")
@require_permission("Branch", "Create")
def create_branch():
    """
    Create branch for a company.
    Accepts JSON or multipart/form-data (payload + file).
    """
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = BranchCreate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = BranchCreate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.create_branch(
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"branch": out},
        status_code=201,
    )


@bp.post("/branches/<int:branch_id>/update")
@require_permission("Branch", "Update")
def update_branch(branch_id: int):
    """
    Update existing branch (incl. HQ flag and image).
    """
    ctx, err = _get_ctx_or_unauthorized()
    if err:
        return err

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = BranchUpdate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = BranchUpdate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, out = svc.update_branch(
        branch_id=branch_id,
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"branch": out},
        status_code=200,
    )
