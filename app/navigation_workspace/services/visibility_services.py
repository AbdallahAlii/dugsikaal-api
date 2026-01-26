#
# from __future__ import annotations
#
# import logging
# from typing import Dict, List, Optional, Set
#
# from app.navigation_workspace.models.nav_links import (
#     Workspace,
#     WorkspaceSection,
#     WorkspacePageLink,
#     Page,
# )
# from app.navigation_workspace.repo import NavRepository
# from app.navigation_workspace.schemas import (
#     NavTreeOut,
#     NavWorkspaceOut,
#     NavLinkOut,
#     NavSectionOut,
# )
# from app.security.rbac_effective import AffiliationContext
# from app.security.rbac_guards import ensure_scope_by_ids
#
# logger = logging.getLogger(__name__)
#
# # ---------------------------------------------------------------------
# # Helpers
# # ---------------------------------------------------------------------
#
# def _canon_perm(s: str) -> str:
#     """
#     Canonical permission string used ONLY for matching.
#     """
#     s = (s or "").strip()
#     if not s:
#         return s
#     if ":" not in s:
#         return s
#     dt, act = s.split(":", 1)
#     dt = " ".join(dt.split()).casefold()
#     act = " ".join(act.split()).upper()
#     return f"{dt}:{act}"
#
#
# def _is_system_admin(context: AffiliationContext) -> bool:
#     """
#     Detect ONLY true system admin.
#     """
#     if getattr(context, "is_system_admin", False):
#         return True
#     roles = {r.lower() for r in (context.roles or [])}
#     return "system admin" in roles
#
#
# def _pick_system_decision(rows, *, workspace_id: int) -> Optional[bool]:
#     for r in rows:
#         if r.workspace_id == workspace_id:
#             return bool(r.is_enabled)
#     return None
#
#
# def _pick_company_decision(
#     rows,
#     *,
#     workspace_id: int,
#     branch_id: Optional[int],
#     user_id: Optional[int],
# ) -> Optional[bool]:
#     user_row = None
#     branch_row = None
#     company_row = None
#
#     for r in rows:
#         if r.workspace_id != workspace_id:
#             continue
#         if r.user_id is not None and r.user_id == user_id:
#             user_row = r
#         elif r.branch_id is not None and r.branch_id == branch_id and r.user_id is None:
#             branch_row = r
#         elif r.branch_id is None and r.user_id is None:
#             company_row = r
#
#     if user_row:
#         return bool(user_row.is_enabled)
#     if branch_row:
#         return bool(branch_row.is_enabled)
#     if company_row:
#         return bool(company_row.is_enabled)
#     return None
#
#
# def _final_visibility(*, sys_val: Optional[bool], cmp_val: Optional[bool]) -> bool:
#     if cmp_val is not None:
#         return bool(cmp_val)
#     if sys_val is not None:
#         return bool(sys_val)
#     return True
#
#
# def _link_is_allowed(
#     link: WorkspacePageLink,
#     *,
#     perms: Set[str],
#     dt_names: Dict[int, str],
#     act_names: Dict[int, str],
# ) -> bool:
#     """
#     ERP-style RBAC check with FULL DEBUG.
#     """
#
#     # Wildcard
#     if "*" in perms or "*:*" in perms:
#         logger.debug("ALLOW link %s (wildcard)", link.id)
#         return True
#
#     # 1️⃣ explicit perm on link.extra (STANDARD ROUTES)
#     extra = getattr(link, "extra", None)
#     if isinstance(extra, dict):
#         req = extra.get("perm") or extra.get("required_perm")
#         if req:
#             needed = _canon_perm(req)
#             allowed = needed in perms
#             logger.debug(
#                 "LINK %s explicit perm %s → %s",
#                 link.id, needed, "ALLOW" if allowed else "DENY"
#             )
#             return allowed
#
#     # 2️⃣ Page-based (custom pages)
#     if link.page:
#         page = link.page
#         if page.doctype_id and page.default_action_id:
#             dt = dt_names.get(page.doctype_id)
#             act = act_names.get(page.default_action_id)
#             if not dt or not act:
#                 logger.debug(
#                     "DENY link %s page=%s (doctype/action missing)",
#                     link.id, page.id
#                 )
#                 return False
#
#             needed = _canon_perm(f"{dt}:{act}")
#             allowed = needed in perms
#             logger.debug(
#                 "LINK %s page perm %s → %s",
#                 link.id, needed, "ALLOW" if allowed else "DENY"
#             )
#             return allowed
#
#     # 3️⃣ No gate = public
#     logger.debug("ALLOW link %s (public)", link.id)
#     return True
#
#
# # ---------------------------------------------------------------------
# # NEW helper (SAFE ADDITION)
# # ---------------------------------------------------------------------
#
# def _workspace_role_allowed(
#     *,
#     workspace_id: int,
#     user_roles: Set[str],
#     workspace_roles_map: Dict[int, Set[str]],
# ) -> bool:
#     """
#     ERPNext-style Has Role check.
#     If workspace has role restrictions, user must match at least one.
#     """
#     allowed = workspace_roles_map.get(workspace_id)
#     if not allowed:
#         return True
#     return bool(user_roles.intersection(allowed))
#
#
# # ---------------------------------------------------------------------
# # Nav Service
# # ---------------------------------------------------------------------
#
# class NavService:
#     """
#     Enterprise-grade navigation builder (ERPNext / Frappe style).
#     """
#
#     def __init__(self, repo: Optional[NavRepository] = None):
#         self.repo = repo or NavRepository()
#
#     def build_nav_tree(
#         self,
#         *,
#         context: AffiliationContext,
#         company_id: Optional[int] = None,
#         branch_id: Optional[int] = None,
#     ) -> NavTreeOut:
#
#         company_id = company_id if company_id is not None else context.company_id
#         branch_id = branch_id if branch_id is not None else context.branch_id
#         ensure_scope_by_ids(
#             context=context,
#             target_company_id=company_id,
#             target_branch_id=branch_id,
#         )
#
#         logger.debug(
#             "NAV BUILD user=%s company=%s branch=%s roles=%s perms=%s",
#             context.user_id, company_id, branch_id, context.roles, context.permissions
#         )
#
#         workspaces = self.repo.load_workspaces_tree()
#         sys_vis = self.repo.load_system_visibility(company_id)
#         cmp_vis = self.repo.load_company_visibility(company_id, branch_id, context.user_id)
#         licensed_ws_ids = self.repo.licensed_workspace_ids_for_company(company_id)
#
#         # ⭐ NEW: workspace ↔ role map
#         try:
#             workspace_roles_map = self.repo.workspace_roles_map()
#         except Exception:
#             logger.exception("Failed to load workspace role map")
#             workspace_roles_map = {}
#
#         user_roles = {r.lower() for r in (context.roles or [])}
#
#         # RBAC maps
#         dt_ids: Set[int] = set()
#         act_ids: Set[int] = set()
#         for ws in workspaces:
#             for sec in ws.sections:
#                 for lk in sec.page_links:
#                     if lk.page:
#                         if lk.page.doctype_id:
#                             dt_ids.add(lk.page.doctype_id)
#                         if lk.page.default_action_id:
#                             act_ids.add(lk.page.default_action_id)
#
#         dt_names = self.repo.map_doctype_names(dt_ids)
#         act_names = self.repo.map_action_names(act_ids)
#
#         perms = {_canon_perm(p) for p in (context.permissions or set())}
#         is_sys_admin = _is_system_admin(context)
#
#         out_workspaces: List[NavWorkspaceOut] = []
#
#         for ws in workspaces:
#             logger.debug("CHECK workspace %s (%s)", ws.slug, ws.id)
#
#             if not ws.is_enabled:
#                 logger.debug("SKIP %s disabled", ws.slug)
#                 continue
#
#             if is_sys_admin:
#                 if not ws.is_system_only:
#                     continue
#             else:
#                 if ws.is_system_only:
#                     continue
#                 if ws.id not in licensed_ws_ids:
#                     logger.debug("SKIP %s not licensed", ws.slug)
#                     continue
#
#             sys_ws = _pick_system_decision(sys_vis, workspace_id=ws.id)
#             cmp_ws = _pick_company_decision(
#                 cmp_vis,
#                 workspace_id=ws.id,
#                 branch_id=branch_id,
#                 user_id=context.user_id,
#             )
#
#             if not _final_visibility(sys_val=sys_ws, cmp_val=cmp_ws):
#                 logger.debug("SKIP %s visibility off", ws.slug)
#                 continue
#
#             # ⭐ NEW ROLE GATE (does NOT replace RBAC)
#             if not _workspace_role_allowed(
#                 workspace_id=ws.id,
#                 user_roles=user_roles,
#                 workspace_roles_map=workspace_roles_map,
#             ):
#                 logger.debug("SKIP %s (workspace role gate)", ws.slug)
#                 continue
#
#             sections: List[NavSectionOut] = []
#             workspace_home: Optional[str] = None
#
#             for sc in ws.sections:
#                 sec_links: List[NavLinkOut] = []
#
#                 for lk in sc.page_links:
#                     if not _link_is_allowed(
#                         lk,
#                         perms=perms,
#                         dt_names=dt_names,
#                         act_names=act_names,
#                     ):
#                         continue
#
#                     if lk.page:
#                         path = lk.page.route_path
#                         icon = lk.page.icon
#                     else:
#                         path = lk.target_route
#                         icon = None
#
#                     if not path:
#                         continue
#
#                     if workspace_home is None:
#                         workspace_home = path
#
#                     label = lk.label or (lk.page.title if lk.page else path)
#                     sec_links.append(NavLinkOut(label=label, path=path, icon=icon))
#
#                 if sec_links:
#                     sections.append(NavSectionOut(label=sc.title, links=sec_links))
#
#             if not sections:
#                 logger.debug("SKIP %s (no visible links)", ws.slug)
#                 continue
#
#             out_workspaces.append(
#                 NavWorkspaceOut(
#                     title=ws.title,
#                     slug=ws.slug,
#                     icon=ws.icon,
#                     description=ws.description,
#                     links=[],
#                     sections=sections,
#                     home_path=workspace_home,
#                 )
#             )
#
#             logger.debug("ADD workspace %s home=%s", ws.slug, workspace_home)
#
#         logger.debug("NAV BUILD DONE (%d workspaces)", len(out_workspaces))
#         return NavTreeOut(workspaces=out_workspaces)
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from app.navigation_workspace.models.nav_links import WorkspacePageLink
from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import (
    NavTreeOut,
    NavWorkspaceOut,
    NavLinkOut,
    NavSectionOut,
)
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

logger = logging.getLogger(__name__)


def _canon_perm(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if ":" not in s:
        return s
    dt, act = s.split(":", 1)
    dt = " ".join(dt.split()).casefold()
    act = " ".join(act.split()).upper()
    return f"{dt}:{act}"


def _canon_role(r: str) -> str:
    return " ".join((r or "").strip().split()).casefold()


def _is_system_admin(context: AffiliationContext) -> bool:
    if getattr(context, "is_system_admin", False):
        return True
    roles = {_canon_role(r) for r in (context.roles or [])}
    return "system admin" in roles


def _pick_system_decision(rows, *, workspace_id: int) -> Optional[bool]:
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
    user_row = None
    branch_row = None
    company_row = None

    for r in rows:
        if r.workspace_id != workspace_id:
            continue
        if r.user_id is not None and r.user_id == user_id:
            user_row = r
        elif r.branch_id is not None and r.branch_id == branch_id and r.user_id is None:
            branch_row = r
        elif r.branch_id is None and r.user_id is None:
            company_row = r

    if user_row:
        return bool(user_row.is_enabled)
    if branch_row:
        return bool(branch_row.is_enabled)
    if company_row:
        return bool(company_row.is_enabled)
    return None


def _final_visibility(*, sys_val: Optional[bool], cmp_val: Optional[bool]) -> bool:
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
    if "*" in perms or "*:*" in perms:
        return True

    extra = getattr(link, "extra", None)
    if isinstance(extra, dict):
        req = extra.get("perm") or extra.get("required_perm")
        if req:
            return _canon_perm(req) in perms

    if link.page:
        page = link.page
        if page.doctype_id and page.default_action_id:
            dt = dt_names.get(page.doctype_id)
            act = act_names.get(page.default_action_id)
            if not dt or not act:
                return False
            return _canon_perm(f"{dt}:{act}") in perms

    return True


def _workspace_role_allowed(
    *,
    workspace_id: int,
    user_roles: Set[str],
    workspace_roles_map: Dict[int, Set[str]],
) -> bool:
    allowed = workspace_roles_map.get(workspace_id)
    if not allowed:
        return True
    return bool(user_roles.intersection(allowed))


def _is_portal_workspace(ws) -> bool:
    """
    portal_only is stored in Workspace.extra (JSONB).
    Also keep a slug fallback so old DB rows still behave correctly.
    """
    extra = getattr(ws, "extra", None) or {}
    if isinstance(extra, dict) and bool(extra.get("portal_only")):
        return True
    return ws.slug in {"student-portal", "teacher-portal", "guardian-portal"}


class NavService:
    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()

    def build_nav_tree(
        self,
        *,
        context: AffiliationContext,
        company_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> NavTreeOut:

        company_id = company_id if company_id is not None else context.company_id
        branch_id = branch_id if branch_id is not None else context.branch_id
        ensure_scope_by_ids(
            context=context,
            target_company_id=company_id,
            target_branch_id=branch_id,
        )

        workspaces = self.repo.load_workspaces_tree()
        sys_vis = self.repo.load_system_visibility(company_id)
        cmp_vis = self.repo.load_company_visibility(company_id, branch_id, context.user_id)
        licensed_ws_ids = self.repo.licensed_workspace_ids_for_company(company_id)

        workspace_roles_map = self.repo.workspace_roles_map()
        user_roles = {_canon_role(r) for r in (context.roles or [])}

        # RBAC maps
        dt_ids: Set[int] = set()
        act_ids: Set[int] = set()
        for ws in workspaces:
            for sec in ws.sections:
                for lk in sec.page_links:
                    if lk.page:
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
            if not ws.is_enabled:
                continue

            # system-only gate
            if is_sys_admin:
                if not ws.is_system_only:
                    continue
            else:
                if ws.is_system_only:
                    continue
                if ws.id not in licensed_ws_ids:
                    continue

            # visibility toggles
            sys_ws = _pick_system_decision(sys_vis, workspace_id=ws.id)
            cmp_ws = _pick_company_decision(
                cmp_vis,
                workspace_id=ws.id,
                branch_id=branch_id,
                user_id=context.user_id,
            )
            if not _final_visibility(sys_val=sys_ws, cmp_val=cmp_ws):
                continue

            # role gate
            allowed_roles_for_ws = workspace_roles_map.get(ws.id, set())

            if _is_portal_workspace(ws):
                # ✅ FAIL-CLOSED portals:
                # must have explicit workspace_roles AND user must match
                if not allowed_roles_for_ws:
                    continue
                if not user_roles.intersection(allowed_roles_for_ws):
                    continue
            else:
                # normal ERPNext-style
                if not _workspace_role_allowed(
                    workspace_id=ws.id,
                    user_roles=user_roles,
                    workspace_roles_map=workspace_roles_map,
                ):
                    continue

            sections: List[NavSectionOut] = []
            workspace_home: Optional[str] = None

            for sc in ws.sections:
                sec_links: List[NavLinkOut] = []

                for lk in sc.page_links:
                    if not _link_is_allowed(
                        lk,
                        perms=perms,
                        dt_names=dt_names,
                        act_names=act_names,
                    ):
                        continue

                    if lk.page:
                        path = lk.page.route_path
                        icon = lk.page.icon
                    else:
                        path = lk.target_route
                        icon = None

                    if not path:
                        continue

                    if workspace_home is None:
                        workspace_home = path

                    label = lk.label or (lk.page.title if lk.page else path)
                    sec_links.append(NavLinkOut(label=label, path=path, icon=icon))

                if sec_links:
                    sections.append(NavSectionOut(label=sc.title, links=sec_links))

            if not sections:
                continue

            out_workspaces.append(
                NavWorkspaceOut(
                    title=ws.title,
                    slug=ws.slug,
                    icon=ws.icon,
                    description=ws.description,
                    links=[],
                    sections=sections,
                    home_path=workspace_home,
                )
            )

        return NavTreeOut(workspaces=out_workspaces)
