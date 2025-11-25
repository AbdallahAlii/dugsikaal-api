# seed_data/navigation_workspace/seeder.py
from __future__ import annotations

import logging
import re
from typing import Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.navigation_workspace.models.nav_links import (
    Workspace,
    WorkspaceSection,
    WorkspacePageLink,
    Page,
    PageKindEnum,
)
from app.navigation_workspace.models.subscription import (
    ModulePackage,
    PackageWorkspace,
    ModulePackage as ModulePackage_,
    PackageWorkspace as PackageWorkspace_,
)
from app.application_rbac.rbac_models import DocType as RbacDocType, Action as RbacAction

from .data import WORKSPACES
from ..subscription.packages import MODULE_PACKAGES

logger = logging.getLogger(__name__)

# ---- helpers ----------------------------------------------------------------


def _get_or_create(session: Session, model, *, defaults: Optional[dict] = None, **filters):
    obj = session.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False
    obj = model(**{**filters, **(defaults or {})})
    session.add(obj)
    try:
        session.flush([obj])
        return obj, True
    except IntegrityError:
        session.rollback()
        obj2 = session.scalar(select(model).filter_by(**filters))
        if obj2:
            return obj2, False
        raise


_slug_re = re.compile(r"[^a-z0-9\\-]+", re.IGNORECASE)


def _slugify_from_path(path: str) -> str:
    """
    Make a stable page slug from a route path.
    e.g. '/stock/item/list' -> 'stock-item-list'
         '/host-admin/platform-settings' -> 'host-admin-platform-settings'
    """
    if not path:
        return "page"
    parts = [p for p in path.strip("/").split("/") if p]
    slug = "-".join(parts[1:]) if parts and parts[0] == "app" else "-".join(parts)
    slug = slug.lower()
    slug = _slug_re.sub("-", slug).strip("-")
    return slug or "page"


def _infer_page_kind(path: str) -> PageKindEnum:
    # Reports (if you ever move to /app/report/... pattern)
    if path.startswith("/app/query-report/") or path.startswith("/app/report/"):
        return PageKindEnum.DASHBOARD
    # Custom page
    if path.startswith("/app/page/"):
        return PageKindEnum.PAGE
    # Platform/host admin settings
    if path.startswith("/platform-admin/") or path.startswith("/host-admin/"):
        return PageKindEnum.SETTINGS
    # Default: normal module page
    return PageKindEnum.PAGE


def _parse_perm(perm: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    'Item:READ' -> ('Item', 'READ')
    """
    if not perm or ":" not in perm:
        return None, None
    dt, act = perm.split(":", 1)
    return dt.strip() or None, (act.strip().upper() or None)


def _lookup_doctype_id(session: Session, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    return session.execute(
        select(RbacDocType.id).where(RbacDocType.name.ilike(name))
    ).scalar()


def _lookup_action_id(session: Session, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    return session.execute(
        select(RbacAction.id).where(RbacAction.name == name.upper())
    ).scalar()


# ---- upsert primitives ------------------------------------------------------


def _upsert_workspace(session: Session, spec: dict) -> Workspace:
    ws, _ = _get_or_create(
        session,
        Workspace,
        slug=spec["slug"],
        defaults={
            "title": spec["title"],
            "icon": spec.get("icon"),
            "description": spec.get("description"),
            "order_index": spec.get("order_index", 100),
            "is_system_only": bool(spec.get("admin_only", False)),
            "is_enabled": True,
        },
    )
    # keep in sync
    ws.title = spec["title"]
    ws.icon = spec.get("icon")
    ws.description = spec.get("description")
    ws.order_index = spec.get("order_index", ws.order_index or 100)
    ws.is_system_only = bool(spec.get("admin_only", False))
    ws.is_enabled = True
    return ws


def _upsert_section(session: Session, ws_id: int, title: str, order_index: int) -> WorkspaceSection:
    sec, _ = _get_or_create(
        session,
        WorkspaceSection,
        workspace_id=ws_id,
        title=title,
        defaults={"order_index": order_index},
    )
    sec.order_index = order_index
    return sec


def _upsert_page(
    session: Session,
    *,
    ws_id: int,
    label: str,
    path: str,
    icon: Optional[str],
    doctype_name: Optional[str],
    action_name: Optional[str],
) -> Page:
    # Page is unique by route_path; slug is derived from path
    slug = _slugify_from_path(path)
    kind = _infer_page_kind(path)

    doctype_id = _lookup_doctype_id(session, doctype_name)
    action_id = _lookup_action_id(session, action_name)

    page, _ = _get_or_create(
        session,
        Page,
        route_path=path,
        defaults={
            "title": label,
            "slug": slug,
            "kind": kind,
            "workspace_id": ws_id,
            "icon": icon,
            "is_enabled": True,
            "doctype_id": doctype_id,
            "default_action_id": action_id,
        },
    )
    # sync edits
    page.title = label
    page.slug = slug
    page.kind = kind
    page.workspace_id = ws_id
    page.icon = icon
    page.is_enabled = True
    # keep RBAC binding if resolvable
    page.doctype_id = doctype_id or page.doctype_id
    page.default_action_id = action_id or page.default_action_id
    return page


def _upsert_page_link(
    session: Session,
    section_id: int,
    page_id: int,
    label: Optional[str],
    order_index: int,
) -> WorkspacePageLink:
    link, _ = _get_or_create(
        session,
        WorkspacePageLink,
        section_id=section_id,
        page_id=page_id,
        target_route=None,
        defaults={"label": label, "order_index": order_index},
    )
    link.label = label
    link.order_index = order_index
    return link


def _prune_sections_not_in_spec(session: Session, ws_id: int, keep_titles: Set[str]) -> None:
    existing = session.scalars(
        select(WorkspaceSection).where(WorkspaceSection.workspace_id == ws_id)
    ).all()
    for sec in existing:
        if sec.title not in keep_titles:
            session.delete(sec)  # cascade wipes links


def _prune_links_not_in_spec(session: Session, section_id: int, keep_page_ids: Set[int]) -> None:
    existing = session.scalars(
        select(WorkspacePageLink).where(WorkspacePageLink.section_id == section_id)
    ).all()
    for ln in existing:
        if (ln.page_id or -1) not in keep_page_ids:
            session.delete(ln)


# ---- main seeders -----------------------------------------------------------


def seed_navigation_workspaces(session: Session) -> None:
    """
    Idempotently seeds:
      • Workspaces
      • Sections
      • Pages
      • WorkspacePageLinks

    Also prunes any sections/links that are no longer present in the WORKSPACES spec.
    """
    logger.info("🌱 Seeding Navigation Workspaces (hybrid)...")

    for ws_spec in WORKSPACES:
        ws = _upsert_workspace(session, ws_spec)

        # 1) Root links -> materialize into a synthetic "__ROOT__" section
        root_links = ws_spec.get("root_links") or []
        have_root = bool(root_links)
        root_sec = None
        if have_root:
            # Low order_index so normal links appear before other sections
            root_sec = _upsert_section(session, ws.id, "__ROOT__", 0)
            keep_root_page_ids: Set[int] = set()
            for idx, L in enumerate(root_links):
                if not L or "path" not in L or "label" not in L:
                    continue
                dt, act = _parse_perm(L.get("perm"))
                page = _upsert_page(
                    session,
                    ws_id=ws.id,
                    label=L["label"],
                    path=L["path"],
                    icon=L.get("icon"),
                    doctype_name=dt,
                    action_name=act,
                )
                keep_root_page_ids.add(page.id)
                _upsert_page_link(
                    session,
                    root_sec.id,
                    page.id,
                    L.get("label"),
                    L.get("order_index", (idx + 1) * 10),
                )
            _prune_links_not_in_spec(session, root_sec.id, keep_root_page_ids)

        # 2) Sections + links
        desired_section_titles: Set[str] = set(["__ROOT__"] if have_root else [])
        for sidx, S in enumerate(ws_spec.get("sections") or []):
            if not S or not S.get("label"):
                continue
            sec = _upsert_section(
                session,
                ws.id,
                S["label"],
                S.get("order_index", (sidx + 1) * 10),
            )
            desired_section_titles.add(S["label"])

            keep_page_ids: Set[int] = set()
            for lidx, L in enumerate(S.get("links") or []):
                if not L or "path" not in L or "label" not in L:
                    continue
                dt, act = _parse_perm(L.get("perm"))
                page = _upsert_page(
                    session,
                    ws_id=ws.id,
                    label=L["label"],
                    path=L["path"],
                    icon=L.get("icon"),
                    doctype_name=dt,
                    action_name=act,
                )
                keep_page_ids.add(page.id)
                _upsert_page_link(
                    session,
                    sec.id,
                    page.id,
                    L.get("label"),
                    L.get("order_index", (lidx + 1) * 10),
                )
            _prune_links_not_in_spec(session, sec.id, keep_page_ids)

        _prune_sections_not_in_spec(session, ws.id, desired_section_titles)

    logger.info("✅ Navigation (Workspaces/Pages/Links) seeded.")


def seed_module_packages(session: Session) -> None:
    """
    Seeds ModulePackage & PackageWorkspace using MODULE_PACKAGES. Idempotent.
    """
    logger.info("🌱 Seeding Module Packages...")
    for pkg in MODULE_PACKAGES:
        mp, _ = _get_or_create(
            session,
            ModulePackage_,
            slug=pkg["slug"],
            defaults={
                "name": pkg["name"],
                "description": pkg.get("description"),
                "is_enabled": bool(pkg.get("is_enabled", True)),
            },
        )
        mp.name = pkg["name"]
        mp.description = pkg.get("description")
        mp.is_enabled = bool(pkg.get("is_enabled", True))

        # map workspaces
        ws_rows = session.execute(
            select(Workspace.slug, Workspace.id).where(Workspace.slug.in_(pkg["workspaces"]))
        ).all()
        slug_to_id = {s: i for (s, i) in ws_rows}

        existing = session.execute(
            select(PackageWorkspace_.workspace_id).where(PackageWorkspace_.package_id == mp.id)
        ).scalars().all()
        have = set(existing)
        want = set(slug_to_id.values())

        # add missing
        for ws_id in want - have:
            session.add(PackageWorkspace_(package_id=mp.id, workspace_id=ws_id))

        # remove extras
        for ws_id in have - want:
            session.query(PackageWorkspace_).filter_by(
                package_id=mp.id, workspace_id=ws_id
            ).delete()

    logger.info("✅ Module Packages seeded.")
