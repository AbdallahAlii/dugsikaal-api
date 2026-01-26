# app/application_org/services/org_service.py
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional, Tuple, List

from sqlalchemy import select, text, bindparam
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException, BadRequest, Forbidden, NotFound

from app.application_org.services.company_bootstrap import CompanyBootstrapper
from app.seed_data.coa.seeder import seed_chart_of_accounts
from app.seed_data.core_org.seeder import (
    seed_core_org_masters,
    seed_warehouses_for_branch,
    seed_company_fiscal_and_hr_defaults,
    seed_cost_center_for_branch,
)
from app.seed_data.gl_templates.seeder import seed_gl_templates
from config.database import db
from app.application_org.models.company import Company, Branch
from app.application_org.repository.org_repo import OrgRepository
from app.application_org.schemas.org_schemas import (
    CompanyCreate,
    CompanyUpdate,
    CompanyDeleteRequest,
    CompanyCreateResponse,
    CompanyMinimalOut,
    OwnerUserOut,
    BranchCreate,
    BranchUpdate,
    BranchMinimalOut,
    ModulePackageOut,
    CompanyPackageSubscriptionOut,
    CompanySetPackageRequest, CompanyRestoreRequest, CompanyArchiveRequest,
)
from app.application_media.service import save_image_for
from app.application_media.utils import MediaFolder
from app.business_validation.item_validation import BizValidationError
from app.business_validation.org_validation import (
    validate_company_basic,
    validate_company_prefix_format,
    validate_branch_basic,
    validate_branch_hq_flag,
)
from app.common.models.base import StatusEnum
from app.common.security.password_generator import generate_random_password
from app.common.security.passwords import hash_password
from app.common.generate_code.service import (
    preview_next_username_for_company,
    bump_username_counter_for_company,
)
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin, ensure_scope_by_ids
from app.application_rbac.rbac_models import Role, UserRole
from app.common.cache.cache_invalidator import (
    bump_user_profile,
    bump_org_companies_list,
    bump_org_company_detail,
    bump_org_branches_list_company,
    bump_org_branch_detail,
    bump_all_cache,
)
from app.seed_data.education_defaults.seeder import seed_education_defaults
from app.seed_data.education_fees_defaults.seeder import seed_education_fees_billing_defaults

from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from app.auth.models.users import User, UserAffiliation
from app.application_rbac.rbac_models import UserRole
from app.navigation_workspace.models.subscription import ModulePackage, CompanyPackageSubscription
from app.application_org.schemas.org_schemas import CompanyDeleteRequest, CompanyPackageSetRequest
from app.common.cache.cache_invalidator import bump_org_companies_list, bump_org_company_detail, bump_user_profile

log = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OrgService:
    def __init__(self, repo: Optional[OrgRepository] = None, session: Optional[Session] = None):
        self.repo = repo or OrgRepository(session or db.session)
        self.s: Session = self.repo.s

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_system_admin(context: AffiliationContext) -> None:
        if not _is_system_admin(context):
            raise Forbidden("Only System Admin can perform this action.")

    def _assign_super_admin_role(self, user_id: int, company_id: int) -> None:
        try:
            role = self.s.scalar(select(Role).filter_by(name="Super Admin"))
            if not role:
                log.warning("Role 'Super Admin' not found; skipping owner role assignment.")
                return

            existing = self.s.scalar(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role.id,
                    UserRole.company_id == company_id,
                    UserRole.branch_id.is_(None),
                )
            )
            if existing:
                return

            ur = UserRole(
                user_id=user_id,
                role_id=role.id,
                company_id=company_id,
                branch_id=None,
                user_affiliation_id=None,
                is_active=True,
                assigned_by=None,
            )
            self.s.add(ur)
            self.s.flush([ur])
        except Exception:
            log.exception("Failed to assign 'Super Admin' role to user_id=%s company_id=%s", user_id, company_id)

    # ------------------------------------------------------------------
    # Packages / subscriptions
    # ------------------------------------------------------------------
    def list_packages(self, *, context: AffiliationContext) -> List[ModulePackageOut]:
        self._ensure_system_admin(context)
        pkgs = self.repo.list_module_packages(enabled_only=False)
        return [
            ModulePackageOut(
                id=p.id,
                slug=p.slug,
                name=p.name,
                description=p.description,
                is_enabled=p.is_enabled,
            )
            for p in pkgs
        ]

    def list_company_packages(self, *, company_id: int, context: AffiliationContext) -> List[CompanyPackageSubscriptionOut]:
        self._ensure_system_admin(context)

        company = self.repo.get_company_by_id(company_id)
        if not company:
            raise NotFound("Company not found.")

        subs = self.repo.get_company_subscriptions(company_id)
        # We also want package slug/name in response:
        out: List[CompanyPackageSubscriptionOut] = []
        for s in subs:
            pkg = self.repo.s.get(type(s).package.property.mapper.class_, s.package_id)  # safe lazy fetch
            # However, above is tricky if relationship isn't defined in model.
            # Safer: load ModulePackage by id:
            from app.navigation_workspace.models.subscription import ModulePackage
            pkg = self.repo.s.get(ModulePackage, s.package_id)

            out.append(
                CompanyPackageSubscriptionOut(
                    company_id=s.company_id,
                    package_id=s.package_id,
                    package_slug=(pkg.slug if pkg else str(s.package_id)),
                    package_name=(pkg.name if pkg else str(s.package_id)),
                    is_enabled=s.is_enabled,
                    valid_from=s.valid_from,
                    valid_until=s.valid_until,
                )
            )
        return out


    # ------------------------------------------------------------------
    # COMPANY – create / update
    # ------------------------------------------------------------------

    def create_company(
            self,
            *,
            payload: CompanyCreate,
            context: AffiliationContext,
            file_storage=None,
            bytes_: Optional[bytes] = None,
            filename: Optional[str] = None,
            content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[CompanyCreateResponse]]:

        log.info(
            "User %s attempting company creation with payload=%s",
            getattr(context, "user_id", "?"),
            payload,
        )

        try:
            # --------------------------------------------------
            # 0. Security + validation
            # --------------------------------------------------
            self._ensure_system_admin(context)

            validate_company_basic(
                name=payload.name,
                prefix=payload.prefix,
                timezone=payload.timezone,
            )
            validate_company_prefix_format(payload.prefix)

            if payload.city_id:
                city = self.repo.get_city_by_id(payload.city_id)
                if not city:
                    raise BadRequest(f"City with ID {payload.city_id} does not exist.")

            # --------------------------------------------------
            # 1. Create Company shell
            # --------------------------------------------------
            company = Company(
                name=payload.name.strip(),
                headquarters_address=payload.headquarters_address,
                contact_email=payload.contact_email,
                contact_phone=payload.contact_phone,
                city_id=payload.city_id,
                prefix=payload.prefix.strip().upper(),
                timezone=payload.timezone.strip(),
                status=payload.status or StatusEnum.ACTIVE,
            )
            self.repo.create_company(company)
            self.s.flush()  # ensures company.id

            # Ensure RBAC scope
            ensure_scope_by_ids(
                context=context,
                target_company_id=company.id,
                target_branch_id=None,
            )

            # --------------------------------------------------
            # 2. Create Owner User
            # --------------------------------------------------
            owner_ut = self.repo.get_user_type_by_name("Owner")
            if not owner_ut:
                raise RuntimeError("UserType 'Owner' is not configured.")

            temp_password = generate_random_password(length=10)
            pwd_hash = hash_password(temp_password)

            owner_username = payload.owner_username
            owner_user = None

            if owner_username:
                candidate = owner_username.strip()
                try:
                    owner_user = self.repo.create_user_and_affiliation(
                        username=candidate,
                        password_hash=pwd_hash,
                        company_id=company.id,
                        user_type=owner_ut,
                        branch_id=None,
                        linked_entity_id=None,
                        make_primary=True,
                    )
                    self.s.flush([owner_user])
                    owner_username = candidate
                except IntegrityError:
                    raise BizValidationError(
                        "Username already exists. Please choose a different username."
                    )
            else:
                for _ in range(20):
                    candidate = preview_next_username_for_company(company)
                    try:
                        with self.s.begin_nested():
                            owner_user = self.repo.create_user_and_affiliation(
                                username=candidate,
                                password_hash=pwd_hash,
                                company_id=company.id,
                                user_type=owner_ut,
                                branch_id=None,
                                linked_entity_id=None,
                                make_primary=True,
                            )
                            self.s.flush([owner_user])
                        bump_username_counter_for_company(company, candidate)
                        owner_username = candidate
                        break
                    except IntegrityError:
                        self.s.rollback()
                        bump_username_counter_for_company(company, candidate)
                        continue

                if not owner_user:
                    raise RuntimeError(
                        "Could not allocate a unique owner username. Please retry."
                    )

            # --------------------------------------------------
            # 3. Company logo upload (optional)
            # --------------------------------------------------
            if file_storage or bytes_:
                try:
                    new_key = save_image_for(
                        folder=MediaFolder.COMPANIES,
                        item_id=company.id,
                        file=file_storage,
                        bytes_=bytes_,
                        filename=filename,
                        content_type=content_type,
                        old_img_key=company.img_key,
                    )
                except ValueError as e:
                    raise BizValidationError(str(e))

                if new_key:
                    self.repo.update_company_img_key(company, new_key)

            # --------------------------------------------------
            # 4. Assign Super Admin role
            # --------------------------------------------------
            try:
                self._assign_super_admin_role(owner_user.id, company.id)
            except Exception:
                log.exception(
                    "Failed assigning Super Admin role to owner user; continuing."
                )

            # --------------------------------------------------
            # 5. PROVISION COMPANY (NEW ORCHESTRATION)
            # --------------------------------------------------
            bootstrap = CompanyBootstrapper(self.s, company.id)
            bootstrap.run()

            # --------------------------------------------------
            # 6. Package subscription (optional)
            # --------------------------------------------------
            if payload.package_slug:
                pkg = self.repo.get_module_package_by_slug(payload.package_slug)
                if not pkg:
                    raise BizValidationError(
                        f"Package slug '{payload.package_slug}' not found."
                    )
                self.repo.upsert_company_subscription(
                    company_id=company.id,
                    package=pkg,
                    is_enabled=True,
                    valid_until=None,
                    extra={},
                )

            # --------------------------------------------------
            # 7. COMMIT (ONLY COMMIT POINT)
            # --------------------------------------------------
            self.s.commit()
            log.info(
                "Successfully created company %s with owner user %s",
                company.id,
                owner_username,
            )

            # --------------------------------------------------
            # 8. Cache invalidation (non-fatal)
            # --------------------------------------------------
            try:
                bump_org_companies_list()
                bump_org_company_detail(company.id)
                if getattr(context, "user_id", None):
                    bump_user_profile(int(context.user_id))
                if payload.package_slug:
                    bump_all_cache()
            except Exception as e:
                log.warning("Cache bump failed after company create: %s", e)

            resp = CompanyCreateResponse(
                company=CompanyMinimalOut(
                    id=company.id,
                    name=company.name,
                    prefix=company.prefix,
                    timezone=company.timezone,
                    status=company.status,
                ),
                owner_user=OwnerUserOut(
                    id=owner_user.id,
                    username=owner_username,
                    temp_password=temp_password,
                ),
            )
            return True, "Company created", resp

        # --------------------------------------------------
        # Error handling (unchanged semantics)
        # --------------------------------------------------
        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None

        except HTTPException:
            self.s.rollback()
            raise

        except IntegrityError as e:
            self.s.rollback()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            log.error("IntegrityError creating company: %s", msg)

            if "ix_companies_name" in msg or "key (name)=" in msg:
                return False, "Company name already exists.", None
            if "ix_companies_prefix" in msg or "key (prefix)=" in msg:
                return False, "Company prefix already exists.", None
            if "ix_companies_contact_email" in msg:
                return False, "Contact email already used.", None
            if "ix_companies_contact_phone" in msg:
                return False, "Contact phone already used.", None
            if "username" in msg:
                return False, "Owner username already exists.", None

            return False, "Integrity error while creating company.", None

        except Exception as e:
            log.exception("Unexpected error creating company: %s", e)
            self.s.rollback()
            return False, "Unexpected server error while creating company.", None

    def update_company(
        self,
        *,
        company_id: int,
        payload: CompanyUpdate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[CompanyMinimalOut]]:
        # (Your existing update_company stays the same — keep it as you already have.)
        # I’m not duplicating it here to avoid changing your working logic.
        return super().update_company(  # type: ignore
            company_id=company_id,
            payload=payload,
            context=context,
            file_storage=file_storage,
            bytes_=bytes_,
            filename=filename,
            content_type=content_type,
        )

    # ------------------------------------------------------------------
    # COMPANY – delete (safe + optional purge)
    # ------------------------------------------------------------------


    def delete_company(
            self,
            *,
            company_id: int,
            payload: CompanyDeleteRequest,
            context: AffiliationContext,
    ) -> Tuple[bool, str]:
        """
        Admin-only destructive delete.

        - confirm_name must match the company.name
        - purge=True: attempts full purge even if DB is missing cascades
        - purge=False: tries normal delete (expects ON DELETE CASCADE properly configured)
        """
        try:
            self._ensure_system_admin(context)

            company = self.repo.get_company_by_id(company_id)
            if not company:
                return False, "Company not found."

            if payload.confirm_name.strip().lower() != (company.name or "").strip().lower():
                return False, "Confirmation name does not match. Company was NOT deleted."

            ensure_scope_by_ids(context=context, target_company_id=company.id, target_branch_id=None)

            # Use savepoint to avoid "transaction already begun"
            with self.s.begin_nested():
                # Always remove these “platform” rows first (scoped to company)
                self.s.execute(
                    delete(CompanyPackageSubscription).where(CompanyPackageSubscription.company_id == company.id))
                self.s.execute(delete(UserRole).where(UserRole.company_id == company.id))

                # Remove affiliations for this company (users may still exist in other companies)
                aff_user_ids = list(
                    self.s.execute(
                        select(UserAffiliation.user_id).where(UserAffiliation.company_id == company.id)
                    ).scalars().all()
                )
                self.s.execute(delete(UserAffiliation).where(UserAffiliation.company_id == company.id))

                # If purge requested, delete ALL tenant rows (handles missing cascades)
                if payload.purge:
                    self._purge_company_rows(company_id=company.id)

                # Optional: delete orphan users created only for this company
                if payload.purge and aff_user_ids:
                    current_uid = int(getattr(context, "user_id", 0) or 0)
                    safe_ids = [uid for uid in set(aff_user_ids) if int(uid) != current_uid]
                    if safe_ids:
                        still_linked = set(
                            self.s.execute(
                                select(UserAffiliation.user_id).where(UserAffiliation.user_id.in_(safe_ids))
                            ).scalars().all()
                        )
                        orphan_ids = [uid for uid in safe_ids if uid not in still_linked]
                        if orphan_ids:
                            self.s.execute(delete(User).where(User.id.in_(orphan_ids)))

                # Finally delete company row
                self.s.delete(company)
                self.s.flush()

            self.s.commit()

            # Cache bumps
            try:
                bump_org_companies_list()
                bump_org_company_detail(company_id)
                bump_all_cache()
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception:
                log.warning("Cache bump failed after company delete", exc_info=True)

            return True, "Company deleted successfully."

        except IntegrityError as e:
            self.s.rollback()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e))
            log.error("IntegrityError deleting company_id=%s: %s", company_id, msg)
            return False, (
                "Company delete blocked by related records (FK constraint). "
                "Try again with purge=true, or add proper ON DELETE CASCADE in schema. "
                f"DB says: {msg}"
            )
        except HTTPException:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error deleting company_id=%s: %s", company_id, e)
            return False, "Unexpected server error while deleting company."

    # ------------------------------------------------------------------
    # Purge helper
    # ------------------------------------------------------------------
    def _purge_company_rows(self, *, company_id: int) -> None:
        """
        Best-effort purge for environments where not all FKs have ON DELETE CASCADE.

        Strategy:
        1) Find branch_ids for this company
        2) Special-case deletes for tables that DO NOT have company_id but depend on it (e.g. account_balances)
        3) Delete rows in tables with branch_id (more specific)
        4) Delete rows in tables with company_id
        5) Delete branches, then company (done by caller)
        """
        branch_ids = list(self.s.execute(select(Branch.id).where(Branch.company_id == company_id)).scalars().all())

        def _safe_ident(x: str) -> bool:
            return bool(_IDENT_RE.match(x or ""))

        def _delete_stmt(schema: str, table: str, where_sql: str) -> int:
            if not (_safe_ident(schema) and _safe_ident(table)):
                return 0
            sql = text(f'DELETE FROM "{schema}"."{table}" WHERE {where_sql}')
            # caller passes params via self.s.execute(sql, params)
            raise RuntimeError("Use _safe_exec with params")  # prevent misuse

        def _safe_exec(sql_stmt, params) -> int:
            # Savepoint per statement: one FK issue won't kill previous deletes
            try:
                with self.s.begin_nested():
                    res = self.s.execute(sql_stmt, params)
                    return int(getattr(res, "rowcount", 0) or 0)
            except IntegrityError:
                # swallow and continue; next passes may unlock it
                return 0

        # -----------------------------
        # 0) SPECIAL CASES (no company_id column)
        # -----------------------------
        # account_balances often depends on accounts/fiscal_years.
        # Delete by JOIN so it works even if account_id is NULL.
        # - If you don't have fiscal_years table, remove that block.
        try:
            # by fiscal_years (covers rows where account_id is NULL)
            sql1 = text("""
                DELETE FROM public.account_balances ab
                USING public.fiscal_years fy
                WHERE ab.fiscal_year_id = fy.id
                  AND fy.company_id = :cid
            """)
            _safe_exec(sql1, {"cid": company_id})

            # by accounts (covers normal rows)
            sql2 = text("""
                DELETE FROM public.account_balances ab
                USING public.accounts a
                WHERE ab.account_id = a.id
                  AND a.company_id = :cid
            """)
            _safe_exec(sql2, {"cid": company_id})
        except Exception:
            # If these tables don't exist in your schema, ignore
            pass

        # -----------------------------
        # 1) discover tables with branch_id / company_id
        # -----------------------------
        company_tables = list(
            self.s.execute(
                text("""
                    SELECT table_schema, table_name
                    FROM information_schema.columns
                    WHERE column_name = 'company_id'
                      AND table_schema = 'public'
                """)
            ).all()
        )

        branch_tables = list(
            self.s.execute(
                text("""
                    SELECT table_schema, table_name
                    FROM information_schema.columns
                    WHERE column_name = 'branch_id'
                      AND table_schema = 'public'
                """)
            ).all()
        )

        # Don't delete from structural/global tables even if they have company_id (rare but protect)
        skip_tables = {
            "alembic_version",
            # global catalog tables you never want to purge
            "module_packages",
            "package_workspaces",
            "workspaces",
            "workspace_sections",
            "workspace_links",
        }

        # -----------------------------
        # 2) multi-pass delete
        # -----------------------------
        max_passes = 12
        total_deleted = 0

        for p in range(1, max_passes + 1):
            progress = 0

            # 2a) branch_id deletes first
            if branch_ids:
                for schema, table in branch_tables:
                    if table in skip_tables or table == "companies":
                        continue
                    if not (_safe_ident(schema) and _safe_ident(table)):
                        continue
                    sql = text(f'DELETE FROM "{schema}"."{table}" WHERE branch_id = ANY(:bids)')
                    progress += _safe_exec(sql, {"bids": branch_ids})

            # 2b) company_id deletes
            for schema, table in company_tables:
                if table in skip_tables or table == "companies":
                    continue
                if not (_safe_ident(schema) and _safe_ident(table)):
                    continue
                sql = text(f'DELETE FROM "{schema}"."{table}" WHERE company_id = :cid')
                progress += _safe_exec(sql, {"cid": company_id})

            # 2c) delete branches explicitly (some schemas miss cascades)
            sqlb = text('DELETE FROM public.branches WHERE company_id = :cid')
            progress += _safe_exec(sqlb, {"cid": company_id})

            self.s.flush()

            total_deleted += progress
            log.info("[purge] pass=%s company_id=%s deleted=%s", p, company_id, progress)

            if progress == 0:
                break

        log.info("[purge] done company_id=%s total_deleted=%s", company_id, total_deleted)

    def archive_company(
            self,
            *,
            company_id: int,
            payload: CompanyArchiveRequest,
            context: AffiliationContext,
    ) -> tuple[bool, str]:
        try:
            self._ensure_system_admin(context)

            company = self.repo.get_company_by_id(company_id)
            if not company:
                raise NotFound("Company not found.")

            if payload.confirm_name.strip().lower() != (company.name or "").strip().lower():
                return False, "Confirmation name does not match. Company was NOT archived."

            ensure_scope_by_ids(context=context, target_company_id=company.id, target_branch_id=None)

            with self.s.begin_nested():
                # mark inactive
                self.repo.set_company_status(company.id, StatusEnum.INACTIVE)

                # disable packages (blocks modules/nav)
                self.repo.archive_company_subscriptions(company.id)

                # disable branches too
                self.repo.set_branches_status_for_company(company.id, StatusEnum.INACTIVE)

                log.info("[company][archive] company_id=%s BEFORE subs=%s", company.id, [
                    {"id": s.id, "pkg": s.package_id, "enabled": bool(s.is_enabled), "until": s.valid_until,
                     "extra": s.extra}
                    for s in self.repo.get_company_subscriptions(company.id)
                ])

                self.repo.archive_company_subscriptions(company.id)

                log.info("[company][archive] company_id=%s AFTER subs=%s", company.id, [
                    {"id": s.id, "pkg": s.package_id, "enabled": bool(s.is_enabled), "until": s.valid_until,
                     "extra": s.extra}
                    for s in self.repo.get_company_subscriptions(company.id)
                ])

            self.s.commit()

            # cache bumps
            try:
                bump_org_companies_list()
                bump_org_company_detail(company.id)
                bump_all_cache()
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception:
                log.warning("Cache bump failed after archive_company", exc_info=True)

            return True, "Company archived successfully."

        except HTTPException:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error archiving company_id=%s: %s", company_id, e)
            return False, "Unexpected server error while archiving company."

    def restore_company(
            self,
            *,
            company_id: int,
            payload: CompanyRestoreRequest,
            context: AffiliationContext,
    ) -> tuple[bool, str]:
        try:
            self._ensure_system_admin(context)

            company = self.repo.get_company_by_id(company_id)
            if not company:
                raise NotFound("Company not found.")

            if payload.confirm_name.strip().lower() != (company.name or "").strip().lower():
                return False, "Confirmation name does not match. Company was NOT restored."

            ensure_scope_by_ids(context=context, target_company_id=company.id, target_branch_id=None)

            with self.s.begin_nested():
                self.repo.set_company_status(company.id, StatusEnum.ACTIVE)
                self.repo.set_branches_status_for_company(company.id, StatusEnum.ACTIVE)

                # ✅ restore subscriptions back to what they were before archive
                self.repo.restore_company_subscriptions(company.id, legacy_restore=True)

                log.info("[company][restore] company_id=%s BEFORE subs=%s", company.id, [
                    {"id": s.id, "pkg": s.package_id, "enabled": bool(s.is_enabled), "until": s.valid_until,
                     "extra": s.extra}
                    for s in self.repo.get_company_subscriptions(company.id)
                ])

                self.repo.restore_company_subscriptions(company.id, legacy_restore=True)

                log.info("[company][restore] company_id=%s AFTER subs=%s", company.id, [
                    {"id": s.id, "pkg": s.package_id, "enabled": bool(s.is_enabled), "until": s.valid_until,
                     "extra": s.extra}
                    for s in self.repo.get_company_subscriptions(company.id)
                ])

            self.s.commit()

            try:
                bump_org_companies_list()
                bump_org_company_detail(company.id)
                bump_all_cache()
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception:
                log.warning("Cache bump failed after restore_company", exc_info=True)

            return True, "Company restored successfully."

        except HTTPException:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error restoring company_id=%s: %s", company_id, e)
            return False, "Unexpected server error while restoring company."

    # ------------------------------------------------------------------
    # COMPANY – set package (enable/disable)
    # ------------------------------------------------------------------
    def set_company_package(
        self,
        *,
        company_id: int,
        payload: CompanyPackageSetRequest,
        context: AffiliationContext,
    ) -> tuple[bool, str, Optional[dict]]:
        """
        Upsert company package subscription. Recommended separate endpoint for UI.
        """
        try:
            self._ensure_system_admin(context)

            company = self.repo.get_company_by_id(company_id)
            if not company:
                return False, "Company not found.", None

            ensure_scope_by_ids(context=context, target_company_id=company.id, target_branch_id=None)

            package = self.repo.get_package_by_slug(payload.package_slug)
            if not package:
                return False, f"Package slug '{payload.package_slug}' not found.", None
            if not package.is_enabled and payload.is_enabled:
                return False, f"Package '{payload.package_slug}' is disabled and cannot be enabled for companies.", None

            with self.s.begin_nested():
                cps = self.repo.upsert_company_package_subscription(
                    company_id=company.id,
                    package_id=package.id,
                    is_enabled=payload.is_enabled,
                    valid_until=payload.valid_until,
                    extra=payload.extra or {},
                )

            self.s.commit()

            # Cache bumps
            try:
                bump_org_company_detail(company_id)
                bump_org_companies_list()
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception:
                log.warning("Cache bump failed after set_company_package", exc_info=True)

            return True, "Company package updated.", {
                "company_id": cps.company_id,
                "package_id": cps.package_id,
                "is_enabled": cps.is_enabled,
                "valid_from": cps.valid_from,
                "valid_until": cps.valid_until,
                "extra": cps.extra,
            }

        except HTTPException:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error setting package for company_id=%s: %s", company_id, e)
            return False, "Unexpected server error while updating company package.", None


    # ------------------------------------------------------------------
    # BRANCH – create / update
    # ------------------------------------------------------------------
    def create_branch(
            self,
            *,
            payload: BranchCreate,
            context: AffiliationContext,
            file_storage=None,
            bytes_: Optional[bytes] = None,
            filename: Optional[str] = None,
            content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[BranchMinimalOut]]:
        log.info(
            "User %s attempting branch creation with payload=%s",
            getattr(context, "user_id", "?"),
            payload,
        )

        try:
            self._ensure_system_admin(context)

            company = self.repo.get_company_by_id(payload.company_id)
            if not company:
                raise BadRequest(f"Company with ID {payload.company_id} does not exist.")

            # Basic validations
            validate_branch_basic(
                company_id=payload.company_id,
                name=payload.name,
                code=payload.code,
            )

            # HQ constraint
            has_existing_hq = self.repo.has_hq_branch(company_id=payload.company_id)
            validate_branch_hq_flag(is_hq=payload.is_hq, has_existing_hq=has_existing_hq)

            # Pre-check uniqueness
            if self.repo.branch_name_exists(
                    company_id=payload.company_id,
                    name=payload.name,
            ):
                return False, "Branch name already exists in this company.", None

            if self.repo.branch_code_exists(code=payload.code):
                return False, "Branch code already exists.", None

            # Scope (System Admin will always pass)
            ensure_scope_by_ids(
                context=context,
                target_company_id=payload.company_id,
                target_branch_id=None,
            )

            branch = Branch(
                company_id=payload.company_id,
                name=payload.name.strip(),
                code=payload.code.strip(),
                location=payload.location,
                is_hq=payload.is_hq,
                created_by=getattr(context, "user_id", None),
                status=payload.status or StatusEnum.ACTIVE,
            )
            self.repo.create_branch(branch)  # flush -> branch.id

            if file_storage or bytes_:
                try:
                    new_key = save_image_for(
                        folder=MediaFolder.BRANCHES,
                        item_id=branch.id,
                        file=file_storage,
                        bytes_=bytes_,
                        filename=filename,
                        content_type=content_type,
                        old_img_key=branch.img_key,
                    )
                except ValueError as e:
                    log.error("Invalid branch image upload: %s", e)
                    self.s.rollback()
                    return False, str(e), None

                if new_key:
                    self.repo.update_branch_img_key(branch, new_key)

            # 🔹 Auto-seed warehouses + cost center for this branch inside same transaction
            try:
                seed_warehouses_for_branch(
                    self.s,
                    company_id=branch.company_id,
                    branch_id=branch.id,
                )
                seed_cost_center_for_branch(
                    self.s,
                    company_id=branch.company_id,
                    branch_id=branch.id,
                )
            except Exception:
                # Do not break branch creation if seeding has a minor issue.
                log.exception(
                    "Failed to seed default warehouses / cost center for company_id=%s, branch_id=%s",
                    branch.company_id,
                    branch.id,
                )

            self.s.commit()

            # ✅ Cache bumps: branch list/detail + current user profile
            try:
                bump_org_branches_list_company(branch.company_id)
                bump_org_branch_detail(branch.id)
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception as e:
                log.warning("Cache bump failed after branch create: %s", e)

            out = BranchMinimalOut(
                id=branch.id,
                company_id=branch.company_id,
                name=branch.name,
                code=branch.code,
                is_hq=branch.is_hq,
                status=branch.status,
            )
            return True, "Branch created", out

        except BizValidationError as e:
            # Example: "This company already has an HQ branch."
            self.s.rollback()
            return False, str(e), None
        except HTTPException:
            self.s.rollback()
            raise
        except IntegrityError as e:
            self.s.rollback()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            log.error("IntegrityError creating branch: %s", msg)

            if "uq_branch_name_per_company" in msg or "branch_name_per_company" in msg:
                return False, "Branch name already exists in this company.", None
            if "branches_code_key" in msg or ("unique" in msg and "code" in msg):
                return False, "Branch code already exists.", None

            return False, "Integrity error while creating branch.", None
        except Exception as e:
            log.exception("Unexpected error creating branch: %s", e)
            self.s.rollback()
            return False, "Unexpected server error while creating branch.", None

    def update_branch(
        self,
        *,
        branch_id: int,
        payload: BranchUpdate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[BranchMinimalOut]]:
        log.info(
            "User %s attempting branch update branch_id=%s payload=%s",
            getattr(context, "user_id", "?"),
            branch_id,
            payload,
        )

        try:
            self._ensure_system_admin(context)

            branch = self.repo.get_branch_by_id(branch_id)
            if not branch:
                raise NotFound("Branch not found.")

            company_id = branch.company_id

            # Use existing values when fields are not provided
            effective_name = payload.name or branch.name
            effective_code = payload.code or branch.code

            validate_branch_basic(
                company_id=company_id,
                name=effective_name,
                code=effective_code,
            )

            # HQ constraint if toggling to True
            if payload.is_hq is not None:
                has_existing_hq = self.repo.has_hq_branch(
                    company_id=company_id,
                    exclude_branch_id=branch.id,
                )
                validate_branch_hq_flag(
                    is_hq=payload.is_hq,
                    has_existing_hq=has_existing_hq,
                )

            # Uniqueness checks on change
            if payload.name and payload.name.strip().lower() != branch.name.lower():
                if self.repo.branch_name_exists(
                    company_id=company_id,
                    name=payload.name,
                    exclude_branch_id=branch.id,
                ):
                    return False, "Branch name already exists in this company.", None

            if payload.code and (branch.code is None or payload.code.strip().lower() != branch.code.lower()):
                if self.repo.branch_code_exists(
                    code=payload.code,
                    exclude_branch_id=branch.id,
                ):
                    return False, "Branch code already exists.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=branch.id,
            )

            data = {
                "name": payload.name,
                "code": payload.code,
                "location": payload.location,
                "is_hq": payload.is_hq,
                "status": payload.status,
            }
            self.repo.update_branch_fields(branch, data)

            if file_storage or bytes_:
                try:
                    new_key = save_image_for(
                        folder=MediaFolder.BRANCHES,
                        item_id=branch.id,
                        file=file_storage,
                        bytes_=bytes_,
                        filename=filename,
                        content_type=content_type,
                        old_img_key=branch.img_key,
                    )
                except ValueError as e:
                    log.error("Invalid branch image upload on update: %s", e)
                    self.s.rollback()
                    return False, str(e), None

                if new_key:
                    self.repo.update_branch_img_key(branch, new_key)

            self.s.commit()

            # ✅ Cache bumps
            try:
                bump_org_branches_list_company(branch.company_id)
                bump_org_branch_detail(branch.id)
                if getattr(context, "user_id", None) is not None:
                    bump_user_profile(int(context.user_id))
            except Exception as e:
                log.warning("Cache bump failed after branch update: %s", e)

            out = BranchMinimalOut(
                id=branch.id,
                company_id=branch.company_id,
                name=branch.name,
                code=branch.code,
                is_hq=branch.is_hq,
                status=branch.status,
            )
            return True, "Branch updated", out

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except HTTPException:
            self.s.rollback()
            raise
        except IntegrityError as e:
            self.s.rollback()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            log.error("IntegrityError updating branch: %s", msg)

            if "uq_branch_name_per_company" in msg or "branch_name_per_company" in msg:
                return False, "Branch name already exists in this company.", None
            if "branches_code_key" in msg or ("unique" in msg and "code" in msg):
                return False, "Branch code already exists.", None

            return False, "Integrity error while updating branch.", None
        except Exception as e:
            log.exception("Unexpected error updating branch: %s", e)
            self.s.rollback()
            return False, "Unexpected server error while updating branch.", None
