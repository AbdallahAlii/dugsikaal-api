# app/application_shareholder/endpoints.py
from __future__ import annotations

import json

from flask import Blueprint, request, g

from app.application_shareholder.schemas.schemas import (
    ShareholderCreate,
    ShareholderUpdate,
    ShareTypeCreate,
    ShareTypeUpdate,
    ShareLedgerEntryCreate,
)
from app.application_shareholder.services.services import ShareholderService
from app.common.api_response import api_success, api_error
from app.navigation_workspace.services.subscription_guards import check_workspace_subscription
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user  # ensures session/profile present

bp = Blueprint("shareholder", __name__, url_prefix="/api/shareholder")
svc = ShareholderService()

# adjust slug to whatever workspace you attach this to (e.g. "accounts")
SHAREHOLDER_WORKSPACE_SLUG = "accounting"


@bp.before_request
def _guard_shareholder_subscription():
    """
    Enforces:
      - user is authenticated (g.auth present)
      - company has Accounts/Shareholder workspace in its packages
    """
    if request.method == "OPTIONS":
        return

    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Authentication required.", status_code=401)

    ok, msg = check_workspace_subscription(ctx, workspace_slug=SHAREHOLDER_WORKSPACE_SLUG)
    if not ok:
        return api_error(msg, status_code=403)


# ======================================================================
# SHAREHOLDER ENDPOINTS
# ======================================================================

@bp.post("/shareholders/create")
@require_permission("Shareholder", "Create")
def create_shareholder():
    """
    Accepts:
      - application/json (body = ShareholderCreate)
      - multipart/form-data (payload=<json ShareholderCreate>, file=<image>)
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = ShareholderCreate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = ShareholderCreate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, resp = svc.create_shareholder(
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not resp:
        return api_error(msg, status_code=400)

    return api_success(
        message=resp.message,
        data={"shareholder": resp.shareholder},
        status_code=201,
    )


@bp.put("/shareholders/update/<int:shareholder_id>")
@require_permission("Shareholder", "Update")
def update_shareholder(shareholder_id: int):
    """
    Update Shareholder master, ERP-style (contacts replaced if provided).
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    file_storage = None
    if request.content_type and "multipart/form-data" in request.content_type:
        payload_raw = request.form.get("payload")
        if not payload_raw:
            return api_error("Missing 'payload' JSON in form-data.", status_code=422)
        try:
            payload = ShareholderUpdate.model_validate(json.loads(payload_raw))
        except Exception as e:
            return api_error(f"Invalid 'payload' JSON: {e}", status_code=422)
        file_storage = request.files.get("file")
    else:
        try:
            payload = ShareholderUpdate.model_validate(request.get_json(silent=True) or {})
        except Exception as e:
            return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, resp = svc.update_shareholder(
        shareholder_id=shareholder_id,
        payload=payload,
        context=ctx,
        file_storage=file_storage,
    )
    if not ok or not resp:
        return api_error(msg, status_code=400)

    return api_success(
        message=resp.message,
        data={"shareholder": resp.shareholder},
        status_code=200,
    )


# ======================================================================
# SHARE TYPE ENDPOINTS
# ======================================================================

@bp.post("/share-types/create")
@require_permission("Share Type", "Create")
def create_share_type():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShareTypeCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, st = svc.create_share_type(payload=payload, context=ctx)
    if not ok or not st:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={
            "share_type": {
                "id": st.id,
                "code": st.code,
                "name": st.name,
            }
        },
        status_code=201,
    )


@bp.put("/share-types/<int:share_type_id>/update")
@require_permission("Share Type", "Update")
def update_share_type(share_type_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShareTypeUpdate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, st = svc.update_share_type(
        share_type_id=share_type_id,
        payload=payload,
        context=ctx,
    )
    if not ok or not st:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={
            "share_type": {
                "id": st.id,
                "code": st.code,
                "name": st.name,
            }
        },
        status_code=200,
    )


# ======================================================================
# SHARE LEDGER ENTRY ENDPOINT
# ======================================================================

@bp.post("/share-ledger/create")
@require_permission("Share Ledger Entry", "Create")
def create_share_ledger_entry():
    """
    Basic endpoint to post share movements (Issue, Transfer, Redemption, etc.).
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload = ShareLedgerEntryCreate.model_validate(request.get_json(silent=True) or {})
    except Exception as e:
        return api_error(f"Invalid JSON body: {e}", status_code=422)

    ok, msg, sle = svc.create_share_ledger_entry(payload=payload, context=ctx)
    if not ok or not sle:
        return api_error(msg, status_code=400)

    return api_success(
        message=msg,
        data={"share_ledger_entry_id": sle.id},
        status_code=201,
    )
