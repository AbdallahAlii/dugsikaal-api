from __future__ import annotations
from flask import Blueprint, request, g

from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user
from config.database import db

from app.application_accounting.query_builders.coa_tree_builders import (
    load_coa_tree,
    load_coa_children,
)

bp = Blueprint("accounts_coa", __name__, url_prefix="/api/v1/coa")


@bp.get("/<int:company_id>/tree")
@require_permission("Account", "Read")
def get_coa_tree(company_id: int):
    """
    GET /api/v1/coa/<company_id>/tree
      ?root_id=<id|null>
      &depth=2 | all
      &include_balances=1
      &include_company_context=1
      &unwrap_single_root=1
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    root_id = request.args.get("root_id")
    depth_raw = (request.args.get("depth") or "2").strip().lower()
    include_balances = request.args.get("include_balances", "1") == "1"
    include_company_context = request.args.get("include_company_context", "1") == "1"
    unwrap_single_root = request.args.get("unwrap_single_root", "1") == "1"

    try:
        depth = 10**9 if depth_raw in ("all", "infinite", "max") else int(depth_raw)
    except Exception:
        return api_error("Invalid depth", status_code=422)

    try:
        data = load_coa_tree(
            s=db.session,
            ctx=ctx,
            company_id=company_id,
            root_id=root_id,
            depth=depth,
            include_balances=include_balances,
            include_company_context=include_company_context,
            unwrap_single_root=unwrap_single_root,
        )
        return api_success(data=data)
    except Exception as e:
        return api_error(str(e), status_code=400)


@bp.get("/<int:company_id>/children")
@require_permission("Account", "Read")
def get_coa_children(company_id: int):
    """
    GET /api/v1/coa/<company_id>/children?parent_id=<id>&include_balances=1
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    parent_id = request.args.get("parent_id")
    if not parent_id:
        return api_error("Missing parent_id", status_code=422)

    include_balances = request.args.get("include_balances", "1") == "1"

    try:
        data = load_coa_children(
            s=db.session,
            ctx=ctx,
            company_id=company_id,
            parent_id=parent_id,
            include_balances=include_balances,
        )
        return api_success(data=data)
    except Exception as e:
        return api_error(str(e), status_code=400)
