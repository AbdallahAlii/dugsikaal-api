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

from app.application_education.institution.academic_service import EducationService
from app.application_education.institution.schemas import (
    EducationSettingsCreate,
    EducationSettingsUpdate,
    AcademicYearCreate,
    AcademicYearUpdate,
    AcademicTermCreate,
    AcademicTermUpdate,
    EducationSettingsOut,
    AcademicYearOut,
    AcademicTermOut,
)

bp = Blueprint("academic", __name__, url_prefix="/api/academic")
svc = EducationService()

ACADEMICS_WORKSPACE_SLUG = "academics"
log = logging.getLogger(__name__)


@bp.before_request
def _guard_academics_subscription():
    if request.method == "OPTIONS":
        return
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Authentication required.", status_code=401)

    ok, msg = check_workspace_subscription(ctx, workspace_slug=ACADEMICS_WORKSPACE_SLUG)
    if not ok:
        return api_error(msg, status_code=403)


# ============================================================
# SETTINGS
# ============================================================

@bp.post("/education-settings/create")
@require_permission("Education Settings", "CREATE")
def create_settings():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = EducationSettingsCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.create_settings(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"settings": out}, status_code=201)


@bp.put("/education-settings/<int:company_id>/update")
@require_permission("Education Settings", "UPDATE")
def update_settings(company_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = EducationSettingsUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.update_settings(company_id=company_id, payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"settings": out}, status_code=200)


# ============================================================
# ACADEMIC YEAR
# ============================================================

@bp.post("/academic-years/create")
@require_permission("Academic Year", "CREATE")
def create_year():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = AcademicYearCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.create_year(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"academic_year": out}, status_code=201)


@bp.put("/academic-years/<int:year_id>/update")
@require_permission("Academic Year", "UPDATE")
def update_year(year_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = AcademicYearUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.update_year(year_id=year_id, payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"academic_year": out}, status_code=200)


# ============================================================
# ACADEMIC TERM
# ============================================================

@bp.post("/academic-terms/create")
@require_permission("Academic Term", "CREATE")
def create_term():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = AcademicTermCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.create_term(payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"academic_term": out}, status_code=201)


@bp.put("/academic-terms/<int:term_id>/update")
@require_permission("Academic Term", "UPDATE")
def update_term(term_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = AcademicTermUpdate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return api_error(humanize_pydantic_error(e), status_code=422)
    except Exception:
        return api_error("Invalid JSON body.", status_code=422)

    ok, msg, out = svc.update_term(term_id=term_id, payload=payload, context=ctx)
    if not ok or not out:
        return api_error(msg, status_code=400)

    return api_success(message=msg, data={"academic_term": out}, status_code=200)
