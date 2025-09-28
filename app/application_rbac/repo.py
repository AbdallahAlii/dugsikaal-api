
from __future__ import annotations
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select, and_, func, delete
from sqlalchemy.orm import joinedload

from config.database import db
from app.application_rbac.rbac_models import PermissionOverride, UserRole, Role, RoleScopeEnum, UserConstraint, \
    Permission
from app.application_org.models.company import Branch
from app.auth.models.users import UserAffiliation


class RbacRepository:
    # ---------- Roles ----------
    def create_role(self, *, name: str, scope, company_id: Optional[int], description: Optional[str]) -> Role:
        r = Role(
            name=name.strip(),
            scope=scope,
            company_id=company_id,
            is_system_defined=False,
            description=description,
        )
        db.session.add(r)
        return r

    # def get_roles_by_ids(self, ids: Sequence[int]) -> List[Role]:
    #     if not ids:
    #         return []
    #     stmt = (
    #         select(Role)
    #         .where(Role.id.in_([int(x) for x in ids]))
    #         .options(joinedload(Role.user_roles))
    #     )
    #     return list(db.session.scalars(stmt).all())
    def get_roles_by_ids(self, role_ids: Sequence[int]) -> List[Role]:
        ids = list({int(x) for x in (role_ids or [])})
        if not ids:
            return []
        stmt = select(Role).where(Role.id.in_(ids))
        return list(db.session.scalars(stmt).all())
    def delete_roles(self, roles: Iterable[Role]) -> int:
        count = 0
        for r in roles:
            db.session.delete(r)
            count += 1
        return count

    # ---------- Users & affiliations ----------
    # def get_user_primary_affiliation(self, user_id: int) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    #     stmt = (
    #         select(UserAffiliation)
    #         .where(UserAffiliation.user_id == int(user_id))
    #         .order_by(UserAffiliation.is_primary.desc(), UserAffiliation.id.asc())
    #         .limit(1)
    #     )
    #     aff = db.session.scalars(stmt).first()
    #     if not aff:
    #         return None, None, None
    #     return aff.company_id, aff.branch_id, aff.id
    def get_user_primary_affiliation(self, user_id: int) -> tuple[Optional[int], Optional[int], Optional[int]]:
        stmt = (
            select(UserAffiliation)
            .where(UserAffiliation.user_id == user_id)
            .order_by(UserAffiliation.is_primary.desc())
            .limit(1)
        )
        aff = db.session.scalar(stmt)
        if not aff:
            return None, None, None
        return aff.company_id, aff.branch_id, aff.id


    def get_user_affiliation_for_anchor(
        self, user_id: int, company_id: Optional[int], branch_id: Optional[int]
    ) -> Optional[UserAffiliation]:
        q = select(UserAffiliation).where(UserAffiliation.user_id == user_id)
        if company_id is not None:
            q = q.where(UserAffiliation.company_id == company_id)
        if branch_id is not None:
            q = q.where(UserAffiliation.branch_id == branch_id)
        affs = list(db.session.scalars(q).all())
        if not affs:
            return None
        primary = next((a for a in affs if bool(getattr(a, "is_primary", False))), None)
        return primary or affs[0]

    def get_active_role_ids_for_user(
            self,
            *,
            user_id: int,
            company_id: Optional[int],
            branch_id: Optional[int],
    ) -> Set[int]:
        stmt = (
            select(UserRole.role_id)
            .where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.is_active.is_(True),
                    (UserRole.company_id.is_(None) if company_id is None else UserRole.company_id == company_id),
                    (UserRole.branch_id.is_(None) if branch_id is None else UserRole.branch_id == branch_id),
                )
            )
        )
        return {int(rid) for (rid,) in db.session.execute(stmt).all()}

    # ---- Assign a role (SET semantics helper) ----
    def assign_user_role(
            self,
            *,
            user_id: int,
            role_id: int,
            company_id: Optional[int],
            branch_id: Optional[int],
            assigned_by: Optional[int],
            user_affiliation_id: Optional[int] = None,
    ) -> UserRole:
        row = UserRole(
            user_id=user_id,
            role_id=role_id,
            company_id=company_id,
            branch_id=branch_id,
            user_affiliation_id=user_affiliation_id,
            is_active=True,
            assigned_by=assigned_by,
        )
        db.session.add(row)
        return row

    # ---- Remove roles for an anchor (hard delete) ----
    def bulk_delete_user_roles(
            self,
            *,
            user_id: int,
            role_ids: Sequence[int],
            company_id: Optional[int],
            branch_id: Optional[int],
    ) -> int:
        ids = list({int(x) for x in (role_ids or [])})
        if not ids:
            return 0
        stmt = (
            delete(UserRole)
            .where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.role_id.in_(ids),
                    (UserRole.company_id.is_(None) if company_id is None else UserRole.company_id == company_id),
                    (UserRole.branch_id.is_(None) if branch_id is None else UserRole.branch_id == branch_id),
                )
            )
        )
        res = db.session.execute(stmt)
        return int(res.rowcount or 0)

    # ---------- Permissions / Overrides ----------
    def get_permission_by_id(self, permission_id: int) -> Optional[Permission]:
        return db.session.get(Permission, permission_id)

    def upsert_permission_override(
        self, *, user_id: int, permission_id: int, is_allowed: bool, reason: Optional[str],
        company_id: Optional[int], branch_id: Optional[int], granted_by: Optional[int]
    ) -> PermissionOverride:
        q = select(PermissionOverride).where(
            and_(
                PermissionOverride.user_id == user_id,
                PermissionOverride.permission_id == permission_id,
                (PermissionOverride.company_id.is_(None) if company_id is None else PermissionOverride.company_id == company_id),
                (PermissionOverride.branch_id.is_(None)  if branch_id is None  else PermissionOverride.branch_id == branch_id),
            )
        )
        row = db.session.scalar(q)
        if row:
            row.is_allowed = is_allowed
            row.reason = reason
            row.granted_by = granted_by
            db.session.add(row)
            return row
        row = PermissionOverride(
            user_id=user_id,
            permission_id=permission_id,
            is_allowed=is_allowed,
            reason=reason,
            company_id=company_id,
            branch_id=branch_id,
            granted_by=granted_by,
        )
        db.session.add(row)
        return row

    def delete_permission_override(
        self, *, user_id: int, permission_id: int,
        company_id: Optional[int], branch_id: Optional[int]
    ) -> int:
        q = select(PermissionOverride).where(
            and_(
                PermissionOverride.user_id == user_id,
                PermissionOverride.permission_id == permission_id,
                (PermissionOverride.company_id.is_(None) if company_id is None else PermissionOverride.company_id == company_id),
                (PermissionOverride.branch_id.is_(None)  if branch_id is None  else PermissionOverride.branch_id == branch_id),
            )
        )
        rows = list(db.session.scalars(q).all())
        for r in rows:
            db.session.delete(r)
        return len(rows)

    # ---------- User constraints ----------
    def create_user_constraint(
        self, *, user_id: int, doctype_id: int, field_name: str,
        ref_doctype_id: int, ref_id: int, allow_children: bool
    ) -> UserConstraint:
        uc = UserConstraint(
            user_id=user_id,
            doctype_id=doctype_id,
            field_name=field_name.strip(),
            ref_doctype_id=ref_doctype_id,
            ref_id=ref_id,
            allow_children=allow_children,
        )
        db.session.add(uc)
        return uc

    def delete_user_constraint(
        self, *, user_id: int, doctype_id: int, field_name: str,
        ref_doctype_id: int, ref_id: int
    ) -> int:
        q = select(UserConstraint).where(
            and_(
                UserConstraint.user_id == user_id,
                UserConstraint.doctype_id == doctype_id,
                func.lower(UserConstraint.field_name) == func.lower(field_name),
                UserConstraint.ref_doctype_id == ref_doctype_id,
                UserConstraint.ref_id == ref_id,
            )
        )
        rows = list(db.session.scalars(q).all())
        for r in rows:
            db.session.delete(r)
        return len(rows)
