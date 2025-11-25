from __future__ import annotations
from typing import Dict, List, Optional, Set

from app.navigation_workspace.models.nav_links import (
    Workspace,
    WorkspaceSection,
    WorkspacePageLink,
    Page,
)
from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import (
    NavTreeOut,
    NavWorkspaceOut,
    NavLinkOut,
    NavSectionOut,
)
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids


def _canon_perm(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if ":" not in s:
        return s.upper()
    a, b = s.split(":", 1)
    return f"{a.strip().upper()}:{b.strip().upper()}"


def _is_system_admin(context: AffiliationContext) -> bool:
    """
    Strict detector for host-level System Admin.

    IMPORTANT:
    Do NOT infer this from wildcard perms ('*' or '*:*') because Super Admin
    also has wildcard but must *not* see admin-only consoles. We only allow:
      • explicit flag context.is_system_admin, OR
      • an assigned role literally named 'System Admin' (case-insensitive).
    """
    if getattr(context, "is_system_admin", False):
        return True
    roles = {str(r).strip().lower() for r in getattr(context, "roles", []) if r}
    return "system admin" in roles


def _pick_system_decision(rows, *, workspace_id: int) -> Optional[bool]:
    """
    SystemWorkspaceVisibility: exact match on workspace_id.
    """
    for r in rows:
        if r.workspace_id == workspace_id:
            return bool(r.is_enabled)
    return None


def _pick_company_decision(
    rows,
    *,
    workspace_id: int,
    branch_id: Optional[int],
    user_id: Optional[int],
) -> Optional[bool]:
    """
    CompanyWorkspaceVisibility precedence:
      user > branch > company
    """
    spec_user = None
    spec_branch = None
    spec_company = None

    for r in rows:
        if r.workspace_id != workspace_id:
            continue

        # User-specific
        if r.user_id is not None and user_id is not None and r.user_id == user_id:
            spec_user = r
        # Branch-specific (but NOT user-specific)
        elif (
            r.branch_id is not None
            and branch_id is not None
            and r.branch_id == branch_id
            and r.user_id is None
        ):
            spec_branch = r
        # Company-wide (no branch/user)
        elif r.branch_id is None and r.user_id is None:
            spec_company = r

    if spec_user is not None:
        return bool(spec_user.is_enabled)
    if spec_branch is not None:
        return bool(spec_branch.is_enabled)
    if spec_company is not None:
        return bool(spec_company.is_enabled)
    return None


def _final_visibility(*, sys_val: Optional[bool], cmp_val: Optional[bool]) -> bool:
    """
    Company overrides System; default visible if nothing set.
    """
    if cmp_val is not None:
        return bool(cmp_val)
    if sys_val is not None:
        return bool(sys_val)
    return True


def _link_is_allowed(
    link: WorkspacePageLink,
    *,
    perms: Set[str],
    dt_names: Dict[int, str],
    act_names: Dict[int, str],
) -> bool:
    """
    RBAC gate for a single link.

    Order:
      1) wildcard => allowed
      2) explicit required_perm in link.extra or page.extra => check directly
      3) if Page.doctype_id + default_action_id => build "DocType:ACTION" string
      4) otherwise => public link (no gate)
    """
    if "*" in perms or "*:*" in perms:
        return True

    # 1) explicit string in extra
    required_perm = None
    extra = getattr(link, "extra", None)
    if isinstance(extra, dict):
        required_perm = extra.get("required_perm") or extra.get("required_permission")

    if not required_perm and link.page is not None:
        p_extra = getattr(link.page, "extra", None)
        if isinstance(p_extra, dict):
            required_perm = p_extra.get("required_perm") or p_extra.get("required_permission")

    if required_perm:
        return _canon_perm(required_perm) in perms

    # 2) DocType + Action mapping
    if link.page is not None and link.page.doctype_id and link.page.default_action_id:
        dt = (dt_names.get(link.page.doctype_id, "") or "").strip()
        act = (act_names.get(link.page.default_action_id, "") or "").strip()
        if not dt or not act:
            return False
        needed = _canon_perm(f"{dt}:{act}")
        return needed in perms

    # 3) no gate => public
    return True


# Optional: pin certain routes to a preferred workspace (avoid duplicates in a *controlled* way).
PREFERRED_PATH_HOME: Dict[str, str] = {
    # e.g. "/accounts/report/gross-profit": "accounting",
}


class NavService:
    """
    Build final nav:
        (Workspaces licensed by packages)
      ∧ (System ⊕ Company visibility)
      ∧ RBAC
      ∧ System-only (admin) vs normal consoles

    NOTE:
      We **do not** globally dedupe routes anymore. A path can appear
      under multiple workspaces (Frappe-style). If you want to force
      a path to belong to a single module, use PREFERRED_PATH_HOME.
    """

    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()

    def build_nav_tree(
        self,
        *,
        context: AffiliationContext,
        company_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> NavTreeOut:
        # ----- scope (primary affiliation if not passed) -----
        company_id = company_id if company_id is not None else getattr(context, "company_id", None)
        branch_id = branch_id if branch_id is not None else getattr(context, "branch_id", None)
        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        # ----- fetch system & company visibility + package licenses -----
        workspaces = self.repo.load_workspaces_tree()
        sys_vis = self.repo.load_system_visibility(company_id)
        cmp_vis = self.repo.load_company_visibility(company_id, branch_id, context.user_id)
        licensed_ws_ids = self.repo.licensed_workspace_ids_for_company(company_id)

        # ----- RBAC lookup maps -----
        dt_ids: Set[int] = set()
        act_ids: Set[int] = set()
        for ws in workspaces:
            for sec in ws.sections:
                for lk in sec.page_links:
                    if lk.page is not None:
                        if lk.page.doctype_id:
                            dt_ids.add(lk.page.doctype_id)
                        if lk.page.default_action_id:
                            act_ids.add(lk.page.default_action_id)

        dt_names = self.repo.map_doctype_names(dt_ids)
        act_names = self.repo.map_action_names(act_ids)

        perms = {_canon_perm(p) for p in (context.permissions or set())}
        is_sys_admin = _is_system_admin(context)

        out_workspaces: List[NavWorkspaceOut] = []

        for ws in workspaces:
            # ----- basic workspace toggles -----
            if not ws.is_enabled:
                continue

            # Separate system-only consoles
            if is_sys_admin:
                # System admin sees ONLY system-only workspaces
                if not ws.is_system_only:
                    continue
            else:
                # Normal users never see system-only consoles
                if ws.is_system_only:
                    continue

                # Package licensing: strict SaaS-style.
                # If company has no packages => no modules.
                if not licensed_ws_ids or ws.id not in licensed_ws_ids:
                    continue

            # System + company visibility
            sys_ws = _pick_system_decision(sys_vis, workspace_id=ws.id)
            cmp_ws = _pick_company_decision(
                cmp_vis,
                workspace_id=ws.id,
                branch_id=branch_id,
                user_id=context.user_id,
            )
            if not _final_visibility(sys_val=sys_ws, cmp_val=cmp_ws):
                continue

            root_links: List[NavLinkOut] = []  # with this model, often empty
            sections: List[NavSectionOut] = []

            # ----- sections + links -----
            for sc in ws.sections:
                sec_links: List[NavLinkOut] = []
                for lk in sc.page_links:
                    # RBAC gate
                    if not _link_is_allowed(lk, perms=perms, dt_names=dt_names, act_names=act_names):
                        continue

                    # Determine route path
                    path: Optional[str] = None
                    icon: Optional[str] = None

                    if lk.page is not None:
                        path = lk.page.route_path
                        icon = lk.page.icon
                    else:
                        path = lk.target_route
                        # optionally, use icon from extra for pure target_route links
                        extra = getattr(lk, "extra", None)
                        if isinstance(extra, dict):
                            icon = extra.get("icon")

                    if not path:
                        continue

                    # Preferred workspace mapping to avoid duplicates *only when explicitly configured*
                    pref = PREFERRED_PATH_HOME.get(path)
                    if pref and pref != ws.slug:
                        continue

                    label = lk.label
                    if not label:
                        if lk.page is not None:
                            label = lk.page.title
                        else:
                            label = path

                    sec_links.append(NavLinkOut(label=label, path=path, icon=icon))

                if sec_links:
                    sections.append(NavSectionOut(label=sc.title, links=sec_links))

            if not root_links and not sections:
                # Nothing left => hide workspace
                continue

            out_workspaces.append(
                NavWorkspaceOut(
                    title=ws.title,
                    slug=ws.slug,
                    icon=ws.icon,
                    description=ws.description,
                    links=root_links,
                    sections=sections,
                )
            )

        return NavTreeOut(workspaces=out_workspaces)
