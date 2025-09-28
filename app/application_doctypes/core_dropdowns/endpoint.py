from __future__ import annotations
import logging, json
from functools import wraps
from typing import Callable

from flask import Blueprint, request, jsonify, g
from werkzeug.exceptions import BadRequest, NotFound, Forbidden

from app.application_doctypes.core_dropdowns.config import get_dropdown_config
from app.application_doctypes.core_dropdowns.service import dropdown_service
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

log = logging.getLogger(__name__)
dropdowns_bp = Blueprint("dropdowns", __name__, url_prefix="/api/dropdowns")

def require_dropdown_permission(func: Callable):
    @wraps(func)
    def _wrapped(module_name: str, name: str, *args, **kwargs):
        try:
            cfg = get_dropdown_config(module_name, name)
        except ValueError as e:
            raise NotFound(str(e))
        # Public dropdowns: skip RBAC when tag is None or "PUBLIC"
        if not cfg.permission_tag or str(cfg.permission_tag).upper() == "PUBLIC":
            return func(module_name, name, *args, **kwargs)
        # RBAC-protected
        decorated = require_permission(cfg.permission_tag, "READ")(func)
        return decorated(module_name, name, *args, **kwargs)
    return _wrapped

@dropdowns_bp.route("/<string:module_name>/<string:name>", methods=["GET"])
@require_dropdown_permission
def get_dropdown(module_name: str, name: str):
    try:
        args = request.args
        cfg = get_dropdown_config(module_name, name)

        q     = (args.get("q") or None)
        sort  = (args.get("sort") or None)
        order = (args.get("order") or None)
        if order:
            order = order.lower()
            if order not in ("asc", "desc"):
                order = "asc"

        limit_default = cfg.default_limit
        limit_max     = cfg.max_limit
        limit  = min(max(int(args.get("limit", limit_default)), 1), limit_max)
        offset = max(int(args.get("offset", 0)), 0)
        fresh  = (args.get("fresh") or "0").strip().lower() in ("1", "true")

        # Merge flat params with optional JSON filters (JSON wins)
        flat_params = {k: v for k, v in args.items()
                       if k not in {"q","limit","offset","sort","order","fresh","filters"}}
        if args.get("filters"):
            try:
                extra = json.loads(args["filters"])
                if not isinstance(extra, dict):
                    raise BadRequest("filters must be a JSON object")
                flat_params.update(extra)
            except Exception as e:
                return jsonify({"error": f"Invalid filters JSON: {e}"}), 422

        ctx: AffiliationContext = g.auth
        result = dropdown_service.get_options(
            module_name=module_name,
            name=name,
            user_context=ctx,
            q=q,
            limit=limit,
            offset=offset,
            params=flat_params,
            fresh=fresh,
            sort=sort,
            order=order,
        )

        return jsonify({
            "data": result["data"],
            "total": result["total"],
            "has_more": result["has_more"],
        }), 200

    except NotFound as e:
        return jsonify({"error": str(e)}), 404
    except Forbidden as e:
        return jsonify({"error": str(e)}), 403
    except BadRequest as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        log.exception("Unhandled error in get_dropdown")
        return jsonify({"error": "Internal server error"}), 500
