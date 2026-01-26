from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import select, or_, and_, func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.navigation_workspace.models.workspace_roles import WorkspaceRole
from config.database import db

from app.navigation_workspace.models.nav_links import (
    Workspace,
    WorkspaceSection,
    Page,
    WorkspacePageLink,
)
from app.navigation_workspace.models.models_visibility import (
    SystemWorkspaceVisibility,
    CompanyWorkspaceVisibility,
)
from app.navigation_workspace.models.subscription import (
    ModulePackage,
    PackageWorkspace,
    CompanyPackageSubscription,
)

from app.application_stock.stock_models import DocumentType
from app.application_rbac.rbac_models import Action


class NavRepository:
    """
    Low-level data access for Workspaces, Pages, visibility and packages.
    Keeps all SQLAlchemy details here so services stay clean.
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---------------------------------------------------------
    # Workspaces + sections + page links tree
    # ---------------------------------------------------------
    def workspace_roles_map(self) -> dict[int, set[str]]:
        """
        Returns:
            { workspace_id: {role_name_lower, ...} }

        If workspace has no roles → workspace is PUBLIC.
        """
        rows = self.s.execute(   # ✅ FIX: use self.s
            select(WorkspaceRole.workspace_id, WorkspaceRole.role_name)
        ).all()

        result: dict[int, set[str]] = defaultdict(set)
        for ws_id, role in rows:
            if role:
                result[ws_id].add(" ".join(role.strip().split()).casefold())

        return dict(result)
    def load_workspaces_tree(self) -> List[Workspace]:
        """
        Load all workspaces with sections + page links + pages.
        Filtering (enabled, visibility, packages, admin_only) is done in service layer.
        """
        stmt = (
            select(Workspace)
            .options(
                selectinload(Workspace.sections)
                .selectinload(WorkspaceSection.page_links)
                .selectinload(WorkspacePageLink.page)
            )
            .order_by(Workspace.order_index, Workspace.title)
        )
        return self.s.execute(stmt).scalars().all()

    # ---------------------------------------------------------
    # Visibility (system + company)
    # ---------------------------------------------------------

    def load_system_visibility(self, company_id: Optional[int]) -> List[SystemWorkspaceVisibility]:
        """
        Per-company system level toggle for each workspace.
        Missing row => inherit.
        """
        if not company_id:
            return []
        stmt = select(SystemWorkspaceVisibility).where(
            SystemWorkspaceVisibility.company_id == company_id
        )
        return self.s.execute(stmt).scalars().all()

    def load_company_visibility(
        self,
        company_id: Optional[int],
        branch_id: Optional[int],
        user_id: Optional[int],
    ) -> List[CompanyWorkspaceVisibility]:
        """
        Tenant overrides: company-wide / per-branch / per-user.
        We still filter by company here, but branch/user precedence is applied
        later in service.
        """
        if not company_id:
            return []
        stmt = select(CompanyWorkspaceVisibility).where(
            CompanyWorkspaceVisibility.company_id == company_id
        )
        # Note: we *do not* filter on branch/user at SQL level to keep all
        # candidate rows; precedence is resolved in Python.
        return self.s.execute(stmt).scalars().all()

    # ---------------------------------------------------------
    # Package / subscription (SaaS layer)
    # ---------------------------------------------------------

    def licensed_workspace_ids_for_company(self, company_id: Optional[int]) -> Set[int]:
        """
        Workspaces included in any enabled package subscription for this company,
        within validity dates.
        """
        if not company_id:
            return set()

        now = func.now()
        stmt = (
            select(PackageWorkspace.workspace_id)
            .join(ModulePackage, PackageWorkspace.package_id == ModulePackage.id)
            .join(
                CompanyPackageSubscription,
                CompanyPackageSubscription.package_id == ModulePackage.id,
            )
            .where(
                CompanyPackageSubscription.company_id == company_id,
                CompanyPackageSubscription.is_enabled.is_(True),
                ModulePackage.is_enabled.is_(True),
                CompanyPackageSubscription.valid_from <= now,
                or_(
                    CompanyPackageSubscription.valid_until.is_(None),
                    CompanyPackageSubscription.valid_until >= now,
                ),
            )
        )
        rows = self.s.execute(stmt).scalars().all()
        return set(rows)

    # ---------------------------------------------------------
    # DocType + Action name lookups (for RBAC mapping)
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # DocType directory helpers
    # ---------------------------------------------------------

    def links_by_doctype(self) -> Dict[int, List[WorkspacePageLink]]:
        """
        Return all WorkspacePageLinks whose Page is tied to a DocType.
        Used by DocTypeDirectoryService to figure out primary_path + locations.
        """
        stmt = (
            select(WorkspacePageLink)
            .join(WorkspacePageLink.page)
            .join(WorkspacePageLink.section)
            .join(WorkspaceSection.workspace)
            .options(
                joinedload(WorkspacePageLink.page),
                joinedload(WorkspacePageLink.section).joinedload(WorkspaceSection.workspace),
            )
            .where(
                Page.doctype_id.isnot(None),
                Page.is_enabled.is_(True),
                Workspace.is_enabled.is_(True),
            )
        )
        links = self.s.execute(stmt).scalars().all()

        by_dt: Dict[int, List[WorkspacePageLink]] = {}
        for l in links:
            if not l.page or not l.page.doctype_id:
                continue
            by_dt.setdefault(l.page.doctype_id, []).append(l)
        return by_dt

    def load_all_doctypes(self) -> List[DocumentType]:
        return self.s.execute(select(DocumentType)).scalars().all()

        # ---------------------------------------------------------
        # Workspace helpers
        # ---------------------------------------------------------

    def find_workspace_by_slug(self, slug: str) -> Optional[Workspace]:
        stmt = select(Workspace).where(Workspace.slug == slug)
        return self.s.execute(stmt).scalar_one_or_none()

    def map_workspaces_by_slug(self, slugs: Iterable[str]) -> Dict[str, Workspace]:
        slugs = {s for s in slugs if s}
        if not slugs:
            return {}
        rows = self.s.execute(select(Workspace).where(Workspace.slug.in_(slugs))).scalars().all()
        return {w.slug: w for w in rows}

     # ---------------------------------------------------------
     # Package + subscription admin
     # ---------------------------------------------------------

    def get_module_package_by_slug(self, slug: str) -> Optional[ModulePackage]:
        stmt = select(ModulePackage).where(ModulePackage.slug == slug)
        return self.s.execute(stmt).scalar_one_or_none()

    def upsert_module_package(
            self,
            *,
            slug: str,
            name: str,
            description: Optional[str],
            is_enabled: bool,
    ) -> ModulePackage:
        pkg = self.get_module_package_by_slug(slug)
        if pkg is None:
            pkg = ModulePackage(slug=slug, name=name, description=description, is_enabled=is_enabled)
            self.s.add(pkg)
        else:
            pkg.name = name
            pkg.description = description
            pkg.is_enabled = is_enabled
        self.s.flush()
        return pkg

    def set_package_workspaces(
            self,
            *,
            package: ModulePackage,
            workspace_ids: Iterable[int],
    ) -> None:
        """
        Replace all PackageWorkspace rows for this package with the given workspace_ids.
        """
        workspace_ids = {int(wid) for wid in workspace_ids}
        # delete old
        self.s.query(PackageWorkspace).filter(
            PackageWorkspace.package_id == package.id
        ).delete(synchronize_session=False)
        # insert new
        for wid in workspace_ids:
            self.s.add(PackageWorkspace(package_id=package.id, workspace_id=wid))
        self.s.flush()

    def list_company_package_subscriptions(self, company_id: int) -> List[CompanyPackageSubscription]:
        stmt = (
            select(CompanyPackageSubscription)
            .where(CompanyPackageSubscription.company_id == company_id)
        )
        return self.s.execute(stmt).scalars().all()

    def set_company_packages(
            self,
            *,
            company_id: int,
            package_ids: Iterable[int],
            valid_from: datetime,
            valid_until: Optional[datetime] = None,
    ) -> List[CompanyPackageSubscription]:
        """
        Idempotent:
          - enable or create subs for package_ids
          - disable subs for other packages of this company
        """
        package_ids = {int(pid) for pid in package_ids}
        existing = self.list_company_package_subscriptions(company_id)

        # index by package_id
        by_package: Dict[int, CompanyPackageSubscription] = {
            sub.package_id: sub for sub in existing
        }

        # 1) ensure all desired packages exist (create/enable/update)
        for pid in package_ids:
            sub = by_package.get(pid)
            if sub is None:
                sub = CompanyPackageSubscription(
                    company_id=company_id,
                    package_id=pid,
                    is_enabled=True,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    extra={},
                )
                self.s.add(sub)
                by_package[pid] = sub
            else:
                sub.is_enabled = True
                sub.valid_from = valid_from
                sub.valid_until = valid_until

        # 2) disable any other packages
        for sub in existing:
            if sub.package_id not in package_ids:
                sub.is_enabled = False

        self.s.flush()
        return list(by_package.values())

     # ---------------------------------------------------------
     # Visibility admin helpers
     # ---------------------------------------------------------

    def upsert_system_workspace_visibility(
            self,
            *,
            company_id: int,
            workspace_id: int,
            is_enabled: bool,
            reason: Optional[str] = None,
    ) -> SystemWorkspaceVisibility:
        stmt = select(SystemWorkspaceVisibility).where(
            SystemWorkspaceVisibility.company_id == company_id,
            SystemWorkspaceVisibility.workspace_id == workspace_id,
        )
        row = self.s.execute(stmt).scalar_one_or_none()
        if row is None:
            row = SystemWorkspaceVisibility(
                company_id=company_id,
                workspace_id=workspace_id,
                is_enabled=is_enabled,
                reason=reason,
            )
            self.s.add(row)
        else:
            row.is_enabled = is_enabled
            row.reason = reason
        self.s.flush()
        return row

    def upsert_company_workspace_visibility(
            self,
            *,
            company_id: int,
            workspace_id: int,
            branch_id: Optional[int],
            user_id: Optional[int],
            is_enabled: bool,
            reason: Optional[str] = None,
    ) -> CompanyWorkspaceVisibility:
        stmt = select(CompanyWorkspaceVisibility).where(
            CompanyWorkspaceVisibility.company_id == company_id,
            CompanyWorkspaceVisibility.workspace_id == workspace_id,
            CompanyWorkspaceVisibility.branch_id.is_(branch_id if branch_id is not None else None),
            CompanyWorkspaceVisibility.user_id.is_(user_id if user_id is not None else None),
        )
        row = self.s.execute(stmt).scalar_one_or_none()
        if row is None:
            row = CompanyWorkspaceVisibility(
                company_id=company_id,
                workspace_id=workspace_id,
                branch_id=branch_id,
                user_id=user_id,
                is_enabled=is_enabled,
                reason=reason,
            )
            self.s.add(row)
        else:
            row.is_enabled = is_enabled
            row.reason = reason
        self.s.flush()
        return row



