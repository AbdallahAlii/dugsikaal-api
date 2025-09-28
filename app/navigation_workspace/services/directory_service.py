# app/navigation_workspace/services/directory_service.py
from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select

from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import DocTypeDirectoryOut, DirectoryDoctype, DirectoryLocation, DocTypeDetailsOut
from config.database import db


from app.application_stock.stock_models import DocumentType


def _canon_perm(s: str) -> str:
    s = (s or "").strip()
    if not s: return s
    if ":" not in s:
        return s.upper()
    a, b = s.split(":", 1)
    return f"{a.strip().upper()}:{b.strip().upper()}"


def _dt_display_name(dt: DocumentType) -> str:
    name = getattr(dt, "name", None)
    label = getattr(dt, "label", None)
    if name and str(name).strip():
        return str(name).strip()
    if label and str(label).strip():
        return str(label).strip()
    code = getattr(dt, "code", None) or ""
    return code.replace("_", " ").title()


def _slugify(name: str) -> str:
    return (
        (name or "")
        .strip()
        .lower()
        .replace("&", "and")
        .replace("/", " ")
        .replace("_", " ")
        .replace("  ", " ")
        .replace(" ", "-")
    )


def _score_primary(link_path: str, link_type_name: str) -> int:
    # prefer LIST routes; then PAGE/REPORT; then others.
    if link_type_name == "LIST" or "/list" in (link_path or ""):
        return 3
    if link_type_name in ("PAGE", "REPORT"):
        return 2
    return 1


class DocTypeDirectoryService:
    """
    Builds a doc-type catalog independent of workspace visibility:
      • only filters by RBAC (must have READ)
      • finds all workspace locations that reference the doctype
      • chooses a 'primary_path' to act like 'Go to List'
      • groups by first workspace title if any, otherwise by domain name
    """
    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()

    def _actions_for(self, dt_name: str, perms: Set[str]) -> List[str]:
        prefix = f"{dt_name.upper()}:"
        out: Set[str] = set()
        for p in perms:
            if p.startswith(prefix):
                out.add(p.split(":", 1)[1])
        return sorted(out)

    def build_directory(self, *, perms: Set[str]) -> DocTypeDirectoryOut:
        perms = {_canon_perm(p) for p in (perms or set())}
        by_dt_links = self.repo.links_by_doctype()
        doctypes = self.repo.load_all_doctypes()

        out: List[DirectoryDoctype] = []

        for dt in doctypes:
            dt_name = _dt_display_name(dt)
            if _canon_perm(f"{dt_name}:READ") not in perms and "*" not in perms and "*:*" not in perms:
                continue

            links = by_dt_links.get(dt.id, [])
            # choose primary path
            primary = None
            best_score = -1
            for l in links:
                lt_name = l.link_type.name if hasattr(l.link_type, "name") else str(l.link_type)
                sc = _score_primary(l.route_path, lt_name)
                if sc > best_score:
                    best_score = sc
                    primary = l.route_path
            if not primary:
                # canonical fallback; frontend should know how to render
                primary = f"/app/doctype/{_slugify(dt_name)}"

            # locations (workspace + section + icon + path)
            locs: List[DirectoryLocation] = []
            group_label: Optional[str] = None
            for l in links:
                ws = l.workspace or (l.section.workspace if l.section else None)
                ws_title = ws.title if ws else ""
                ws_slug  = ws.slug if ws else ""
                sec_lbl  = l.section.label if l.section else None
                if not group_label and ws_title:
                    group_label = ws_title  # first workspace becomes the grouping label
                locs.append(DirectoryLocation(
                    workspace_slug=ws_slug,
                    workspace_title=ws_title,
                    section_label=sec_lbl,
                    path=l.route_path,
                    icon=l.icon,
                ))

            if not group_label:
                # fallback group by DocumentType.domain if your model has it, else "General"
                dm = getattr(dt, "domain", None)
                group_label = str(dm.name).title() if getattr(dm, "name", None) else "General"

            actions = self._actions_for(dt_name, perms)
            out.append(DirectoryDoctype(
                id=dt.id,
                name=dt_name,
                group=group_label,
                actions=actions,
                primary_path=primary,
                locations=locs,
            ))

        # sort by group then name
        out.sort(key=lambda r: (r.group.lower(), r.name.lower()))
        return DocTypeDirectoryOut(doctypes=out)

    def get_doctype_details(self, *, perms: Set[str], slug: str) -> Optional[DocTypeDetailsOut]:
        perms = {_canon_perm(p) for p in (perms or set())}
        slug = (slug or "").strip().lower()
        doctypes = self.repo.load_all_doctypes()
        match = None
        for dt in doctypes:
            if _slugify(_dt_display_name(dt)) == slug:
                match = dt
                break
        if not match:
            return None

        dt_name = _dt_display_name(match)
        if _canon_perm(f"{dt_name}:READ") not in perms and "*" not in perms and "*:*" not in perms:
            return None

        links_by_dt = self.repo.links_by_doctype()
        links = links_by_dt.get(match.id, [])

        # primary path
        primary = None
        best_score = -1
        for l in links:
            lt_name = l.link_type.name if hasattr(l.link_type, "name") else str(l.link_type)
            sc = _score_primary(l.route_path, lt_name)
            if sc > best_score:
                best_score = sc
                primary = l.route_path
        if not primary:
            primary = f"/app/doctype/{_slugify(dt_name)}"

        # group (first workspace title or domain)
        group_label: Optional[str] = None
        locs: List[DirectoryLocation] = []
        for l in links:
            ws = l.workspace or (l.section.workspace if l.section else None)
            ws_title = ws.title if ws else ""
            ws_slug  = ws.slug if ws else ""
            sec_lbl  = l.section.label if l.section else None
            if not group_label and ws_title:
                group_label = ws_title
            locs.append(DirectoryLocation(
                workspace_slug=ws_slug,
                workspace_title=ws_title,
                section_label=sec_lbl,
                path=l.route_path,
                icon=l.icon,
            ))
        if not group_label:
            dm = getattr(match, "domain", None)
            group_label = str(dm.name).title() if getattr(dm, "name", None) else "General"

        actions = self._actions_for(dt_name, perms)
        return DocTypeDetailsOut(
            id=match.id, name=dt_name, group=group_label, actions=actions,
            primary_path=primary, locations=locs
        )
