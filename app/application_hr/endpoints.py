# app/hr/endpoints.py
from __future__ import annotations
import json
from typing import Optional
from flask import Blueprint, request, g

from app.application_hr.schemas.schemas import EmployeeCreate
from app.application_hr.services.services import HrService
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user  # ensures session/profile present


bp = Blueprint("hr", __name__, url_prefix="/api/hr")
svc = HrService()


@bp.post("/employees/create")
@require_permission("Employee", "Create")
def create_employee():
    """
    Accepts:
      - application/json (body = EmployeeCreate)
      - multipart/form-data (payload=<json EmployeeCreate>, file=<image>)

    Rules:
      - System Admin MUST provide company_id; can choose any branch that belongs to that company.
      - Global “*:*” can create in any branch of their own company (DB-checked).
      - Regular users can create ONLY in their own branch(es) (checked against affiliations, no DB).
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

    return api_success(message=resp.message, data={"employee": resp.employee}, status_code=201)