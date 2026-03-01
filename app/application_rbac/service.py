from __future__ import annotations
import logging
from typing import List, Optional, Sequence, Set, Tuple, Dict

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from app.application_rbac.rbac_models import Role, RoleScopeEnum, Permission
from app.security.rbac_guards import ensure_scope_by_ids
from config.database import db

from app.application_rbac.repo import RbacRepository
from app.common.cache.invalidation import bump_user_profile
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


class RbacService:
    def __init__(self, repo: Optional[RbacRepository] = None):
        self.repo = repo or RbacRepository()

    # ---------- Roles ----------

    def create_role(
        self, *,
        name: str,
        scope: str,
        description: Optional[str],
        company_id: Optional[int],
        context: AffiliationContext,
    ) -> Role:
        scope_enum = RoleScopeEnum(scope.upper())
        if scope_enum == RoleScopeEnum.SYSTEM:
            raise Forbidden("Creating SYSTEM-scoped roles is not allowed.")

        # default to caller’s primary company if not provided
        if company_id is None:
            company_id = context.company_id

        if company_id is None:
            raise BadRequest("company_id is required (payload or your primary affiliation).")

        try:
            role = self.repo.create_role(
                name=name, scope=scope_enum, company_id=company_id, description=description
            )
            db.session.commit()
            return role
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error creating role: %s", e, exc_info=True)
            raise BadRequest("Failed to create role.")

    def delete_roles_bulk(self, *, role_ids: Sequence[int], context: AffiliationContext) -> None:
        # normalize and validate input
        ids = sorted({int(rid) for rid in role_ids if rid is not None})
        if not ids:
            raise BadRequest("No role IDs provided.")

        # fetch and detect missing IDs (generic message; don’t leak specific IDs)
        roles: List[Role] = self.repo.get_roles_by_ids(ids)
        found_ids = {int(r.id) for r in roles}
        if any(rid not in found_ids for rid in ids):
            raise NotFound("One or more selected roles do not exist.")

        # partition
        system_defined = [r for r in roles if bool(getattr(r, "is_system_defined", False))]
        other_company = [
            r for r in roles
            if not bool(getattr(r, "is_system_defined", False))
               and getattr(r, "company_id", None) is not None
               and r.company_id != context.company_id
        ]

        # prioritized, single-message failures
        if system_defined:
            raise Forbidden("Cannot delete predefined roles.")
        if other_company:
            raise Forbidden("Cannot delete roles belonging to another company.")

        # allowed => your-company custom roles only
        allowed = [
            r for r in roles
            if not bool(getattr(r, "is_system_defined", False))
               and getattr(r, "company_id", None) == context.company_id
        ]

        if not allowed:
            raise Forbidden("No deletable roles found.")

        try:
            self.repo.delete_roles(allowed)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error bulk delete roles: %s", e, exc_info=True)
            raise BadRequest("Failed to delete roles.")

     # ---------- Set user roles (assign/unassign) ----------


    def set_user_roles_for_user(
            self,
            *,
            target_user_id: int,
            role_ids: Sequence[int],
            context: AffiliationContext,
    ) -> None:
        ids = sorted({int(x) for x in (role_ids or [])})
        if not ids:
            raise BadRequest("No roles selected.")

        roles: List[Role] = self.repo.get_roles_by_ids(ids)
        found = {int(r.id) for r in roles}
        if len(found) != len(ids):
            raise NotFound("Some roles were not found.")

        # Get the target user's primary affiliation info ONCE
        tgt_company, tgt_branch, tgt_aff_id = self.repo.get_user_primary_affiliation(target_user_id)
        if tgt_company is None:
            raise BadRequest("Target user does not have a primary affiliation.")

        # Policy: allow predefined globally; custom only if they belong to caller's company
        bad_custom = [r for r in roles if (not r.is_system_defined) and (r.company_id != context.company_id)]
        if bad_custom:
            raise Forbidden("Only predefined or your-company roles.")

        # Partition roles based on type
        predefined_ids: Set[int] = {int(r.id) for r in roles if r.is_system_defined}
        custom_ids: Set[int] = {int(r.id) for r in roles if not r.is_system_defined}

        try:
            # --- SET for predefined (global) ---
            cur_pre = self.repo.get_active_role_ids_for_user(
                user_id=target_user_id, company_id=None, branch_id=None
            )
            add_pre = sorted(list(predefined_ids - cur_pre))
            del_pre = sorted(list(cur_pre - predefined_ids))

            for rid in add_pre:
                self.repo.assign_user_role(
                    user_id=target_user_id,
                    role_id=rid,
                    # NOW passing the target user's affiliation details for ALL roles
                    company_id=tgt_company,
                    branch_id=tgt_branch,
                    assigned_by=context.user_id,
                    user_affiliation_id=tgt_aff_id,
                )
            if del_pre:
                self.repo.bulk_delete_user_roles(
                    user_id=target_user_id,
                    role_ids=del_pre,
                    company_id=tgt_company,
                    branch_id=tgt_branch,
                )

            # --- SET for custom (company anchor) ---
            if custom_ids:
                if context.company_id is None:
                    raise Forbidden("Only predefined or your-company roles.")

                # Note: `cur_cust` query needs to be updated to match the company_id and branch_id
                # that you will be using for custom role assignments.
                cur_cust = self.repo.get_active_role_ids_for_user(
                    user_id=target_user_id, company_id=context.company_id, branch_id=None
                )
                add_cust = sorted(list(custom_ids - cur_cust))
                del_cust = sorted(list(cur_cust - custom_ids))

                for rid in add_cust:
                    self.repo.assign_user_role(
                        user_id=target_user_id,
                        role_id=rid,
                        company_id=context.company_id,
                        branch_id=tgt_branch,  # Using the target user's branch
                        assigned_by=context.user_id,
                        user_affiliation_id=tgt_aff_id,
                    )
                if del_cust:
                    self.repo.bulk_delete_user_roles(
                        user_id=target_user_id,
                        role_ids=del_cust,
                        company_id=context.company_id,
                        branch_id=tgt_branch,  # Using the target user's branch
                    )

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error setting roles for user %s: %s", target_user_id, e, exc_info=True)
            raise BadRequest("Failed to update roles.")

        try:
            bump_user_profile(target_user_id)
        except Exception:
            log.exception("bump_user_profile failed after role change for user_id=%s", target_user_id)
    # ---------- Permission overrides (no scope checks) ----------
    # Allowed if permission is global (company_id NULL) or belongs to actor's company.

    def upsert_override(
        self, *,
        target_user_id: int,
        permission_id: int,
        is_allowed: bool,
        reason: Optional[str],
        company_id: Optional[int],
        branch_id: Optional[int],
        context: AffiliationContext,
    ) -> None:
        perm: Optional[Permission] = self.repo.get_permission_by_id(permission_id)
        if not perm:
            raise NotFound("Permission not found.")

        actor_company = context.company_id
        if perm.company_id is not None and perm.company_id != actor_company:
            raise Forbidden("You can only override permissions for your company.")

        # resolve anchors (optional), default to actor → target
        tgt_company, tgt_branch, _ = self.repo.get_user_primary_affiliation(target_user_id)
        anchor_company = company_id or actor_company or tgt_company
        anchor_branch  = branch_id or context.branch_id or (tgt_branch if (tgt_company == anchor_company) else None)

        try:
            self.repo.upsert_permission_override(
                user_id=target_user_id,
                permission_id=permission_id,
                is_allowed=is_allowed,
                reason=reason,
                company_id=anchor_company,
                branch_id=anchor_branch,
                granted_by=context.user_id,
            )
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error upserting permission override: %s", e, exc_info=True)
            raise BadRequest("Failed to upsert permission override.")

        try:
            bump_user_profile(target_user_id)
        except Exception:
            log.exception("bump_user_profile failed after override for user_id=%s", target_user_id)

    def delete_override(
        self, *,
        target_user_id: int,
        permission_id: int,
        company_id: Optional[int],
        branch_id: Optional[int],
        context: AffiliationContext,
    ) -> None:
        # we don't need the Permission row to delete; anchors still auto-resolve
        tgt_company, tgt_branch, _ = self.repo.get_user_primary_affiliation(target_user_id)
        anchor_company = company_id or context.company_id or tgt_company
        anchor_branch  = branch_id or context.branch_id or (tgt_branch if (tgt_company == anchor_company) else None)

        try:
            self.repo.delete_permission_override(
                user_id=target_user_id,
                permission_id=permission_id,
                company_id=anchor_company,
                branch_id=anchor_branch,
            )
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error deleting permission override: %s", e, exc_info=True)
            raise BadRequest("Failed to delete permission override.")

        try:
            bump_user_profile(target_user_id)
        except Exception:
            log.exception("bump_user_profile failed after override delete for user_id=%s", target_user_id)

    # ---------- User constraints ----------
    def create_user_constraint(
        self, *,
        target_user_id: int,
        doctype_id: int,
        field_name: str,
        ref_doctype_id: int,
        ref_id: int,
        allow_children: bool,
        context: AffiliationContext,
    ) -> None:
        try:
            self.repo.create_user_constraint(
                user_id=target_user_id,
                doctype_id=doctype_id,
                field_name=field_name,
                ref_doctype_id=ref_doctype_id,
                ref_id=ref_id,
                allow_children=allow_children,
            )
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error creating user constraint: %s", e, exc_info=True)
            raise BadRequest("Failed to create user constraint.")

        try:
            bump_user_profile(target_user_id)
        except Exception:
            log.exception("bump_user_profile failed after constraint create for user_id=%s", target_user_id)

    def delete_user_constraint(
        self, *,
        target_user_id: int,
        doctype_id: int,
        field_name: str,
        ref_doctype_id: int,
        ref_id: int,
        context: AffiliationContext,
    ) -> None:
        try:
            self.repo.delete_user_constraint(
                user_id=target_user_id,
                doctype_id=doctype_id,
                field_name=field_name,
                ref_doctype_id=ref_doctype_id,
                ref_id=ref_id,
            )
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error deleting user constraint: %s", e, exc_info=True)
            raise BadRequest("Failed to delete user constraint.")

        try:
            bump_user_profile(target_user_id)
        except Exception:
            log.exception("bump_user_profile failed after constraint delete for user_id=%s", target_user_id)
