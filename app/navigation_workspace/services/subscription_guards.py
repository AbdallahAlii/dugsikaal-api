# app/navigation_workspace/subscription_guards.py
from __future__ import annotations

from typing import Optional, Tuple

from flask import g

from app.navigation_workspace.repo import NavRepository
from app.security.rbac_effective import AffiliationContext
from app.common.api_response import api_error
from app.navigation_workspace.services.visibility_services import (
    _pick_system_decision,
    _pick_company_decision,
    _final_visibility,
)


def check_workspace_subscription(
    context: AffiliationContext,
    *,
    workspace_slug: str,
) -> Tuple[bool, Optional[str]]:
    """
    Central check:
      - host System Admin bypass
      - company_id must exist
      - workspace must exist & be enabled
      - company must have a package that includes this workspace
      - workspace must be visible (SystemWorkspaceVisibility / CompanyWorkspaceVisibility)

    Returns (ok, message). If ok is False, message is a user-facing ERP-style error string.
    """
    # Host-level system admin bypass (platform owner)
    if getattr(context, "is_system_admin", False):
        return True, None

    company_id = getattr(context, "company_id", None)
    branch_id = getattr(context, "branch_id", None)

    if not company_id:
        return False, "Company context is required to access modules."

    repo = NavRepository()

    ws = repo.find_workspace_by_slug(workspace_slug)
    if ws is None or not ws.is_enabled:
        # Don't leak internal info; just say module not available
        return False, "This module is not available. Please contact your administrator."

    # Check package licensing
    licensed_ws_ids = repo.licensed_workspace_ids_for_company(company_id)
    if not licensed_ws_ids:
        # No packages at all for this company
        return False, "You don’t have access to any modules. Please contact your administrator."

    if ws.id not in licensed_ws_ids:
        label = ws.title or ws.slug
        return False, f"Your subscription does not include the {label} module. Please contact your administrator."

    # Check visibility overrides (same logic as NavService)
    sys_vis = repo.load_system_visibility(company_id)
    cmp_vis = repo.load_company_visibility(company_id, branch_id, context.user_id)

    sys_ws = _pick_system_decision(sys_vis, workspace_id=ws.id)
    cmp_ws = _pick_company_decision(
        cmp_vis,
        workspace_id=ws.id,
        branch_id=branch_id,
        user_id=context.user_id,
    )

    if not _final_visibility(sys_val=sys_ws, cmp_val=cmp_ws):
        label = ws.title or ws.slug
        return False, f"The {label} module has been disabled for your company. Please contact your administrator."

    return True, None
