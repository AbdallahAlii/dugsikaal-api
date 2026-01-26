# app/security/rbac_effective.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Set, List

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from flask import g

from config.database import db
from app.application_rbac.rbac_models import (
    RoleScopeEnum,
    Permission, Role, RolePermission, UserRole, PermissionOverride,
)
from app.auth.models.users import UserAffiliation

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

    # convenience (compat with older code)
    branch_ids: List[int]

    # permissions as "DocType:ACTION", or {"*"} for global
    permissions: Set[str]

    # role names for reference/debug
    roles: List[str]

    # convenient flag
    is_system_admin: bool


# -------------------------------------------------------------------
# Permission aliases (Party -> Customer/Supplier)
# -------------------------------------------------------------------
_ALIAS_DOCTYPES = ("Customer", "Supplier")


def _split_perm(p: str) -> tuple[str, str] | None:
    if not p or ":" not in p:
        return None
    dt, act = p.split(":", 1)
    dt = (dt or "").strip()
    act = (act or "").strip()
    if not dt or not act:
        return None
    return dt, act


def _has_any(perms: Set[str], doctype: str, actions: set[str]) -> bool:
    for a in actions:
        if f"{doctype}:{a}" in perms:
            return True
    return False


def apply_party_permission_aliases(perms: Set[str]) -> Set[str]:
    """
    Navigation/workspace uses "Customer:READ" / "Supplier:READ",
    but backend is unified as Party.

    So we alias:
      Party:READ   -> Customer:READ, Supplier:READ
      Party:CREATE -> Customer:CREATE, Supplier:CREATE
      Party:UPDATE -> Customer:UPDATE, Supplier:UPDATE
      Party:DELETE -> Customer:DELETE, Supplier:DELETE

    Also treat Party:MANAGE as CRUD if it exists.
    """
    if not perms:
        return perms

    # System wildcard: no need to add aliases (but harmless if you do).
    if "*" in perms or "*:*" in perms:
        return perms

    # Determine Party actions present
    party_actions: set[str] = set()
    for p in perms:
        sp = _split_perm(p)
        if not sp:
            continue
        dt, act = sp
        if dt == "Party":
            party_actions.add(act)

    if not party_actions:
        return perms

    # Expand MANAGE -> CRUD if MANAGE exists in your DB (some seeders keep it)
    if "MANAGE" in party_actions:
        party_actions.update({"READ", "CREATE", "UPDATE", "DELETE"})

    # If Party can be read, allow Customer/Supplier views in UI navigation
    if "READ" in party_actions:
        for dt in _ALIAS_DOCTYPES:
            perms.add(f"{dt}:READ")

    # If Party has write actions, mirror them (nice + consistent)
    for act in ("CREATE", "UPDATE", "DELETE"):
        if act in party_actions:
            for dt in _ALIAS_DOCTYPES:
                perms.add(f"{dt}:{act}")

    return perms


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

    user_roles = db.session.scalars(roles_q).unique().all()

    # System-scoped role => global wildcard
    if any(ur.role and ur.role.scope == RoleScopeEnum.SYSTEM for ur in user_roles):
        return {"*"}

    # Role-based perms
    for ur in user_roles:
        r = ur.role
        if not r:
            continue
        for rp in r.role_permissions:
            p = rp.permission
            if p and p.doctype and p.action:
                perms.add(f"{p.doctype.name}:{p.action.name}")

    # Overrides
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

    # ✅ Apply aliases for navigation/workspace gating
    perms = apply_party_permission_aliases(perms)

    return perms


# ---------------------------------------
# Build a simple request context (like FastAPI)
# ---------------------------------------
def build_affiliation_context(user_id: int) -> AffiliationContext:
    """
    Loads:
      - primary affiliation (if any)
      - list of all affiliations
      - branch_ids convenience list
      - user_type (from primary, if any)
      - roles (names)
      - permissions (via compute_effective_permissions + aliases)
    """
    affs = db.session.scalars(
        select(UserAffiliation)
        .options(joinedload(UserAffiliation.user_type))
        .where(UserAffiliation.user_id == user_id)
    ).all()

    primary = None
    if affs:
        # prefer is_primary True, else first
        primary = sorted(affs, key=lambda a: bool(a.is_primary), reverse=True)[0]

    primary_company = primary.company_id if primary else None
    primary_branch = primary.branch_id if primary else None
    primary_type = primary.user_type.name if (primary and primary.user_type) else None

    all_affs = [AffiliationMini(a.company_id, a.branch_id) for a in affs]

    # convenience branch_ids (for any code that expects ctx.branch_ids)
    branch_ids = sorted(
        {int(a.branch_id) for a in affs if getattr(a, "branch_id", None) is not None}
    )

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
        branch_ids=branch_ids,
        permissions=compute_effective_permissions(user_id),
        roles=role_names,
        is_system_admin=is_sys_admin,
    )


def attach_auth_context(user_id: int) -> None:
    """Attach the user's affiliation context to g.auth."""
    g.auth = build_affiliation_context(user_id)
