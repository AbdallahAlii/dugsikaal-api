#
#
# # application_doctypes/endpoint.py
#
# from __future__ import annotations
#
# import json
# import logging
# from functools import wraps
# from typing import Callable, Optional
#
# from flask import Blueprint, request, g, jsonify, abort
# from werkzeug.exceptions import BadRequest, NotFound, Forbidden
#
# from app.application_doctypes.core_lists.config import get_list_config, get_detail_config
# from app.application_doctypes.core_lists.schemas import ListResponse, DetailResponse
# from app.application_doctypes.core_lists.service import list_service, detail_service
# # NOTE: get_current_user is no longer needed here
# # from app.auth.deps import get_current_user
# from app.security.rbac_effective import AffiliationContext
# from app.security.rbac_guards import attach_auth_context, require_permission
#
# log = logging.getLogger(__name__)
#
# docypelist_bp = Blueprint("docypelists", __name__, url_prefix="/api/docypelists")
#
#
#
#
# # -------------------------------------------
# # Dynamic list permission using existing decorators
# # -------------------------------------------
# def require_list_permission(func: Callable):
#     """
#     Looks up the list config, then delegates to the `require_permission`
#     decorator using the config's permission_tag and 'read' action.
#     """
#     @wraps(func)
#     def _wrapped(module_name: str, entity_name: str, *args, **kwargs):
#         try:
#             cfg = get_list_config(module_name, entity_name)
#         except ValueError as e:
#             raise NotFound(str(e))
#
#         # Dynamically apply the require_permission decorator
#         decorated_func = require_permission(cfg.permission_tag, "READ")(func)
#         return decorated_func(module_name, entity_name, *args, **kwargs)
#
#     return _wrapped
#
#
# def require_detail_permission(func: Callable):
#     @wraps(func)
#     def _wrapped(module_name: str, entity_name: str, *args, **kwargs):
#         try:
#             cfg = get_detail_config(module_name, entity_name)
#         except ValueError as e:
#             raise NotFound(str(e))
#         decorated_func = require_permission(cfg.permission_tag, "READ")(func)
#         return decorated_func(module_name, entity_name, *args, **kwargs)
#     return _wrapped
# # -------------
# # List endpoint
# # -------------
# # @docypelist_bp.route("/<string:module_name>/<string:entity_name>", methods=["GET"])
# # @require_list_permission
# # def get_document_list(module_name: str, entity_name: str):
# #     try:
# #         args = request.args
# #         page = max(1, int(args.get("page", 1)))
# #         per_page = min(max(int(args.get("per_page", 20)), 1), 500)
# #         sort = args.get("sort", "created_at")
# #         order = (args.get("order") or "desc").lower()
# #         search = (args.get("search") or None)
# #
# #         # Parse filters JSON safely
# #         filters_raw = args.get("filters", "{}")
# #         try:
# #             filters_dict = json.loads(filters_raw) if filters_raw else {}
# #             if not isinstance(filters_dict, dict):
# #                 raise BadRequest("filters must be a JSON object")
# #         except Exception as e:
# #             return jsonify({"error": f"Invalid filters JSON: {e}"}), 422
# #
# #         # Service call (sync)
# #         # g.auth is now guaranteed to exist due to the global middleware
# #         ctx: AffiliationContext = g.auth
# #         result = list_service.get_list(
# #             module_name=module_name,
# #             entity_name=entity_name,
# #             user_context=ctx,
# #             page=page,
# #             per_page=per_page,
# #             sort=sort,
# #             order=order,
# #             search=search,
# #             filters=filters_dict,
# #         )
# #
# #         total = result["total"]
# #         resp = ListResponse(
# #             data=result["data"],
# #             pagination={
# #                 "page": page,
# #                 "per_page": per_page,
# #                 "total_items": total,
# #                 "total_pages": (total + per_page - 1) // per_page,
# #             },
# #         )
# #         # Pydantic v1/v2 compatibility
# #         data = getattr(resp, "model_dump", getattr(resp, "dict"))()
# #         return jsonify(data), 200
# #
# #     except NotFound as e:
# #         return jsonify({"error": str(e)}), 404
# #     except Forbidden as e:
# #         return jsonify({"error": str(e)}), 403
# #     except BadRequest as e:
# #         return jsonify({"error": str(e)}), 400
# #     except Exception:
# #         log.exception("Unhandled error in get_document_list")
# #         return jsonify({"error": "Internal server error"}), 500
# @docypelist_bp.route("/<string:module_name>/<string:entity_name>", methods=["GET"])
# @require_list_permission
# def get_document_list(module_name: str, entity_name: str):
#     try:
#         args = request.args
#         page = max(1, int(args.get("page", 1)))
#         per_page = min(max(int(args.get("per_page", 20)), 1), 500)
#         sort = args.get("sort", "created_at")
#         order = (args.get("order") or "desc").lower()
#         search = (args.get("search") or None)
#
#         # Parse filters JSON safely
#         filters_raw = args.get("filters", "{}")
#         try:
#             filters_dict = json.loads(filters_raw) if filters_raw else {}
#             if not isinstance(filters_dict, dict):
#                 raise BadRequest("filters must be a JSON object")
#         except Exception as e:
#             return jsonify({"error": f"Invalid filters JSON: {e}"}), 422
#
#         # CHANGE: merge date-related query params into filters so callers can pass plain
#         # ?posting_date_from=...&posting_date_to=... (without filters={})
#         cfg = get_list_config(module_name, entity_name)
#
#         # CHANGE: generic date keys (field-agnostic)
#         _generic_date_keys = ["on_date", "date", "date_from", "date_to", "from_date", "to_date"]
#         for k in _generic_date_keys:
#             if k in args and k not in filters_dict:
#                 filters_dict[k] = args.get(k)
#
#         # CHANGE: field-specific keys for any declared filter_fields
#         # (accept <field>, <field>_from, <field>_to if present in query string)
#         for fname in (cfg.filter_fields or {}).keys():
#             if fname in args and fname not in filters_dict:
#                 filters_dict[fname] = args.get(fname)
#             k_from = f"{fname}_from"
#             k_to = f"{fname}_to"
#             if k_from in args and k_from not in filters_dict:
#                 filters_dict[k_from] = args.get(k_from)
#             if k_to in args and k_to not in filters_dict:
#                 filters_dict[k_to] = args.get(k_to)
#
#         # CHANGE: safety net — accept any *_from / *_to present in query string
#         for k in args.keys():
#             if (k.endswith("_from") or k.endswith("_to")) and (k not in filters_dict):
#                 filters_dict[k] = args.get(k)
#
#         # Service call (sync)
#         # g.auth is now guaranteed to exist due to the global middleware
#         ctx: AffiliationContext = g.auth
#         result = list_service.get_list(
#             module_name=module_name,
#             entity_name=entity_name,
#             user_context=ctx,
#             page=page,
#             per_page=per_page,
#             sort=sort,
#             order=order,
#             search=search,
#             filters=filters_dict,
#         )
#
#         total = result["total"]
#         resp = ListResponse(
#             data=result["data"],
#             pagination={
#                 "page": page,
#                 "per_page": per_page,
#                 "total_items": total,
#                 "total_pages": (total + per_page - 1) // per_page,
#             },
#         )
#         # Pydantic v1/v2 compatibility
#         data = getattr(resp, "model_dump", getattr(resp, "dict"))()
#         return jsonify(data), 200
#
#     except NotFound as e:
#         return jsonify({"error": str(e)}), 404
#     except Forbidden as e:
#         return jsonify({"error": str(e)}), 403
#     except BadRequest as e:
#         return jsonify({"error": str(e)}), 400
#     except Exception:
#         log.exception("Unhandled error in get_document_list")
#         return jsonify({"error": "Internal server error"}), 500
#
# # -------------
# # Detail endpoint (supports ?by= and ?fresh=1)
# # -------------
# @docypelist_bp.route("/<string:module_name>/<string:entity_name>/<string:identifier>", methods=["GET"])
# @require_detail_permission
# def get_document_detail(module_name: str, entity_name: str, identifier: str):
#     try:
#         args = request.args
#         by: Optional[str] = (args.get("by") or "").strip() or None
#         fresh = (args.get("fresh") or "0").strip() in ("1", "true", "True")
#
#         ctx: AffiliationContext = g.auth
#         result = detail_service.get_detail(
#             module_name=module_name,
#             entity_name=entity_name,
#             by=by,
#             identifier=identifier,
#             user_context=ctx,
#             fresh=fresh,
#         )
#
#         if result is None:
#             raise NotFound("Document not found or you do not have permission to view it.")
#
#         resp = DetailResponse(data=result)
#         data = getattr(resp, "model_dump", getattr(resp, "dict"))()
#         return jsonify(data), 200
#
#     except NotFound as e:
#         return jsonify({"error": str(e)}), 404
#     except Forbidden as e:
#         return jsonify({"error": str(e)}), 403
#     except BadRequest as e:
#         return jsonify({"error": str(e)}), 400
#     except Exception:
#         log.exception("Unhandled error in get_document_detail")
#         return jsonify({"error": "Internal server error"}), 500

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
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission
from app.common.api_response import api_success, api_error

log = logging.getLogger(__name__)

docypelist_bp = Blueprint("docypelists", __name__, url_prefix="/api/docypelists")


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
