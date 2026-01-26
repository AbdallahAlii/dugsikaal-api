# # app/application_doctypes/core_lists/endpoint.py
from __future__ import annotations

import json
import logging
from functools import wraps
from typing import Callable, Optional

from flask import Blueprint, request, g
from werkzeug.exceptions import HTTPException, BadRequest, NotFound, Forbidden

from app.application_doctypes.core_lists.config import get_list_config, get_detail_config
from app.application_doctypes.core_lists.schemas import ListResponse, DetailResponse
from app.application_doctypes.core_lists.service import list_service, detail_service
from app.navigation_workspace.services.subscription_guards import check_workspace_subscription
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission
from app.common.api_response import api_success, api_error

log = logging.getLogger(__name__)

docypelist_bp = Blueprint("docypelists", __name__, url_prefix="/api/docypelists")


# ----------------------------------------------------------------------
# Subscription guard for dynamic lists/detail (per module)
# ----------------------------------------------------------------------

# Map dynamic list module_name -> workspace slug used in navigation/packages.
# Only modules in this mapping will be gated by subscription/visibility.
DOCYPELIST_MODULE_TO_WORKSPACE = {
    # Education side (adjust to your actual list module names)
    # "hr": "hr",
    "access-control": "access-control",
    "accounting": "accounting",
    "inventory": "inventory",
    "buying": "buying",
    "selling": "selling",
    # Example: if you register education lists as module_name="education"
    # and you want them bound to the "student" workspace:
    # "education": "student",
}

# If you ever need some docype list/detail endpoints to bypass subscription
# (e.g. some public/system lists), add their endpoint names here:
#   "docypelists.get_document_list"
#   "docypelists.get_document_detail"
DOCYPELIST_SUBSCRIPTION_EXEMPT_ENDPOINTS = set()


@docypelist_bp.before_request
def _guard_docypelists_subscription():
    """
    Runs for every /api/docypelists/* request (after global auth middleware).

    Enforces, for modules in DOCYPELIST_MODULE_TO_WORKSPACE:
      - user is authenticated (g.auth present)
      - company has the corresponding workspace in its packages
      - workspace is not disabled by visibility

    This gives ERP-style behavior:
      • If company has no packages -> "You don’t have access to any modules..."
      • If specific module not in subscription -> "Your subscription does not include ..."
      • If module disabled by visibility -> "The <module> module has been disabled..."
    """
    # Allow CORS preflight to pass without checks
    if request.method == "OPTIONS":
        return

    # Skip selected endpoints if you add any to the exempt set
    if request.endpoint in DOCYPELIST_SUBSCRIPTION_EXEMPT_ENDPOINTS:
        return

    # Global auth middleware (before_request_session_auth) should have attached g.auth
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        # Safety net; normally require_login_globally has already enforced 401
        return api_error("Authentication required.", status_code=401)

    # For these endpoints, module_name is part of the URL:
    #   /api/docypelists/<module_name>/<entity_name>
    #   /api/docypelists/<module_name>/<entity_name>/<identifier>
    view_args = getattr(request, "view_args", None) or {}
    module_name = (view_args.get("module_name") or "").strip()

    if not module_name:
        # No module context => nothing to gate (rare)
        return

    workspace_slug = DOCYPELIST_MODULE_TO_WORKSPACE.get(module_name)
    if not workspace_slug:
        # Module not bound to any workspace: treat as system/global list and skip gating.
        # You can tighten this later by expanding the mapping.
        return

    ok, msg = check_workspace_subscription(ctx, workspace_slug=workspace_slug)
    if not ok:
        # ERP-style user-facing message from subscription guard
        return api_error(msg, status_code=403)



def _short_msg(e: Exception, default: str) -> str:
    if isinstance(e, HTTPException):
        return (e.description or default).strip()
    return default


# -------------------------------------------
# Dynamic list permission with clear resource errors
# -------------------------------------------
def require_list_permission(func: Callable):
    @wraps(func)
    def _wrapped(module_name: str, entity_name: str, *args, **kwargs):
        try:
            cfg = get_list_config(module_name, entity_name)
        except ValueError:
            # Explicit, ERP-style message that names the missing resource
            return api_error(f"Unknown resource: {module_name}/{entity_name}.", status_code=404)
        decorated_func = require_permission(cfg.permission_tag, "READ")(func)
        return decorated_func(module_name, entity_name, *args, **kwargs)
    return _wrapped


def require_detail_permission(func: Callable):
    @wraps(func)
    def _wrapped(module_name: str, entity_name: str, *args, **kwargs):
        try:
            cfg = get_detail_config(module_name, entity_name)
        except ValueError:
            return api_error(f"Unknown resource: {module_name}/{entity_name}.", status_code=404)
        decorated_func = require_permission(cfg.permission_tag, "READ")(func)
        return decorated_func(module_name, entity_name, *args, **kwargs)
    return _wrapped


# -------------
# List endpoint
# -------------
@docypelist_bp.route("/<string:module_name>/<string:entity_name>", methods=["GET"])
@require_list_permission
def get_document_list(module_name: str, entity_name: str):
    try:
        args = request.args
        page = max(1, int(args.get("page", 1)))
        per_page = min(max(int(args.get("per_page", 20)), 1), 500)
        sort = args.get("sort", "created_at")
        order = (args.get("order") or "desc").lower()
        search = (args.get("search") or None)

        # Parse filters JSON safely
        filters_raw = args.get("filters", "{}")
        try:
            filters_dict = json.loads(filters_raw) if filters_raw else {}
            if not isinstance(filters_dict, dict):
                raise BadRequest("Invalid filters.")
        except BadRequest as e:
            return api_error(_short_msg(e, "Invalid filters."), status_code=422)
        except Exception:
            return api_error("Invalid filters.", status_code=422)

        # Merge date-related params into filters
        cfg = get_list_config(module_name, entity_name)

        _generic_date_keys = ["on_date", "date", "date_from", "date_to", "from_date", "to_date"]
        for k in _generic_date_keys:
            if k in args and k not in filters_dict:
                filters_dict[k] = args.get(k)

        for fname in (cfg.filter_fields or {}).keys():
            if fname in args and fname not in filters_dict:
                filters_dict[fname] = args.get(fname)
            k_from = f"{fname}_from"
            k_to = f"{fname}_to"
            if k_from in args and k_from not in filters_dict:
                filters_dict[k_from] = args.get(k_from)
            if k_to in args and k_to not in filters_dict:
                filters_dict[k_to] = args.get(k_to)

        for k in args.keys():
            if (k.endswith("_from") or k.endswith("_to")) and (k not in filters_dict):
                filters_dict[k] = args.get(k)

        # Service call
        ctx: AffiliationContext = g.auth
        result = list_service.get_list(
            module_name=module_name,
            entity_name=entity_name,
            user_context=ctx,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
            search=search,
            filters=filters_dict,
        )

        total = result["total"]
        resp = ListResponse(
            data=result["data"],
            pagination={
                "page": page,
                "per_page": per_page,
                "total_items": total,
                "total_pages": (total + per_page - 1) // per_page,
            },
        )
        data = getattr(resp, "model_dump", getattr(resp, "dict"))()
        return api_success(data, "Success", 200)

    except NotFound as e:
        return api_error(_short_msg(e, "Not found."), status_code=404)
    except Forbidden as e:
        return api_error(_short_msg(e, "Not allowed."), status_code=403)
    except BadRequest as e:
        msg = _short_msg(e, "Invalid identifier.")
        if "Unsupported lookup" in str(e):
            msg = "Unsupported lookup."
        return api_error(msg, status_code=400)
    except Exception:
        log.exception("Unhandled error in get_document_list")
        return api_error("Internal server error.", status_code=500)


# -------------
# Detail endpoint (supports ?by= and ?fresh=1)
# -------------
@docypelist_bp.route("/<string:module_name>/<string:entity_name>/<path:identifier>", methods=["GET"])
@require_detail_permission
def get_document_detail(module_name: str, entity_name: str, identifier: str):
    try:
        args = request.args
        by: Optional[str] = (args.get("by") or "").strip() or None
        fresh = (args.get("fresh") or "0").strip() in ("1", "true", "True")

        ctx: AffiliationContext = g.auth
        result = detail_service.get_detail(
            module_name=module_name,
            entity_name=entity_name,
            by=by,
            identifier=identifier,
            user_context=ctx,
            fresh=fresh,
        )

        if result is None:
            # This is a rare path; keep it short
            return api_error("Not found.", status_code=404)

        resp = DetailResponse(data=result)
        data = getattr(resp, "model_dump", getattr(resp, "dict"))()
        return api_success(data, "Success", 200)

    except NotFound as e:
        # This includes resolver 'Item not found.' etc.
        return api_error(_short_msg(e, "Not found."), status_code=404)
    except Forbidden as e:
        return api_error(_short_msg(e, "Not allowed."), status_code=403)
    except BadRequest as e:
        msg = _short_msg(e, "Invalid identifier.")
        if "Unsupported lookup" in str(e):
            msg = "Unsupported lookup."
        return api_error(msg, status_code=400)
    except Exception:
        log.exception("Unhandled error in get_document_detail")
        return api_error("Internal server error.", status_code=500)
