from __future__ import annotations
from typing import Set
from flask import Blueprint, request, g

from app.common.api_response import api_success, api_error
from app.auth.deps import get_current_user
from app.navigation_workspace.services.directory_service import DocTypeDirectoryService
from app.navigation_workspace.services.visibility_services import NavService
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

bp = Blueprint("navigation", __name__, url_prefix="api/navigation")

def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Unauthorized")
    return ctx

@bp.get("/nav/workspaces")
def get_workspaces_nav():
    try:
        ctx = _ctx()
        q_company = request.args.get("company_id", type=int)
        q_branch  = request.args.get("branch_id", type=int)

        tree = NavService().build_nav_tree(context=ctx, company_id=q_company, branch_id=q_branch)
        if not tree.workspaces:
            return api_success(
                data={"workspaces": []},
                message="You don’t have access to any modules. Please contact your administrator."
            )
        return api_success(tree.model_dump(), message="OK")

    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to build navigation.", status_code=500)

@bp.get("/doctypes")
def list_doctypes():
    try:
        ctx = _ctx()
        perms: Set[str] = set(ctx.permissions or [])
        directory = DocTypeDirectoryService().build_directory(perms=perms)
        if not directory.doctypes:
            return api_success(
                data={"doctypes": []},
                message="You don’t have access to any document types. Please contact your administrator."
            )
        return api_success(directory.model_dump(), message="OK")
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to build DocType directory.", status_code=500)

@bp.get("/doctypes/<string:slug>")
def get_doctype(slug: str):
    try:
        ctx = _ctx()
        perms: Set[str] = set(ctx.permissions or [])
        details = DocTypeDirectoryService().get_doctype_details(perms=perms, slug=slug)
        if not details:
            return api_error("DocType not found or not permitted.", status_code=404)
        return api_success(details.model_dump(), message="OK")
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to load DocType.", status_code=500)
