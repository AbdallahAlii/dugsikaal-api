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

from app.common.cache.api import get_doctype_list
from app.common.cache.core_cache import get_version
from app.common.cache.cache_keys import coa_balance_version_key
from app.application_accounting.query_builders.coa_tree_builders import (
    load_coa_tree, load_coa_children,
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
        # ERP-style, user-friendly message from subscription guard
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
    vB = get_version(coa_balance_version_key(company_id)) if include_balances else 0

    scope_key = f"co:{company_id}"
    params = {
        "root_id": root_id or None,
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

    data = get_doctype_list(
        module_name="accounting",
        entity_name="coa_tree",
        scope_key=scope_key,
        params=params,
        builder=builder,
        ttl=30,
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
        log.info("create_account: company_id=%s user_id=%s payload=%s",
                 ctx.company_id, ctx.user_id, payload_json)

        # 🔍 Pydantic validation with clear error
        try:
            payload = AccountCreate.model_validate(payload_json)
        except ValidationError as ve:
            log.warning("ValidationError in create_account: %s", ve, exc_info=True)
            # You can simplify this message if errors() is too verbose
            return api_error(
                f"Invalid account data: {ve}",
                status_code=422,
            )

        out = account_service.create_account(payload, ctx)
        return api_success(data=out.model_dump(), status_code=201)

    except BizValidationError as e:
        # Business-level ERP messages (our own rules)
        log.info("BizValidationError in create_account: %s", e)
        return api_error(str(e), status_code=422)

    except HTTPException:
        raise

    except Exception as e:
        # Unexpected bug – log full stack for you, generic message for user
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
        payload = AccountUpdate(**payload_json)
        out = account_service.update_account(account_id, payload=payload, ctx=ctx)
        return api_success(data=out.model_dump())

    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException:
        raise
    except Exception:
        db.session.rollback()
        return api_error("Unexpected error while updating account.", status_code=400)


@bp.delete("/accounts/<int:account_id>/delete")
@require_permission("Account", "Delete")
def delete_account(account_id: int):
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Unauthorized", status_code=401)

    try:
        account_service.delete_account(account_id, ctx=ctx)
        return api_success(message="Account deleted successfully.", data=None)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException:
        raise
    except Exception:
        db.session.rollback()
        return api_error("Unexpected error while deleting account.", status_code=400)
