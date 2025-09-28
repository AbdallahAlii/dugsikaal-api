# # app/navigation_workspace/services/visibility_services.py

from __future__ import annotations
from typing import Dict, List, Optional, Set

from app.navigation_workspace.models.nav_links import WorkspaceLink
from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import NavTreeOut, NavWorkspaceOut, NavLinkOut, NavSectionOut
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

def _pick_company_decision(rows, *, workspace_id=None, link_id=None) -> Optional[bool]:
    """user > branch > company precedence"""
    spec_user = None
    spec_branch = None
    spec_company = None
    for r in rows:
        if workspace_id and r.workspace_id != workspace_id:
            continue
        if link_id and r.link_id != link_id:
            continue
        if r.user_id is not None:
            spec_user = r
        elif r.branch_id is not None:
            spec_branch = r
        else:
            spec_company = r
    if spec_user is not None:
        return bool(spec_user.is_enabled)
    if spec_branch is not None:
        return bool(spec_branch.is_enabled)
    if spec_company is not None:
        return bool(spec_company.is_enabled)
    return None

def _pick_system_decision(rows, *, workspace_id=None, link_id=None) -> Optional[bool]:
    for r in rows:
        if workspace_id and r.workspace_id == workspace_id:
            return bool(r.is_enabled)
        if link_id and r.link_id == link_id:
            return bool(r.is_enabled)
    return None

def _final_visibility(*, sys_val: Optional[bool], cmp_val: Optional[bool]) -> bool:
    # Company overrides System; default visible if nothing set.
    if cmp_val is not None:
        return bool(cmp_val)
    if sys_val is not None:
        return bool(sys_val)
    return True

def _link_is_allowed(link: WorkspaceLink, *, perms: Set[str],
                     dt_names: Dict[int, str], act_names: Dict[int, str]) -> bool:
    # Wildcard RBAC still applies inside a workspace *after* admin_only gating.
    if "*" in perms or "*:*" in perms:
        return True
    if link.required_permission_str:
        return _canon_perm(link.required_permission_str) in perms
    if link.doctype_id and link.required_action_id:
        dt = (dt_names.get(link.doctype_id, "") or "").strip()
        act = (act_names.get(link.required_action_id, "") or "").strip()
        if not dt or not act:
            return False
        return _canon_perm(f"{dt}:{act}") in perms
    # public link (no gate)
    return True

# Optional: pin certain routes to a preferred workspace slug (avoid duplicates moving around)
PREFERRED_PATH_HOME: Dict[str, str] = {
    # "/masters/party/list": "selling",
}

class NavService:
    """Build final nav = (System rules ⊕ Company rules) ∧ RBAC ∧ AdminOnly gate, with global link dedupe."""

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

        # ----- load data -----
        workspaces = self.repo.load_workspaces_tree()
        sys_vis    = self.repo.load_system_visibility(company_id)
        cmp_vis    = self.repo.load_company_visibility(company_id, branch_id, context.user_id)

        # ----- resolve permissions once -----
        dt_ids: Set[int] = set()
        act_ids: Set[int] = set()
        for ws in workspaces:
            for l in ws.root_links:
                if l.doctype_id: dt_ids.add(l.doctype_id)
                if l.required_action_id: act_ids.add(l.required_action_id)
            for sc in ws.sections:
                for l in sc.links:
                    if l.doctype_id: dt_ids.add(l.doctype_id)
                    if l.required_action_id: act_ids.add(l.required_action_id)

        dt_names = self.repo.map_doctype_names(dt_ids)
        act_names = self.repo.map_action_names(act_ids)
        perms = {_canon_perm(p) for p in (context.permissions or set())}
        is_sys_admin = _is_system_admin(context)

        # 🔹 global dedupe set — once a path is added anywhere, skip elsewhere
        used_paths: Set[str] = set()

        out_workspaces: List[NavWorkspaceOut] = []

        for ws in workspaces:
            ws_admin_only = bool(getattr(ws, "admin_only", False))

            # ---- HARD admin_only gate (mutually exclusive) ----
            if is_sys_admin:
                # System Admin sees ONLY admin consoles
                if not ws_admin_only:
                    continue
            else:
                # Everyone else sees ONLY non-admin consoles
                if ws_admin_only:
                    continue

            # ---- Apply visibility toggles (System ⊕ Company) ----
            sys_ws = _pick_system_decision(sys_vis, workspace_id=ws.id)
            cmp_ws = _pick_company_decision(cmp_vis, workspace_id=ws.id)
            if not _final_visibility(sys_val=sys_ws, cmp_val=cmp_ws):
                continue

            root_links: List[NavLinkOut] = []
            sections: List[NavSectionOut] = []

            # root links
            for lk in ws.root_links:
                sys_l = _pick_system_decision(sys_vis, link_id=lk.id)
                cmp_l = _pick_company_decision(cmp_vis, link_id=lk.id)
                if not _final_visibility(sys_val=sys_l, cmp_val=cmp_l):
                    continue
                if not _link_is_allowed(lk, perms=perms, dt_names=dt_names, act_names=act_names):
                    continue

                pref = PREFERRED_PATH_HOME.get(lk.route_path)
                if pref and pref != ws.slug:
                    continue

                if lk.route_path in used_paths:
                    continue
                used_paths.add(lk.route_path)

                root_links.append(NavLinkOut(label=lk.label, path=lk.route_path, icon=lk.icon))

            # sections
            for sc in ws.sections:
                sec_links: List[NavLinkOut] = []
                for lk in sc.links:
                    sys_l = _pick_system_decision(sys_vis, link_id=lk.id)
                    cmp_l = _pick_company_decision(cmp_vis, link_id=lk.id)
                    if not _final_visibility(sys_val=sys_l, cmp_val=cmp_l):
                        continue
                    if not _link_is_allowed(lk, perms=perms, dt_names=dt_names, act_names=act_names):
                        continue

                    pref = PREFERRED_PATH_HOME.get(lk.route_path)
                    if pref and pref != ws.slug:
                        continue

                    if lk.route_path in used_paths:
                        continue
                    used_paths.add(lk.route_path)

                    sec_links.append(NavLinkOut(label=lk.label, path=lk.route_path, icon=lk.icon))
                if sec_links:
                    sections.append(NavSectionOut(label=sc.label, links=sec_links))

            if not root_links and not sections:
                # workspace has nothing left after visibility/RBAC/dedupe → hide it
                continue

            out_workspaces.append(
                NavWorkspaceOut(
                    title=ws.title, slug=ws.slug, icon=ws.icon, description=ws.description,
                    links=root_links, sections=sections
                )
            )

        return NavTreeOut(workspaces=out_workspaces)
