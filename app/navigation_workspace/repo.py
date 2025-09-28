# # app/navigation_workspace/repo.py

from __future__ import annotations
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload, selectinload, Session

from app.navigation_workspace.models.models_visibility import SystemNavVisibility, CompanyNavVisibility
from app.navigation_workspace.models.nav_links import Workspace, WorkspaceSection, WorkspaceLink
from config.database import db
from app.application_stock.stock_models import DocumentType
from app.application_rbac.rbac_models import Action
from app.common.models.base import StatusEnum

class NavRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def load_workspaces_tree(self) -> List[Workspace]:
        stmt = (
            select(Workspace)
            .where(Workspace.status == StatusEnum.ACTIVE)
            .options(
                selectinload(Workspace.root_links),
                selectinload(Workspace.sections).selectinload(WorkspaceSection.links),
            )
            .order_by(Workspace.order_index, Workspace.title)
        )
        return self.s.execute(stmt).scalars().all()

    def load_system_visibility(self, company_id: int) -> List[SystemNavVisibility]:
        return self.s.execute(
            select(SystemNavVisibility).where(SystemNavVisibility.company_id == company_id)
        ).scalars().all()

    def load_company_visibility(self, company_id: int, branch_id: Optional[int], user_id: Optional[int]) -> List[CompanyNavVisibility]:
        return self.s.execute(
            select(CompanyNavVisibility).where(
                CompanyNavVisibility.company_id == company_id,
                or_(CompanyNavVisibility.branch_id.is_(None), CompanyNavVisibility.branch_id == branch_id),
                or_(CompanyNavVisibility.user_id.is_(None), CompanyNavVisibility.user_id == user_id),
            )
        ).scalars().all()

    def map_doctype_names(self, ids: Iterable[int]) -> Dict[int, str]:
        ids = {i for i in ids if i}
        if not ids:
            return {}
        rows = self.s.execute(
            select(DocumentType.id, DocumentType.label).where(DocumentType.id.in_(ids))
        ).all()
        return {r.id: (r.label or "").strip() or str(r.id) for r in rows}

    def map_action_names(self, ids: Iterable[int]) -> Dict[int, str]:
        ids = {i for i in ids if i}
        if not ids:
            return {}
        rows = self.s.execute(select(Action.id, Action.name).where(Action.id.in_(ids))).all()
        return {r.id: r.name for r in rows}

    def find_workspace_by_slug(self, slug: str) -> Optional[Workspace]:
        return self.s.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()

    def find_link_by_path(self, workspace_id: int, route_path: str) -> Optional[WorkspaceLink]:
        return self.s.execute(
            select(WorkspaceLink).where(
                WorkspaceLink.route_path == route_path,
                or_(
                    WorkspaceLink.workspace_id == workspace_id,
                    WorkspaceLink.section_id.in_(
                        select(WorkspaceSection.id).where(WorkspaceSection.workspace_id == workspace_id)
                    ),
                )
            )
        ).scalar_one_or_none()

    def links_by_doctype(self) -> Dict[int, List[WorkspaceLink]]:
        links = self.s.execute(
            select(WorkspaceLink)
            .options(
                joinedload(WorkspaceLink.section).joinedload(WorkspaceSection.workspace),
                joinedload(WorkspaceLink.workspace),
            )
            .where(WorkspaceLink.doctype_id.isnot(None))
        ).scalars().all()

        by_dt: Dict[int, List[WorkspaceLink]] = {}
        for l in links:
            if l.doctype_id:
                by_dt.setdefault(l.doctype_id, []).append(l)
        return by_dt

    def load_all_doctypes(self) -> List[DocumentType]:
        return self.s.execute(select(DocumentType)).scalars().all()
