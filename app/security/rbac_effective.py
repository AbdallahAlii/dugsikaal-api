# rbac_effective
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Set, List

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from flask import g, jsonify
from config.database import db
from app.application_rbac.rbac_models import (
    RoleScopeEnum,
    Permission, Role, RolePermission, UserRole, PermissionOverride,
)
from app.auth.models.users import UserAffiliation, UserType

logger = logging.getLogger(__name__)


# ---------------------------
# Light-weight auth context
# ---------------------------
@dataclass
class AffiliationMini:
    company_id: Optional[int]
    branch_id: Optional[int]

@dataclass
class AffiliationContext:
    user_id: int
    # primary affiliation (nullable)
    company_id: Optional[int]
    branch_id: Optional[int]
    user_type: Optional[str]
    # all affiliations for easy scope checks
    affiliations: List[AffiliationMini]
    # permissions as "DocType:ACTION", or {"*"} for global
    permissions: Set[str]
    # role names for reference/debug
    roles: List[str]
    # convenient flag
    is_system_admin: bool


# ---------------------------------------
# Effective permissions (roles + overrides)
# ---------------------------------------
def compute_effective_permissions(user_id: int) -> Set[str]:
    """
    Build the set of permission strings the user has, ignoring company/branch.
    Scope (company/branch) is enforced separately in the service layer.

    Short-circuit: if user has ANY SYSTEM-scoped role => return {"*"}.
    """
    perms: Set[str] = set()

    # Roles (+ permissions)
    roles_q = (
        select(UserRole)
        .where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
        .options(
            joinedload(UserRole.role)
                .joinedload(Role.role_permissions)
                .joinedload(RolePermission.permission)
                .joinedload(Permission.doctype),
            joinedload(UserRole.role)
                .joinedload(Role.role_permissions)
                .joinedload(RolePermission.permission)
                .joinedload(Permission.action),
        )
    )

    # Fetch the roles uniquely
    user_roles = db.session.scalars(roles_q).unique().all()

    # Check for global wildcard permission (SYSTEM scoped role)
    if any(ur.role and ur.role.scope == RoleScopeEnum.SYSTEM for ur in user_roles):
        return {"*"}

    # Collect role-based permissions
    for ur in user_roles:
        r = ur.role
        if not r:
            continue
        for rp in r.role_permissions:
            p = rp.permission
            if p and p.doctype and p.action:
                perms.add(f"{p.doctype.name}:{p.action.name}")

    # Handle overrides
    ov_q = (
        select(PermissionOverride)
        .where(PermissionOverride.user_id == user_id)
        .options(
            joinedload(PermissionOverride.permission).joinedload(Permission.doctype),
            joinedload(PermissionOverride.permission).joinedload(Permission.action),
        )
    )

    for po in db.session.scalars(ov_q).all():
        p = po.permission
        if not p or not p.doctype or not p.action:
            continue
        s = f"{p.doctype.name}:{p.action.name}"
        if po.is_allowed:
            perms.add(s)
        else:
            perms.discard(s)

    return perms



# ---------------------------------------
# Build a simple request context (like FastAPI)
# ---------------------------------------
def build_affiliation_context(user_id: int) -> AffiliationContext:
    """
    Loads:
      - primary affiliation (if any)
      - list of all affiliations
      - user_type (from primary, if any)
      - roles (names)
      - permissions (via compute_effective_permissions)
    """
    # affiliations
    affs = db.session.scalars(
        select(UserAffiliation)
        .options(joinedload(UserAffiliation.user_type))
        .where(UserAffiliation.user_id == user_id)
    ).all()

    primary = None
    # prefer is_primary True, else first
    if affs:
        primary = sorted(affs, key=lambda a: bool(a.is_primary), reverse=True)[0]

    primary_company = primary.company_id if primary else None
    primary_branch  = primary.branch_id if primary else None
    primary_type    = primary.user_type.name if (primary and primary.user_type) else None

    all_affs = [AffiliationMini(a.company_id, a.branch_id) for a in affs]

    # role names + system admin flag
    roles_q = (
        select(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
        .options(joinedload(UserRole.role))
    )
    urs = db.session.scalars(roles_q).all()
    role_names = [ur.role.name for ur in urs if ur.role]
    is_sys_admin = any(ur.role and ur.role.scope == RoleScopeEnum.SYSTEM for ur in urs)

    return AffiliationContext(
        user_id=user_id,
        company_id=primary_company,
        branch_id=primary_branch,
        user_type=primary_type,
        affiliations=all_affs,
        permissions=compute_effective_permissions(user_id),
        roles=role_names,
        is_system_admin=is_sys_admin,
    )


def attach_auth_context(user_id: int) -> None:
    """ Attach the user's affiliation context to g.auth """
    context = build_affiliation_context(user_id)
    g.auth = context