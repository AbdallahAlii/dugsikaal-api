from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, g
from werkzeug.exceptions import HTTPException, NotFound, Forbidden, BadRequest

from app.application_meta.service import meta_service
from app.application_meta.schemas import DoctypeMetaOut, ListViewUpdateIn
from app.common.api_response import api_success, api_error
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission  # if you want to protect meta

log = logging.getLogger(__name__)

meta_bp = Blueprint("meta", __name__, url_prefix="/api/meta")


def _short_msg(e: Exception, default: str) -> str:
    if isinstance(e, HTTPException):
        return (e.description or default).strip()
    return default


@meta_bp.route("/doctype/<string:doctype_name>", methods=["GET"])
def get_doctype_meta(doctype_name: str):
    """
    Returns Doctype meta including fields, permissions and links.

    You can pass ?company_id= to get company-specific overrides; if omitted,
    context.company_id is used.
    """
    try:
        ctx: AffiliationContext = getattr(g, "auth", None)
        if not ctx:
            return api_error("Authentication required.", status_code=401)

        # company_id override from query
        company_id_param: Optional[str] = request.args.get("company_id") or None
        company_id: Optional[int] = None
        if company_id_param:
            try:
                company_id = int(company_id_param)
            except ValueError:
                return api_error("Invalid company_id.", status_code=400)

        meta = meta_service.get_doctype_meta(
            name=doctype_name,
            ctx=ctx,
            company_id=company_id,
        )

        data = meta.model_dump()
        return api_success(data, "Success", 200)

    except NotFound as e:
        return api_error(_short_msg(e, "Doctype not found."), status_code=404)
    except Forbidden as e:
        return api_error(_short_msg(e, "Not allowed."), status_code=403)
    except Exception:
        log.exception("Unhandled error in get_doctype_meta")
        return api_error("Internal server error.", status_code=500)


# ----------------------------------------------------------------------
# NEW: PATCH /api/meta/doctype/<doctype_name>/listview
# Customize list view per company (Frappe-like "Customize Columns")
# ----------------------------------------------------------------------
@meta_bp.route("/doctype/<string:doctype_name>/listview", methods=["PATCH"])
def update_doctype_listview(doctype_name: str):
    """
    Allows a company admin (or system admin) to customize list-view columns:

      - which fields appear (in_list_view)
      - in which order (idx)
      - optionally: in_filter, in_quick_entry

    Body example:
      {
        "company_id": 10,
        "fields": [
          { "fieldname": "code", "in_list_view": true,  "idx": 1 },
          { "fieldname": "full_name", "in_list_view": true, "idx": 2 },
          { "fieldname": "status", "in_list_view": true, "idx": 3 },
          { "fieldname": "branch_name", "in_list_view": true, "idx": 4 }
        ]
      }
    """
    try:
        ctx: AffiliationContext = getattr(g, "auth", None)
        if not ctx:
            return api_error("Authentication required.", status_code=401)

        # 🔒 Optional: protect with a permission (adjust tag to your RBAC)
        # e.g. "Doctype Meta" or "System Settings"
        decorated = require_permission("Doctype Meta", "WRITE")(lambda: None)
        decorated()

        # Parse payload
        try:
            json_payload = request.get_json(force=True, silent=False)
        except Exception:
            return api_error("Invalid JSON body.", status_code=400)

        try:
            payload = ListViewUpdateIn(**json_payload)
        except Exception as e:
            log.warning("Invalid listview update payload: %s", e)
            return api_error("Invalid payload.", status_code=400)

        # Apply config
        meta_service.update_list_view_config(
            name=doctype_name,
            ctx=ctx,
            payload=payload,
        )

        return api_success({}, "List view updated.", 200)

    except BadRequest as e:
        return api_error(_short_msg(e, "Bad request."), status_code=400)
    except NotFound as e:
        return api_error(_short_msg(e, "Doctype not found."), status_code=404)
    except Forbidden as e:
        return api_error(_short_msg(e, "Not allowed."), status_code=403)
    except Exception:
        log.exception("Unhandled error in update_doctype_listview")
        return api_error("Internal server error.", status_code=500)
