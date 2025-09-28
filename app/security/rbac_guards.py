# from app.security.rbac_guards
from __future__ import annotations
from functools import wraps
from typing import Optional
from flask import g, jsonify
from werkzeug.exceptions import Forbidden
from app.security.rbac_effective import AffiliationContext, build_affiliation_context

from typing import Optional, Callable, Tuple
from werkzeug.exceptions import Forbidden, NotFound, BadRequest
# Attach context after you authenticate the user
def attach_auth_context(user_id: int) -> None:
    """ Attach user context (permissions, affiliations) to the global context. """
    g.auth = build_affiliation_context(user_id)


# Route-level permission check only (no scope here)
def require_permission(doctype: str, action: str):
    """ Permission check for specific doctype actions """
    required = f"{doctype}:{action}".strip()

    def _dec(fn):
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            ctx: AffiliationContext = getattr(g, "auth", None)
            if not ctx:
                return jsonify({"message": "Unauthorized"}), 401

            perms = set(ctx.permissions or [])
            # If user has wildcard permissions (* or *:*), they can perform any action
            if "*" in perms or "*:*" in perms:
                return fn(*args, **kwargs)

            # If required permission is not in the list of permissions
            if required not in perms:
                return jsonify({
                    "message": "You do not have permission to perform this action.",
                    "required": required
                }), 403

            return fn(*args, **kwargs)

        return _wrapped

    return _dec


# ---- Helper Functions for Scope Check ----

def _is_system_admin(ctx: AffiliationContext) -> bool:
    """
    Check if the user is a System Admin. This check is based on the `is_system_admin` flag
    or the role "System Admin". This is the ONLY way a user gets system-wide access.
    """
    if bool(getattr(ctx, "is_system_admin", False)):
        return True

    roles = getattr(ctx, "roles", None) or []
    return any((str(r) or "").lower() == "system admin" for r in roles)


def ensure_scope_by_ids(
        *,
        context: AffiliationContext,
        target_company_id: Optional[int],
        target_branch_id: Optional[int] = None
) -> None:
    """
    Ensures that the user has a valid scope to access the requested resource.
    This logic is now much stricter and clearer, inspired by the working example.

    - If the user is a system admin, allow all access.
    - If not a system admin:
        - They CANNOT perform operations where a company is not specified.
        - They MUST be affiliated with the target_company_id.
        - If a target_branch_id is given, they must have access to that branch
          (either directly or via a company-level affiliation).
    """
    # 1. System admins have universal scope and bypass all checks.
    if _is_system_admin(context):
        return

    # 2. If not a system admin, any operation without a company scope is forbidden.
    if target_company_id is None:
        raise Forbidden("Out of scope. This action requires system-level privileges.")

    user_affiliations = list(getattr(context, "affiliations", []) or [])

    # 3. Check if the user is affiliated with the target company at all.
    # This is the primary company-level scope check.
    is_in_company = any(a.company_id == target_company_id for a in user_affiliations)
    if not is_in_company:
        raise Forbidden("Out of scope. You do not have access to this company.")

    # 4. If a specific branch is targeted, perform a stricter branch-level check.
    if target_branch_id is not None:
        # The user has scope if they are affiliated with the target company AND either:
        #   a) Their affiliation is for that specific branch (a.branch_id == target_branch_id)
        #   b) Their affiliation is at the company level (a.branch_id is None), granting access to all sub-branches.
        has_branch_scope = any(
            a.company_id == target_company_id and (a.branch_id is None or a.branch_id == target_branch_id)
            for a in user_affiliations
        )
        if not has_branch_scope:
            raise Forbidden("Out of scope. You do not have access to this specific branch.")

    # 5. If all checks pass, the user is confirmed to be in scope.
    return





def ensure_branch_scope(
    *,
    context: AffiliationContext,
    branch_id: int,
    get_branch_company_id: Callable[[int], Optional[int]],
    b_company_id_hint: Optional[int] = None,
) -> int:
    """
    Enforce scope to (company_id, branch_id) for a branch-scoped operation.

    - Resolves the branch's company_id via `get_branch_company_id`.
      If you already know it, pass `b_company_id_hint` to skip the DB lookup.
    - Calls your existing `ensure_scope_by_ids`, which includes the System Admin bypass.
    - Returns the resolved company_id.
    """
    b_company_id = b_company_id_hint
    if b_company_id is None:
        b_company_id = get_branch_company_id(branch_id)
    if b_company_id is None:
        raise NotFound("Branch not found.")
    ensure_scope_by_ids(context=context, target_company_id=b_company_id, target_branch_id=branch_id)
    return b_company_id


def resolve_company_branch_and_scope(
    *,
    context: AffiliationContext,
    payload_company_id: Optional[int],
    branch_id: Optional[int],
    get_branch_company_id: Callable[[int], Optional[int]],
    require_branch: bool = True,
) -> Tuple[int, Optional[int]]:
    """
    Canonicalize (company_id, branch_id) and enforce scope with zero duplication.

    Behavior:
      • If `require_branch` and no branch_id → 400 BadRequest.
      • If branch_id is provided:
          - Resolve its real company_id via `get_branch_company_id`.
          - If `payload_company_id` is present and mismatches → 403 Forbidden
            ("Out of scope. Branch does not belong to the target company.")
          - Enforce scope via `ensure_scope_by_ids`.
          - Return (company_id, branch_id).
      • If branch_id is NOT provided:
          - This is a company-level path (e.g., company roots).
          - Use payload_company_id or context.company_id and enforce company-level scope.
          - Return (company_id, None).
    """
    if require_branch and not branch_id:
        raise BadRequest("Branch is required.")

    if branch_id:
        b_company_id = ensure_branch_scope(
            context=context,
            branch_id=branch_id,
            get_branch_company_id=get_branch_company_id,
        )
        if payload_company_id is not None and payload_company_id != b_company_id:
            # Structurally invalid: cross-company branch supplied.
            raise Forbidden("Out of scope. Branch does not belong to the target company.")
        return b_company_id, branch_id

    # Company-level (no branch)
    company_id = payload_company_id or getattr(context, "company_id", None)
    ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)
    return company_id, None