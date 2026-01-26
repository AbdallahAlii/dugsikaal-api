from __future__ import annotations
from typing import List, Dict, Optional
from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload

from config.database import db
from app.application_rbac.rbac_models import (
    Role, RoleScopeEnum,
    Permission, RolePermission,
    DocType as RBACDocType,
    Action,
)
from app.application_meta.schemas import DocPermissionOut


class PermissionMatrixService:
    """
    Builds a Frappe-style permission grid per DocType using the real RBAC engine.
    Output: list[DocPermissionOut]
    """

    def get_role_matrix_for_doctype(
        self,
        *,
        doctype_name: str,
        company_id: Optional[int],
    ) -> List[DocPermissionOut]:
        session = db.session

        # 1) Resolve RBAC DocType
        dt = session.execute(
            select(RBACDocType).where(RBACDocType.name == doctype_name)
        ).scalar_one_or_none()
        if not dt:
            return []

        # 2) Load all roles that matter for this company:
        #    - SYSTEM roles (scope=SYSTEM)
        #    - Company roles (scope=COMPANY, company_id=this company)
        #    - Branch roles also rely on same permissions, but the scope
        #      is enforced elsewhere by your ensure_scope_by_ids.
        roles_q = select(Role).where(
            or_(
                Role.scope == RoleScopeEnum.SYSTEM,
                Role.company_id == company_id,
            )
        )
        roles = session.execute(roles_q).scalars().all()
        if not roles:
            return []

        # 3) For these roles, load RolePermission + Permission + Action for this DocType
        rp_q = (
            select(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .join(Action, Action.id == Permission.action_id)
            .join(RBACDocType, RBACDocType.id == Permission.doctype_id)
            .options(
                joinedload(RolePermission.role),
                joinedload(RolePermission.permission)
                    .joinedload(Permission.action),
                joinedload(RolePermission.permission)
                    .joinedload(Permission.doctype),
            )
            .where(
                RBACDocType.id == dt.id,
                RolePermission.is_allowed.is_(True),
                or_(
                    RolePermission.company_id.is_(None),
                    RolePermission.company_id == company_id,
                )
            )
        )

        role_perms = db.session.scalars(rp_q).all()

        # 4) Build a matrix like:
        #    { role_name: { "READ": True, "CREATE": True, ... } }
        matrix: Dict[str, Dict[str, bool]] = {}

        for rp in role_perms:
            r = rp.role
            p = rp.permission
            if not r or not p or not p.action:
                continue

            role_name = r.name
            action_name = (p.action.name or "").upper()

            if role_name not in matrix:
                matrix[role_name] = {}

            # mark this specific action as allowed
            matrix[role_name][action_name] = True

        # 5) Map action flags -> DocPermissionOut booleans
        result: List[DocPermissionOut] = []

        for role_name, acts in matrix.items():
            # NOTE: You are using UPDATE in actions, not WRITE.
            can_read   = acts.get("READ", False)
            can_create = acts.get("CREATE", False)
            can_update = acts.get("UPDATE", False)
            can_delete = acts.get("DELETE", False)
            can_submit = acts.get("SUBMIT", False)
            can_cancel = acts.get("CANCEL", False)
            can_amend  = acts.get("AMEND", False)

            result.append(
                DocPermissionOut(
                    role=role_name,
                    level=0,  # you can use this later for advanced levels
                    can_read=can_read,
                    can_write=can_update,   # map UPDATE -> can_write
                    can_create=can_create,
                    can_delete=can_delete,
                    can_submit=can_submit,
                    can_cancel=can_cancel,
                    can_amend=can_amend,
                )
            )

        # Sort by role name for stable UI
        result.sort(key=lambda r: r.role.lower())
        return result


permission_matrix_service = PermissionMatrixService()
