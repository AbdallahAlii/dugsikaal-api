# # app/application_org/repository/org_repo.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import db
from app.application_org.models.company import Company, Branch, City
from app.auth.models.users import User, UserAffiliation, UserType
from app.common.models.base import StatusEnum
from datetime import datetime, timezone
from app.navigation_workspace.models.subscription import ModulePackage, CompanyPackageSubscription

from app.navigation_workspace.models.subscription import (
    ModulePackage,
    CompanyPackageSubscription,
)

import logging
log = logging.getLogger(__name__)

class OrgRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ------------------------------------------------------------------
    # City helpers
    # ------------------------------------------------------------------
    def get_city_by_id(self, city_id: int) -> Optional[City]:
        return self.s.get(City, city_id)

    # ------------------------------------------------------------------
    # Company helpers
    # ------------------------------------------------------------------
    def company_name_exists(self, name: str) -> bool:
        stmt = select(Company.id).where(func.lower(Company.name) == func.lower(name))
        return bool(self.s.scalar(stmt))

    def company_prefix_exists(self, prefix: str) -> bool:
        stmt = select(Company.id).where(
            Company.prefix.isnot(None),
            func.lower(Company.prefix) == func.lower(prefix),
        )
        return bool(self.s.scalar(stmt))

    def get_company_by_id(self, company_id: int) -> Optional[Company]:
        return self.s.get(Company, company_id)

    def create_company(self, c: Company) -> Company:
        self.s.add(c)
        self.s.flush([c])
        return c

    def update_company_fields(self, c: Company, data: dict) -> None:
        for field, value in data.items():
            if hasattr(c, field) and value is not None:
                setattr(c, field, value)
        self.s.flush([c])

    def update_company_img_key(self, company: Company, img_key: str) -> None:
        company.img_key = img_key
        self.s.flush([company])

    def delete_company(self, company: Company) -> None:
        self.s.delete(company)
        self.s.flush()

    # ------------------------------------------------------------------
    # Branch helpers
    # ------------------------------------------------------------------
    def get_branch_by_id(self, branch_id: int) -> Optional[Branch]:
        return self.s.get(Branch, branch_id)

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.scalar(stmt)

    def branch_name_exists(
        self,
        *,
        company_id: int,
        name: str,
        exclude_branch_id: Optional[int] = None,
    ) -> bool:
        stmt = select(Branch.id).where(
            Branch.company_id == company_id,
            func.lower(Branch.name) == func.lower(name),
        )
        if exclude_branch_id:
            stmt = stmt.where(Branch.id != exclude_branch_id)
        return bool(self.s.scalar(stmt))

    def branch_code_exists(
        self,
        *,
        code: str,
        exclude_branch_id: Optional[int] = None,
    ) -> bool:
        stmt = select(Branch.id).where(func.lower(Branch.code) == func.lower(code))
        if exclude_branch_id:
            stmt = stmt.where(Branch.id != exclude_branch_id)
        return bool(self.s.scalar(stmt))

    def has_hq_branch(
        self,
        *,
        company_id: int,
        exclude_branch_id: Optional[int] = None,
    ) -> bool:
        stmt = select(Branch.id).where(
            Branch.company_id == company_id,
            Branch.is_hq.is_(True),
        )
        if exclude_branch_id:
            stmt = stmt.where(Branch.id != exclude_branch_id)
        return bool(self.s.scalar(stmt))

    def create_branch(self, b: Branch) -> Branch:
        self.s.add(b)
        self.s.flush([b])
        return b

    def update_branch_fields(self, b: Branch, data: dict) -> None:
        for field, value in data.items():
            if hasattr(b, field) and value is not None:
                setattr(b, field, value)
        self.s.flush([b])

    def update_branch_img_key(self, branch: Branch, img_key: str) -> None:
        branch.img_key = img_key
        self.s.flush([branch])

    def list_branch_ids_for_company(self, company_id: int) -> List[int]:
        return list(self.s.execute(select(Branch.id).where(Branch.company_id == company_id)).scalars().all())

    # ------------------------------------------------------------------
    # User + affiliation for company owner
    # ------------------------------------------------------------------
    def get_user_type_by_name(self, name: str) -> Optional[UserType]:
        stmt = select(UserType).where(func.lower(UserType.name) == func.lower(name))
        return self.s.scalar(stmt)

    def create_user_and_affiliation(
        self,
        *,
        username: str,
        password_hash: str,
        company_id: int,
        user_type: UserType,
        make_primary: bool = True,
        branch_id: Optional[int] = None,
        linked_entity_id: Optional[int] = None,
    ) -> User:
        u = User(username=username, password_hash=password_hash, status=StatusEnum.ACTIVE)
        self.s.add(u)
        self.s.flush([u])

        aff = UserAffiliation(
            user_id=u.id,
            company_id=company_id,
            branch_id=branch_id,
            user_type_id=user_type.id,
            linked_entity_id=linked_entity_id,
            is_primary=make_primary,
        )
        self.s.add(aff)
        self.s.flush([aff])
        return u

    # ------------------------------------------------------------------
    # Packages / subscriptions (UI-managed)
    # ------------------------------------------------------------------
    def list_module_packages(self, *, enabled_only: bool = True) -> List[ModulePackage]:
        stmt = select(ModulePackage)
        if enabled_only:
            stmt = stmt.where(ModulePackage.is_enabled.is_(True))
        stmt = stmt.order_by(ModulePackage.name.asc())
        return list(self.s.execute(stmt).scalars().all())

    def get_module_package_by_slug(self, slug: str) -> Optional[ModulePackage]:
        return self.s.scalar(select(ModulePackage).where(ModulePackage.slug == slug))

    def get_company_subscriptions(self, company_id: int) -> List[CompanyPackageSubscription]:
        stmt = (
            select(CompanyPackageSubscription)
            .where(CompanyPackageSubscription.company_id == company_id)
            .order_by(CompanyPackageSubscription.id.asc())
        )
        return list(self.s.execute(stmt).scalars().all())

    def upsert_company_subscription(
        self,
        *,
        company_id: int,
        package: ModulePackage,
        is_enabled: bool,
        valid_until,
        extra: Dict[str, Any],
    ) -> CompanyPackageSubscription:
        cps = self.s.scalar(
            select(CompanyPackageSubscription).where(
                CompanyPackageSubscription.company_id == company_id,
                CompanyPackageSubscription.package_id == package.id,
            )
        )
        now_utc = datetime.now(timezone.utc)

        if cps:
            cps.is_enabled = bool(is_enabled)
            cps.valid_until = valid_until
            cps.extra = extra or {}
            self.s.flush([cps])
            return cps

        cps = CompanyPackageSubscription(
            company_id=company_id,
            package_id=package.id,
            is_enabled=bool(is_enabled),
            valid_from=now_utc,
            valid_until=valid_until,
            extra=extra or {},
        )
        self.s.add(cps)
        self.s.flush([cps])
        return cps



    # ------------------------------------------------------------------
    # Packages / subscriptions
    # ------------------------------------------------------------------
    def get_package_by_slug(self, slug: str) -> Optional[ModulePackage]:
        stmt = select(ModulePackage).where(ModulePackage.slug == slug)
        return self.s.scalar(stmt)

    def get_company_package_subscription(self, company_id: int, package_id: int) -> Optional[CompanyPackageSubscription]:
        stmt = select(CompanyPackageSubscription).where(
            CompanyPackageSubscription.company_id == company_id,
            CompanyPackageSubscription.package_id == package_id,
        )
        return self.s.scalar(stmt)

    def upsert_company_package_subscription(
        self,
        *,
        company_id: int,
        package_id: int,
        is_enabled: bool,
        valid_until: Optional[datetime],
        extra: dict,
    ) -> CompanyPackageSubscription:
        now_utc = datetime.now(timezone.utc)
        cps = self.get_company_package_subscription(company_id, package_id)
        if cps:
            cps.is_enabled = bool(is_enabled)
            if cps.valid_from is None:
                cps.valid_from = now_utc
            cps.valid_until = valid_until
            cps.extra = extra or {}
            self.s.flush([cps])
            return cps

        cps = CompanyPackageSubscription(
            company_id=company_id,
            package_id=package_id,
            is_enabled=bool(is_enabled),
            valid_from=now_utc,
            valid_until=valid_until,
            extra=extra or {},
        )
        self.s.add(cps)
        self.s.flush([cps])
        return cps
    def set_company_status(self, company_id: int, status: StatusEnum) -> None:
        self.s.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(status=status)
        )

    def set_branches_status_for_company(self, company_id: int, status: StatusEnum) -> None:
        self.s.execute(
            update(Branch)
            .where(Branch.company_id == company_id)
            .values(status=status)
        )

    def disable_company_subscriptions(self, company_id: int) -> None:
        now_utc = datetime.now(timezone.utc)
        self.s.execute(
            update(CompanyPackageSubscription)
            .where(CompanyPackageSubscription.company_id == company_id)
            .values(is_enabled=False, valid_until=now_utc)
        )

    def archive_company_subscriptions(self, company_id: int) -> None:
        now_utc = datetime.now(timezone.utc)

        subs = list(
            self.s.execute(
                select(CompanyPackageSubscription)
                .where(CompanyPackageSubscription.company_id == company_id)
                .order_by(CompanyPackageSubscription.id.asc())
            ).scalars().all()
        )

        log.info("[subs][archive] company_id=%s subs=%s", company_id, len(subs))

        for s in subs:
            before_enabled = bool(s.is_enabled)
            before_valid_until = s.valid_until
            extra = dict(s.extra or {})

            # Always overwrite (so it's correct even if you archive twice)
            extra["_prev_enabled"] = before_enabled
            extra["_prev_valid_until"] = before_valid_until.isoformat() if before_valid_until else None
            extra["_archived_by_company"] = True
            extra["_archived_at"] = now_utc.isoformat()

            s.extra = extra
            s.is_enabled = False
            # Use valid_until as “blocked until now” (and restore will put it back)
            s.valid_until = now_utc

            log.info(
                "[subs][archive] sub_id=%s pkg_id=%s before_enabled=%s -> after_enabled=%s before_valid_until=%s -> after_valid_until=%s extra=%s",
                s.id, s.package_id, before_enabled, s.is_enabled, before_valid_until, s.valid_until, s.extra
            )

        self.s.flush(subs)

    def restore_company_subscriptions(self, company_id: int, *, legacy_restore: bool = False) -> None:
        subs = list(
            self.s.execute(
                select(CompanyPackageSubscription)
                .where(CompanyPackageSubscription.company_id == company_id)
                .order_by(CompanyPackageSubscription.id.asc())
            ).scalars().all()
        )

        log.info("[subs][restore] company_id=%s subs=%s legacy_restore=%s", company_id, len(subs), legacy_restore)

        for s in subs:
            before_enabled = bool(s.is_enabled)
            before_valid_until = s.valid_until
            extra = dict(s.extra or {})

            if "_prev_enabled" in extra:
                prev_enabled = bool(extra.get("_prev_enabled", False))

                prev_valid_until_raw = extra.get("_prev_valid_until", None)
                prev_valid_until = None
                if prev_valid_until_raw:
                    try:
                        prev_valid_until = datetime.fromisoformat(prev_valid_until_raw)
                    except Exception:
                        prev_valid_until = None

            else:
                # 👇 Legacy restore: only when called from Restore Company
                if not legacy_restore:
                    log.warning(
                        "[subs][restore] sub_id=%s pkg_id=%s SKIP (no _prev_enabled marker). before_enabled=%s before_valid_until=%s extra=%s",
                        s.id, s.package_id, before_enabled, before_valid_until, extra
                    )
                    continue

                # Legacy heuristic:
                # If restore is requested and we have no marker, assume it was enabled before archive.
                prev_enabled = True
                prev_valid_until = None

                log.warning(
                    "[subs][restore] sub_id=%s pkg_id=%s LEGACY restore (no marker). before_enabled=%s before_valid_until=%s -> enable=True",
                    s.id, s.package_id, before_enabled, before_valid_until
                )

            # Never enable if package disabled globally
            pkg = self.s.get(ModulePackage, s.package_id)
            pkg_enabled = (pkg is None) or bool(pkg.is_enabled)
            if not pkg_enabled:
                prev_enabled = False

            s.is_enabled = bool(prev_enabled)
            s.valid_until = prev_valid_until

            # cleanup markers if any
            extra.pop("_prev_enabled", None)
            extra.pop("_prev_valid_until", None)
            extra.pop("_archived_by_company", None)
            extra.pop("_archived_at", None)
            s.extra = extra

            log.info(
                "[subs][restore] sub_id=%s pkg_id=%s pkg_enabled=%s before_enabled=%s -> after_enabled=%s before_valid_until=%s -> after_valid_until=%s",
                s.id, s.package_id, pkg_enabled, before_enabled, s.is_enabled, before_valid_until, s.valid_until
            )

        self.s.flush(subs)
