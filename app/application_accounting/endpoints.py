# app/application_accounting/chart_of_accounts/endpoints_coa.py
from __future__ import annotations

import logging

from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user
from config.database import db

from app.common.cache.cache import get_version
from app.common.cache.invalidation import bump_company_list, bump_version
from app.common.cache import keys

from app.application_accounting.query_builders.coa_tree_builders import (
    load_coa_tree,
    load_coa_children,
)
from app.application_accounting.chart_of_accounts.services.account_service import AccountService
from app.application_accounting.chart_of_accounts.schemas.account_schemas import (
    AccountCreate,
    AccountUpdate,
)

# 🔐 workspace subscription guard
from app.navigation_workspace.services.subscription_guards import check_workspace_subscription

log = logging.getLogger(__name__)
bp = Blueprint("accounts_coa", __name__, url_prefix="/api/v1/coa")
account_service = AccountService()

# 👉 must match navigation_workspace.workspace.slug for Accounts module
ACCOUNTS_WORKSPACE_SLUG = "accounting"

# Any Accounts endpoints that should be allowed even if Accounts module is not subscribed
ACCOUNTS_SUBSCRIPTION_EXEMPT_ENDPOINTS = set()

# ---- Cache entity names (namespace stable) ----
COA_TREE_ENTITY = "coa_tree"
COA_CHILDREN_ENTITY = "coa_children"


def coa_balance_version_key(company_id: int) -> str:
    """
    Replacement for the old cache_keys.coa_balance_version_key(company_id).
    We keep a stable, explicit vkey that you can bump whenever balances change.
    """
    return keys.v_list(f"accounting:coa_balance:scope:co:{int(company_id)}")


def bump_coa_balance(company_id: int) -> int:
    """
    Call this after posting GL entries / journal / payments etc. (anything affecting balances).
    Best-effort. If Redis is down -> returns 0.
    """
    return bump_version(coa_balance_version_key(company_id))


@bp.before_request
def _guard_accounts_subscription():
    """
    Runs for every /api/v1/coa/* request (after global auth middleware).

    Enforces:
      - user is authenticated (g.auth present)
      - company has Accounts workspace in its packages
      - Accounts workspace is not disabled by visibility
    """
    # Allow CORS preflight
    if request.method == "OPTIONS":
        return

    # Skip some endpoints if you want them to work even when Accounts is not subscribed
    if request.endpoint in ACCOUNTS_SUBSCRIPTION_EXEMPT_ENDPOINTS:
        return

    # Global auth middleware should already have attached g.auth
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Authentication required.", status_code=401)

    ok, msg = check_workspace_subscription(ctx, workspace_slug=ACCOUNTS_WORKSPACE_SLUG)
    if not ok:
        return api_error(msg, status_code=403)


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
    vB = get_version(coa_balance_version_key(company_id), default=0) if include_balances else 0

    # Company-scope cache key (shared for all branches in same company)
    scope_key = f"co:{company_id}"

    # Params must include anything that affects output, including vB
    params = {
        "root_id": int(root_id) if (root_id and str(root_id).isdigit()) else (root_id or None),
        "depth": int(depth),
        "include_balances": 1 if include_balances else 0,
        "include_company_context": 1 if include_company_context else 0,
        "unwrap_single_root": 1 if unwrap_single_root else 0,
        "vB": int(vB),
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

    # New cache path: entity_scope -> "<module>:<entity>:scope:<scope_key>"
    entity_scope = f"accounting:{COA_TREE_ENTITY}:scope:{scope_key}"

    from app.common.cache.cache import get_or_build_list  # local import to avoid cycles in some apps
    data = get_or_build_list(entity_scope, params=params, builder=builder, ttl=30)

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

    try:
        parent_id_int = int(parent_id)
    except Exception:
        return api_error("Invalid parent_id", status_code=422)

    include_balances = request.args.get("include_balances", "1") == "1"
    vB = get_version(coa_balance_version_key(company_id), default=0) if include_balances else 0

    scope_key = f"co:{company_id}"
    params = {
        "parent_id": int(parent_id_int),
        "include_balances": 1 if include_balances else 0,
        "vB": int(vB),
    }

    def builder():
        return load_coa_children(
            s=db.session,
            ctx=ctx,
            company_id=company_id,
            parent_id=parent_id_int,
            include_balances=include_balances,
        )

    entity_scope = f"accounting:{COA_CHILDREN_ENTITY}:scope:{scope_key}"

    from app.common.cache.cache import get_or_build_list  # local import to avoid cycles in some apps
    data = get_or_build_list(entity_scope, params=params, builder=builder, ttl=30)

    return api_success(data=data)


@bp.post("/<int:company_id>/accounts/create")
@require_permission("Account", "Create")
def create_account(company_id: int):
    """
    POST /api/v1/coa/<company_id>/accounts/create
    Body: AccountCreate JSON
    """
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    if ctx.company_id != company_id:
        return api_error("Forbidden: company mismatch.", status_code=403)

    try:
        payload_json = request.get_json(silent=True) or {}
        log.info("create_account: company_id=%s user_id=%s payload=%s", ctx.company_id, ctx.user_id, payload_json)

        # Pydantic validation with clear error
        try:
            payload = AccountCreate.model_validate(payload_json)
        except ValidationError as ve:
            log.warning("ValidationError in create_account: %s", ve, exc_info=True)
            return api_error(f"Invalid account data: {ve}", status_code=422)

        out = account_service.create_account(payload, ctx)

        # ✅ Invalidate after successful create
        try:
            # COA tree/children are company-wide views
            bump_company_list("accounting", COA_TREE_ENTITY, ctx, company_id)
            bump_company_list("accounting", COA_CHILDREN_ENTITY, ctx, company_id)
        except Exception:
            log.exception("[cache] failed to bump COA caches after create_account")

        return api_success(data=out.model_dump(), status_code=201)

    except BizValidationError as e:
        log.info("BizValidationError in create_account: %s", e)
        return api_error(str(e), status_code=422)

    except HTTPException:
        raise

    except Exception:
        db.session.rollback()
        log.exception("Unhandled error in create_account")
        return api_error("Unexpected error while creating account.", status_code=500)


@bp.put("/accounts/<int:account_id>/update")
@require_permission("Account", "Update")
def update_account(account_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        payload_json = request.get_json(force=True) or {}

        # keep your schema behavior: AccountUpdate(**payload_json)
        payload = AccountUpdate(**payload_json)

        out = account_service.update_account(account_id, payload=payload, ctx=ctx)

        # ✅ Invalidate after successful update
        try:
            # Determine company id for cache scope
            # Prefer returned object, else fallback to ctx.company_id
            co = int(getattr(out, "company_id", None) or ctx.company_id or 0)
            if co:
                bump_company_list("accounting", COA_TREE_ENTITY, ctx, co)
                bump_company_list("accounting", COA_CHILDREN_ENTITY, ctx, co)
        except Exception:
            log.exception("[cache] failed to bump COA caches after update_account")

        return api_success(data=out.model_dump())

    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException:
        raise
    except Exception:
        db.session.rollback()
        log.exception("Unexpected error while updating account")
        return api_error("Unexpected error while updating account.", status_code=400)


@bp.delete("/accounts/<int:account_id>/delete")
@require_permission("Account", "Delete")
def delete_account(account_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        # If your service returns the deleted account or company_id, use it.
        # Otherwise we fall back to ctx.company_id.
        deleted_company_id = None
        try:
            deleted_company_id = account_service.delete_account(account_id, ctx=ctx)
        except TypeError:
            # service returns None; call it without expecting return
            account_service.delete_account(account_id, ctx=ctx)

        # ✅ Invalidate after successful delete
        try:
            co = int(deleted_company_id or ctx.company_id or 0)
            if co:
                bump_company_list("accounting", COA_TREE_ENTITY, ctx, co)
                bump_company_list("accounting", COA_CHILDREN_ENTITY, ctx, co)
        except Exception:
            log.exception("[cache] failed to bump COA caches after delete_account")

        return api_success(message="Account deleted successfully.", data=None)

    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException:
        raise
    except Exception:
        db.session.rollback()
        log.exception("Unexpected error while deleting account")
        return api_error("Unexpected error while deleting account.", status_code=400)