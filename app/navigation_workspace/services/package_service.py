# app/navigation_workspace/services/package_service.py
from __future__ import annotations

from typing import Iterable, List, Dict, Optional
from datetime import datetime, date

from sqlalchemy import select

from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import (
    CompanyPackagesSetIn,
    CompanyPackageOut,
    CompanyPackagesOut,
    CompanyPackageToggleIn,
)
from app.navigation_workspace.models.subscription import (
    ModulePackage,
    CompanyPackageSubscription,
)
from app.navigation_workspace.models.nav_links import Workspace
from app.common.timezone.service import company_posting_dt  # ✅ use timezone helper, no FiscalYear


class PackageService:
    """
    High-level operations for:
      • syncing ModulePackage + PackageWorkspace from MODULE_PACKAGES config
      • assigning packages to companies (bulk + single)
    """

    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()
        self.s = self.repo.s

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    def _normalize_date_for_company(
        self,
        company_id: int,
        d: date,
    ) -> datetime:
        """
        Convert a DATE (no time from UI) to a company-aware datetime.

        IMPORTANT:
        - We use company_posting_dt to attach the correct timezone and a time-of-day.
        - We DO NOT run FiscalYear / posting-date business validation here.
          Package subscriptions are SaaS-layer, not accounting documents.
        """
        if d is None:
            # Fallback: just use "today" in company timezone
            today = datetime.utcnow().date()
            return company_posting_dt(
                self.s,
                company_id,
                today,
                treat_midnight_as_date=True,
            )

        # Pydantic already parsed the string to a date (e.g. "2025-11-27" → date(2025, 11, 27))
        return company_posting_dt(
            self.s,
            company_id,
            d,
            treat_midnight_as_date=True,
        )

    # ---------------------------------------------------------
    # Sync from config
    # ---------------------------------------------------------

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

            ws_ids = []
            for ws_slug in workspace_slugs:
                ws = ws_map.get(ws_slug)
                if ws:
                    ws_ids.append(ws.id)

            self.repo.set_package_workspaces(package=pkg, workspace_ids=ws_ids)
            out.append(pkg)

        return out

    # ---------------------------------------------------------
    # Bulk set/toggle many packages for a company
    # ---------------------------------------------------------

    def bulk_set_company_packages_for_company(
        self,
        *,
        company_id: int,
        body: CompanyPackagesSetIn,
    ) -> CompanyPackagesOut:
        """
        ERP-style bulk update:
          body = {
            "packages": [
              {
                "slug": "selling",
                "is_enabled": true,
                "valid_from": "2025-11-27",
                "valid_until": "2026-01-01"
              },
              {
                "slug": "inventory",
                "is_enabled": false,
                "valid_from": "2025-11-27",
                "valid_until": null
              }
            ]
          }

        - Each row is independent (no magic 'missing slug' rules).
        - Disable = send is_enabled=false for that slug.
        """
        updated: List[CompanyPackageOut] = []

        for pkg_in in body.packages:
            toggle_body = CompanyPackageToggleIn(
                is_enabled=pkg_in.is_enabled,
                valid_from=pkg_in.valid_from,
                valid_until=pkg_in.valid_until,
            )
            out = self.upsert_company_package_for_company(
                company_id=company_id,
                package_slug=pkg_in.slug,
                body=toggle_body,
            )
            updated.append(out)

        # Option B (nicer for UI): return full state for this company
        full_state = self.get_company_packages(company_id=company_id)
        return full_state

    # ---------------------------------------------------------
    # Get all packages for a company
    # ---------------------------------------------------------

    def get_company_packages(self, company_id: int) -> CompanyPackagesOut:
        subs = self.repo.list_company_package_subscriptions(company_id)

        rows = self.s.execute(
            select(ModulePackage.id, ModulePackage.slug, ModulePackage.name)
            .where(ModulePackage.id.in_({s.package_id for s in subs}))
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

    # ---------------------------------------------------------
    # Upsert / enable / disable a single company-package
    # ---------------------------------------------------------

    def upsert_company_package_for_company(
        self,
        *,
        company_id: int,
        package_slug: str,
        body: CompanyPackageToggleIn,
    ) -> CompanyPackageOut:
        """
        Enable/disable one CompanyPackageSubscription for (company_id, package_slug).

        Behavior:
          - If subscription exists: update is_enabled + dates (if provided).
          - If not exists AND is_enabled=True: create subscription
            (valid_from is REQUIRED).
          - If not exists AND is_enabled=False: no-op (no subscription row).
        """
        pkg = self.repo.get_module_package_by_slug(package_slug)
        if not pkg:
            raise ValueError(f"Unknown package slug: {package_slug!r}")

        sub: Optional[CompanyPackageSubscription] = self.s.scalar(
            select(CompanyPackageSubscription).where(
                CompanyPackageSubscription.company_id == company_id,
                CompanyPackageSubscription.package_id == pkg.id,
            )
        )

        # NEW subscription
        if sub is None:
            if not body.is_enabled:
                # No existing subscription and disabled => nothing to do.
                # Build a "virtual" DTO for response.
                now_dt = company_posting_dt(self.s, company_id, datetime.utcnow().date())
                return CompanyPackageOut(
                    company_id=company_id,
                    package_id=pkg.id,
                    package_slug=pkg.slug,
                    package_name=pkg.name,
                    is_enabled=False,
                    valid_from=now_dt,
                    valid_until=None,
                )

            # enabling new package => valid_from is required
            if body.valid_from is None:
                raise ValueError("valid_from is required when enabling a new package.")

            valid_from_dt = self._normalize_date_for_company(company_id, body.valid_from)
            valid_until_dt: Optional[datetime] = None
            if body.valid_until is not None:
                valid_until_dt = self._normalize_date_for_company(company_id, body.valid_until)

            sub = CompanyPackageSubscription(
                company_id=company_id,
                package_id=pkg.id,
                is_enabled=True,
                valid_from=valid_from_dt,
                valid_until=valid_until_dt,
                extra={},
            )
            self.s.add(sub)
            self.s.flush([sub])
        else:
            # Existing subscription → update flags and dates conditionally
            sub.is_enabled = body.is_enabled

            if body.valid_from is not None:
                sub.valid_from = self._normalize_date_for_company(company_id, body.valid_from)

            if body.valid_until is not None:
                sub.valid_until = self._normalize_date_for_company(company_id, body.valid_until)

            self.s.flush([sub])

        return CompanyPackageOut(
            company_id=sub.company_id,
            package_id=sub.package_id,
            package_slug=pkg.slug,
            package_name=pkg.name,
            is_enabled=sub.is_enabled,
            valid_from=sub.valid_from,
            valid_until=sub.valid_until,
        )
