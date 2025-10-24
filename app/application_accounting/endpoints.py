
from __future__ import annotations
from flask import Blueprint, request, g
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user
from config.database import db

from app.common.cache.api import get_doctype_list
from app.common.cache.core_cache import get_version
from app.common.cache.cache_keys import coa_balance_version_key
from app.application_accounting.query_builders.coa_tree_builders import (
    load_coa_tree, load_coa_children,
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

    # Parse depth ("all" -> very large)
    try:
        depth = 10**9 if depth_raw in ("all", "infinite", "max") else int(depth_raw)
    except Exception:
        return api_error("Invalid depth", status_code=422)

    # Balance version (0 when not included)
    vB = get_version(coa_balance_version_key(company_id)) if include_balances else 0

    scope_key = f"co:{company_id}"
    params = {
        "root_id": root_id or None,
        "depth": int(depth),
        "include_balances": 1 if include_balances else 0,
        "include_company_context": 1 if include_company_context else 0,
        "unwrap_single_root": 1 if unwrap_single_root else 0,
        "vB": int(vB),  # <-- balance version baked into cache key params
    }

    def builder():
        return load_coa_tree(
            s=db.session,
            ctx=ctx,
            company_id=company_id,
            root_id=root_id,
            depth=depth,
            include_balances=include_balances,
            include_company_context=include_company_context,
            unwrap_single_root=unwrap_single_root,
        )

    # entity name can be anything logical; we use 'coa_tree'
    data = get_doctype_list(
        module_name="accounting",
        entity_name="coa_tree",
        scope_key=scope_key,
        params=params,
        builder=builder,
        ttl=30,     # TTL is secondary; version changes take precedence
        enabled=True,
    )
    return api_success(data=data)


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
    vB = get_version(coa_balance_version_key(company_id)) if include_balances else 0

    scope_key = f"co:{company_id}"
    params = {
        "parent_id": int(parent_id),
        "include_balances": 1 if include_balances else 0,
        "vB": int(vB),
    }

    def builder():
        return load_coa_children(
            s=db.session,
            ctx=ctx,
            company_id=company_id,
            parent_id=parent_id,
            include_balances=include_balances,
        )

    data = get_doctype_list(
        module_name="accounting",
        entity_name="coa_children",
        scope_key=scope_key,
        params=params,
        builder=builder,
        ttl=30,
        enabled=True,
    )
    return api_success(data=data)
