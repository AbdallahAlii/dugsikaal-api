from __future__ import annotations
import logging, json
from functools import wraps
from typing import Callable, Any, Dict, Tuple

from flask import Blueprint, request, jsonify, g
from werkzeug.exceptions import BadRequest, NotFound, Forbidden

from app.application_doctypes.core_dropdowns.config import get_dropdown_config
from app.application_doctypes.core_dropdowns.service import dropdown_service
from app.auth.deps import get_current_user
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

log = logging.getLogger(__name__)
dropdowns_bp = Blueprint("dropdowns", __name__, url_prefix="/api/dropdowns")

# ========================= helpers =========================

def _ctx() -> AffiliationContext:
    """Ensure g.current_user / g.auth is populated, then return AffiliationContext."""
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx
def _normalize_order(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).lower().strip()
    return s if s in ("asc", "desc") else "asc"

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


# ========================= Scoped Batch (new) =========================

@dropdowns_bp.post("/<string:module_name>/<string:name>/batch")
def get_dropdown_scoped_batch(module_name: str, name: str):
    """
    POST /api/dropdowns/<module>/<name>/batch

    Body (simple, no repetition of module/name):
    {
      "lines": [
        { "row_id": "r1", "params": { "item_id": 28 } },
        { "row_id": "r2", "params": { "item_id": 31 } }
      ],
      // Optional global defaults (applied if a line doesn't override):
      "q": null, "limit": null, "offset": null, "sort": null, "order": "asc", "fresh": false
    }

    Response:
    {
      "module": "<module>",
      "name": "<name>",
      "lines": [
        { "row_id": "r1", "data": [...], "total": 2, "has_more": false },
        { "row_id": "r2", "data": [...], "total": 3, "has_more": false }
      ]
    }
    """
    try:
        ctx = _ctx()  # ensure g.auth

        # Config (to read defaults) and RBAC once for the whole batch
        try:
            cfg = get_dropdown_config(module_name, name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

        tag = (str(cfg.permission_tag).upper() if cfg.permission_tag else None)
        if tag and tag != "PUBLIC":
            guard = require_permission(cfg.permission_tag, "READ")

            @guard
            def _permit_probe():
                return None

            _permit_probe()  # raises Forbidden if unauthorized

        raw = request.get_json(silent=True) or {}
        lines = raw.get("lines")
        if not isinstance(lines, list) or not lines:
            raise BadRequest("lines must be a non-empty list")

        # Optional global defaults
        g_q      = raw.get("q")
        g_limit  = raw.get("limit")
        g_offset = raw.get("offset")
        g_sort   = raw.get("sort")
        g_order  = _normalize_order(raw.get("order"))
        g_fresh  = bool(raw.get("fresh", False))

        # In-request memoization to avoid repeated identical DB calls
        memo: Dict[Tuple, Dict[str, Any]] = {}
        results = []

        for ln in lines:
            row_id = ln.get("row_id")
            params = ln.get("params") or {}

            q      = ln.get("q", g_q)
            limit  = int(ln.get("limit", g_limit if g_limit is not None else (cfg.default_limit or 20)))
            limit  = max(1, min(limit, cfg.max_limit or 200))
            offset = int(ln.get("offset", g_offset if g_offset is not None else 0))
            sort   = ln.get("sort", g_sort)
            order  = _normalize_order(ln.get("order", g_order)) or "asc"
            fresh  = bool(ln.get("fresh", g_fresh))

            # Memo key
            try:
                filters_key = json.dumps(params, sort_keys=True, default=str)
            except Exception:
                filters_key = str(sorted(params.items()))
            key = (module_name, name, q or "", limit, offset, sort or "", order, int(fresh), filters_key)

            if key in memo:
                res = memo[key]
            else:
                res = dropdown_service.get_options(
                    module_name=module_name,
                    name=name,
                    user_context=ctx,
                    q=q,
                    limit=limit,
                    offset=offset,
                    params=params,
                    fresh=fresh,
                    sort=sort,
                    order=order,
                )
                memo[key] = res

            results.append({
                "row_id": row_id,
                "data": res["data"],
                "total": res["total"],
                "has_more": res["has_more"],
            })

        return jsonify({"module": module_name, "name": name, "lines": results}), 200

    except Forbidden as e:
        return jsonify({"error": e.description if hasattr(e, "description") else str(e)}), 403
    except BadRequest as e:
        return jsonify({"error": str(e)}), 422
    except Exception:
        log.exception("Unhandled error in POST /api/dropdowns/%s/%s/batch", module_name, name)
        return jsonify({"error": "Internal server error"}), 500