# # seed_data/navigation_workspace/seeder.py
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
    ModulePackage as ModulePackage_,
    PackageWorkspace as PackageWorkspace_,
)
from app.application_rbac.rbac_models import DocType as RbacDocType, Action as RbacAction

from .data import WORKSPACES
from ..subscription.packages import MODULE_PACKAGES

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------

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
    if not path:
        return "page"
    parts = [p for p in path.strip("/").split("/") if p]
    slug = "-".join(parts)
    slug = slug.lower()
    slug = _slug_re.sub("-", slug).strip("-")
    return slug or "page"


def _infer_page_kind(path: str) -> PageKindEnum:
    if path.startswith("/app/query-report/") or path.startswith("/app/report/"):
        return PageKindEnum.DASHBOARD
    if path.startswith("/app/page/"):
        return PageKindEnum.PAGE
    if path.startswith("/platform-admin/") or path.startswith("/host-admin/"):
        return PageKindEnum.SETTINGS
    return PageKindEnum.PAGE


def _parse_perm(perm: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not perm or ":" not in perm:
        return None, None
    dt, act = perm.split(":", 1)
    return dt.strip(), act.strip().upper()


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


# -----------------------------------------------------------------------------
# upsert primitives
# -----------------------------------------------------------------------------

# def _upsert_workspace(session: Session, spec: dict) -> Workspace:
#     ws, _ = _get_or_create(
#         session,
#         Workspace,
#         slug=spec["slug"],
#         defaults={
#             "title": spec["title"],
#             "icon": spec.get("icon"),
#             "description": spec.get("description"),
#             "order_index": spec.get("order_index", 100),
#             "is_system_only": bool(spec.get("admin_only", False)),
#             "is_enabled": True,
#         },
#     )
#     ws.title = spec["title"]
#     ws.icon = spec.get("icon")
#     ws.description = spec.get("description")
#     ws.order_index = spec.get("order_index", ws.order_index or 100)
#     ws.is_system_only = bool(spec.get("admin_only", False))
#     ws.is_enabled = True
#     return ws
def _upsert_workspace(session: Session, spec: dict) -> Workspace:
    # build/merge metadata into Workspace.extra
    meta = dict(spec.get("extra") or {})
    meta["portal_only"] = bool(spec.get("portal_only", False))

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
            "extra": meta,
        },
    )

    ws.title = spec["title"]
    ws.icon = spec.get("icon")
    ws.description = spec.get("description")
    ws.order_index = spec.get("order_index", ws.order_index or 100)
    ws.is_system_only = bool(spec.get("admin_only", False))
    ws.is_enabled = True

    # IMPORTANT: keep existing keys and just update portal_only
    current = dict(ws.extra or {})
    current.update(meta)
    ws.extra = current

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


# -----------------------------------------------------------------------------
# MAIN FIX: STANDARD ROUTES USE target_route + extra.required_perm
# -----------------------------------------------------------------------------

def _upsert_standard_link(
    session: Session,
    *,
    section_id: int,
    label: str,
    path: str,
    order_index: int,
    required_perm: Optional[str],
) -> WorkspacePageLink:
    extra = {}
    if required_perm:
        extra["required_perm"] = required_perm

    link, _ = _get_or_create(
        session,
        WorkspacePageLink,
        section_id=section_id,
        page_id=None,
        target_route=path,
        defaults={
            "label": label,
            "order_index": order_index,
            "extra": extra,
        },
    )
    link.label = label
    link.order_index = order_index
    link.extra = extra
    return link


# -----------------------------------------------------------------------------
# seeders
# -----------------------------------------------------------------------------

def seed_navigation_workspaces(session: Session) -> None:
    logger.info("🌱 Seeding Navigation Workspaces (FIXED)...")

    for ws_spec in WORKSPACES:
        ws = _upsert_workspace(session, ws_spec)

        # ROOT LINKS
        root_links = ws_spec.get("root_links") or []
        have_root = bool(root_links)
        root_sec = None

        if have_root:
            root_sec = _upsert_section(session, ws.id, "__ROOT__", 0)
            keep_routes: Set[str] = set()

            for idx, L in enumerate(root_links):
                if not L or "path" not in L or "label" not in L:
                    continue

                _upsert_standard_link(
                    session,
                    section_id=root_sec.id,
                    label=L["label"],
                    path=L["path"],
                    order_index=L.get("order_index", (idx + 1) * 10),
                    required_perm=L.get("perm"),
                )
                keep_routes.add(L["path"])

        # SECTIONS
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

            keep_routes: Set[str] = set()

            for lidx, L in enumerate(S.get("links") or []):
                if not L or "path" not in L or "label" not in L:
                    continue

                _upsert_standard_link(
                    session,
                    section_id=sec.id,
                    label=L["label"],
                    path=L["path"],
                    order_index=L.get("order_index", (lidx + 1) * 10),
                    required_perm=L.get("perm"),
                )
                keep_routes.add(L["path"])

        session.flush()

    logger.info("✅ Navigation seeded correctly (ERPNext-style).")


def seed_module_packages(session: Session) -> None:
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

        ws_rows = session.execute(
            select(Workspace.slug, Workspace.id).where(Workspace.slug.in_(pkg["workspaces"]))
        ).all()
        slug_to_id = {s: i for (s, i) in ws_rows}

        existing = session.execute(
            select(PackageWorkspace_.workspace_id).where(PackageWorkspace_.package_id == mp.id)
        ).scalars().all()

        have = set(existing)
        want = set(slug_to_id.values())

        for ws_id in want - have:
            session.add(PackageWorkspace_(package_id=mp.id, workspace_id=ws_id))

        for ws_id in have - want:
            session.query(PackageWorkspace_).filter_by(
                package_id=mp.id, workspace_id=ws_id
            ).delete()

    logger.info("✅ Module Packages seeded.")
