#
# # seed_data/navigation_workspace/seeder.py

from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.navigation_workspace.models.nav_links import (
    Workspace, WorkspaceSection, WorkspaceLink, NavLinkTypeEnum,
)
from .data import WORKSPACES

logger = logging.getLogger(__name__)

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
            # persist new admin_only flag if your model has it
            "admin_only": bool(spec.get("admin_only", False)),
        },
    )
    ws.title = spec["title"]
    ws.icon = spec.get("icon")
    ws.description = spec.get("description")
    ws.order_index = spec.get("order_index", ws.order_index or 100)
    # keep admin_only in sync with spec (default False)
    if hasattr(ws, "admin_only"):
        ws.admin_only = bool(spec.get("admin_only", False))
    return ws

def _upsert_section(session: Session, ws_id: int, label: str, order_index: int) -> WorkspaceSection:
    sec, _ = _get_or_create(
        session,
        WorkspaceSection,
        workspace_id=ws_id,
        label=label,
        defaults={"order_index": order_index},
    )
    sec.order_index = order_index
    return sec

def _upsert_root_link(session: Session, ws_id: int, *, label: str, path: str, icon: Optional[str], order_index: int, perm: Optional[str]) -> WorkspaceLink:
    link = session.scalar(
        select(WorkspaceLink).where(
            WorkspaceLink.workspace_id == ws_id,
            WorkspaceLink.section_id.is_(None),
            WorkspaceLink.route_path == path,
        )
    )
    if not link:
        link = WorkspaceLink(
            workspace_id=ws_id,
            section_id=None,
            label=label,
            link_type=NavLinkTypeEnum.LIST,
            route_path=path,
            icon=icon,
            order_index=order_index,
            required_permission_str=(perm or None),
        )
        session.add(link)
        session.flush([link])
        return link

    link.label = label
    link.link_type = NavLinkTypeEnum.LIST
    link.icon = icon
    link.order_index = order_index
    link.required_permission_str = (perm or None)
    return link

def _upsert_section_link(session: Session, sec_id: int, *, label: str, path: str, icon: Optional[str], order_index: int, perm: Optional[str]) -> WorkspaceLink:
    link = session.scalar(
        select(WorkspaceLink).where(
            WorkspaceLink.section_id == sec_id,
            WorkspaceLink.workspace_id.is_(None),
            WorkspaceLink.route_path == path,
        )
    )
    if not link:
        link = WorkspaceLink(
            workspace_id=None,
            section_id=sec_id,
            label=label,
            link_type=NavLinkTypeEnum.LIST,
            route_path=path,
            icon=icon,
            order_index=order_index,
            required_permission_str=(perm or None),
        )
        session.add(link)
        session.flush([link])
        return link

    link.label = label
    link.link_type = NavLinkTypeEnum.LIST
    link.icon = icon
    link.order_index = order_index
    link.required_permission_str = (perm or None)
    return link

# ---------- PRUNE HELPERS ----------
def _prune_sections_not_in_spec(session: Session, ws_id: int, keep_labels: Set[str]) -> None:
    existing = session.scalars(select(WorkspaceSection).where(WorkspaceSection.workspace_id == ws_id)).all()
    for sec in existing:
        if sec.label not in keep_labels:
            session.delete(sec)  # ondelete CASCADE will remove its links

def _prune_root_links_not_in_spec(session: Session, ws_id: int, keep_paths: Set[str]) -> None:
    existing = session.scalars(
        select(WorkspaceLink).where(
            WorkspaceLink.workspace_id == ws_id,
            WorkspaceLink.section_id.is_(None),
        )
    ).all()
    for link in existing:
        if link.route_path not in keep_paths:
            session.delete(link)

def _prune_section_links_not_in_spec(session: Session, sec_id: int, keep_paths: Set[str]) -> None:
    existing = session.scalars(
        select(WorkspaceLink).where(
            WorkspaceLink.section_id == sec_id,
            WorkspaceLink.workspace_id.is_(None),
        )
    ).all()
    for link in existing:
        if link.route_path not in keep_paths:
            session.delete(link)

def seed_navigation_workspaces(session: Session) -> None:
    """
    Idempotently seeds:
      • Workspaces
      • Sections
      • LIST links
    Also prunes any sections/links that are no longer present in the spec.
    """
    logger.info("🌱 Seeding Navigation Workspaces...")

    for ws_idx, ws_spec in enumerate(WORKSPACES):
        ws = _upsert_workspace(session, ws_spec)

        # ----- root links (desired set) -----
        desired_root_paths: Set[str] = set()
        root_links = ws_spec.get("root_links") or []
        for li_idx, L in enumerate(root_links):
            # skip invalid link specs defensively
            if not L or "path" not in L or "label" not in L:
                continue
            desired_root_paths.add(L["path"])
            _upsert_root_link(
                session,
                ws.id,
                label=L["label"],
                path=L["path"],
                icon=L.get("icon"),
                order_index=L.get("order_index", (li_idx + 1) * 10),
                perm=L.get("perm"),
            )
        _prune_root_links_not_in_spec(session, ws.id, desired_root_paths)

        # ----- sections + links (desired sets) -----
        desired_section_labels: Set[str] = set()
        for sec_idx, S in enumerate(ws_spec.get("sections") or []):
            # HARDEN: skip empties or unlabeled sections
            if not S or not S.get("label"):
                continue
            desired_section_labels.add(S["label"])
            sec = _upsert_section(session, ws.id, S["label"], S.get("order_index", (sec_idx + 1) * 10))

            desired_sec_paths: Set[str] = set()
            for li_idx, L in enumerate(S.get("links") or []):
                if not L or "path" not in L or "label" not in L:
                    continue
                desired_sec_paths.add(L["path"])
                _upsert_section_link(
                    session,
                    sec.id,
                    label=L["label"],
                    path=L["path"],
                    icon=L.get("icon"),
                    order_index=L.get("order_index", (li_idx + 1) * 10),
                    perm=L.get("perm"),
                )
            _prune_section_links_not_in_spec(session, sec.id, desired_sec_paths)

        _prune_sections_not_in_spec(session, ws.id, desired_section_labels)

    logger.info("✅ Navigation Workspaces seeded.")
