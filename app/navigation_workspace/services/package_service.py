from __future__ import annotations
from typing import Iterable, List, Dict, Optional
from datetime import datetime, timezone

from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import (
    CompanyPackagesSetIn,
    CompanyPackageOut,
    CompanyPackagesOut,
)
from app.navigation_workspace.models.subscription import ModulePackage, CompanyPackageSubscription
from app.navigation_workspace.models.nav_links import Workspace


class PackageService:
    """
    High-level operations for:
      • syncing ModulePackage + PackageWorkspace from MODULE_PACKAGES config
      • assigning packages to companies
    """

    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()

    def sync_from_config(self, config: Iterable[dict]) -> List[ModulePackage]:
        """
        Idempotent sync:
          - upsert ModulePackage rows
          - attach workspaces (by slug) to each package
        """
        ws_map: Dict[str, Workspace] = self.repo.map_workspaces_by_slug(
            slugs={slug for pkg in config for slug in pkg.get("workspaces", [])}
        )

        out: List[ModulePackage] = []

        for pkg_cfg in config:
            slug = pkg_cfg["slug"]
            name = pkg_cfg["name"]
            desc = pkg_cfg.get("description")
            is_enabled = bool(pkg_cfg.get("is_enabled", True))
            workspace_slugs: List[str] = pkg_cfg.get("workspaces", [])

            pkg = self.repo.upsert_module_package(
                slug=slug,
                name=name,
                description=desc,
                is_enabled=is_enabled,
            )

            # map slugs -> workspace ids (ignore unknown slugs)
            ws_ids = []
            for ws_slug in workspace_slugs:
                ws = ws_map.get(ws_slug)
                if ws:
                    ws_ids.append(ws.id)

            self.repo.set_package_workspaces(package=pkg, workspace_ids=ws_ids)
            out.append(pkg)

        return out

    def set_company_packages_for_company(
        self,
        *,
        company_id: int,
        body: CompanyPackagesSetIn,
    ) -> CompanyPackagesOut:
        """
        Assign package_slugs for a company; create/enable subscriptions and disable others.
        """
        # resolve package ids
        pkg_ids: List[int] = []
        for slug in body.package_slugs:
            pkg = self.repo.get_module_package_by_slug(slug)
            if not pkg:
                # skip unknown; in production you might raise
                continue
            pkg_ids.append(pkg.id)

        valid_from = body.valid_from
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)

        valid_until = body.valid_until
        if valid_until is not None and valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)

        subs = self.repo.set_company_packages(
            company_id=company_id,
            package_ids=pkg_ids,
            valid_from=valid_from,
            valid_until=valid_until,
        )

        # convert to DTO
        out_items: List[CompanyPackageOut] = []
        # load packages to map slug/name
        from app.navigation_workspace.models.subscription import ModulePackage as MP
        from sqlalchemy import select
        rows = self.repo.s.execute(
            select(MP.id, MP.slug, MP.name).where(MP.id.in_({s.package_id for s in subs}))
        ).all()
        by_id = {r.id: r for r in rows}

        for sub in subs:
            pkg_row = by_id.get(sub.package_id)
            out_items.append(
                CompanyPackageOut(
                    company_id=sub.company_id,
                    package_id=sub.package_id,
                    package_slug=pkg_row.slug if pkg_row else "",
                    package_name=pkg_row.name if pkg_row else "",
                    is_enabled=sub.is_enabled,
                    valid_from=sub.valid_from,
                    valid_until=sub.valid_until,
                )
            )

        return CompanyPackagesOut(company_id=company_id, packages=out_items)

    def get_company_packages(self, company_id: int) -> CompanyPackagesOut:
        subs = self.repo.list_company_package_subscriptions(company_id)
        from app.navigation_workspace.models.subscription import ModulePackage as MP
        from sqlalchemy import select
        rows = self.repo.s.execute(
            select(MP.id, MP.slug, MP.name).where(MP.id.in_({s.package_id for s in subs}))
        ).all()
        by_id = {r.id: r for r in rows}

        out_items: List[CompanyPackageOut] = []
        for sub in subs:
            pkg_row = by_id.get(sub.package_id)
            out_items.append(
                CompanyPackageOut(
                    company_id=sub.company_id,
                    package_id=sub.package_id,
                    package_slug=pkg_row.slug if pkg_row else "",
                    package_name=pkg_row.name if pkg_row else "",
                    is_enabled=sub.is_enabled,
                    valid_from=sub.valid_from,
                    valid_until=sub.valid_until,
                )
            )

        return CompanyPackagesOut(company_id=company_id, packages=out_items)
