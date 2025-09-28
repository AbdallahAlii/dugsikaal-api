# app/security/effective_permissions.py


import logging
from typing import Set, Tuple, List

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload, Session

from app.application_rbac.rbac_models import (
    UserRole,
    Role,
    RolePermission,
    Permission,
    PermissionOverride,
    RoleScopeEnum,
)

logger = logging.getLogger(__name__)


def get_effective_permissions_from_db(user_id: int, db: Session) -> Tuple[Set[str], List[str], bool]:
    """
    Calculates a user's effective permissions directly from the database with detailed logging.
    """
    logger.debug(f"--- Starting get_effective_permissions_from_db for user_id: {user_id} ---")
    effective_permissions: Set[str] = set()
    role_names: set[str] = set()
    is_system_admin = False

    # Robust query strategy
    stmt_roles = (
        select(UserRole)
        .where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
        .options(
            joinedload(UserRole.role).options(
                selectinload(Role.role_permissions).options(
                    joinedload(RolePermission.permission).options(
                        joinedload(Permission.doctype),
                        joinedload(Permission.action)
                    )
                )
            )
        )
    )

    # .unique() is important when using joinedload with collections to avoid duplicate parent objects
    user_roles = db.execute(stmt_roles).scalars().unique().all()
    logger.debug(f"Found {len(user_roles)} active user role assignments for user {user_id}.")

    for ur in user_roles:
        if not ur.role:
            logger.warning(f"UserRole ID {ur.id} for user {user_id} has no associated role object. Check data integrity.")
            continue

        role_names.add(ur.role.name)
        logger.debug(f"Processing Role: '{ur.role.name}' (Scope: {ur.role.scope.value})")

        if ur.role.scope == RoleScopeEnum.SYSTEM:
            logger.warning(f"✅ Granting '*' global wildcard permission to user {user_id} via SYSTEM scoped role: '{ur.role.name}'")
            is_system_admin = True
            # Return immediately with all data populated
            return {"*"}, sorted(list(role_names)), True

        if not ur.role.role_permissions:
            logger.debug(f"  Role '{ur.role.name}' has no specific role_permissions attached.")

        for rp in ur.role.role_permissions:
            p = rp.permission
            if p and p.doctype and p.action:
                perm_string = f"{p.doctype.name}:{p.action.name}"
                effective_permissions.add(perm_string)
                logger.debug(f"  -> Added permission '{perm_string}' from role '{ur.role.name}'.")
            else:
                logger.warning(f"  -> Skipping malformed permission link from role '{ur.role.name}'.")

    # Process overrides (only if not a system admin)
    stmt_overrides = (
        select(PermissionOverride)
        .where(PermissionOverride.user_id == user_id)
        .options(
            joinedload(PermissionOverride.permission).options(
                joinedload(Permission.doctype),
                joinedload(Permission.action)
            )
        )
    )
    overrides = db.execute(stmt_overrides).scalars().all()
    if overrides:
        logger.debug(f"Found {len(overrides)} permission overrides for user {user_id}.")
        for po in overrides:
            p = po.permission
            if p and p.doctype and p.action:
                perm_string = f"{p.doctype.name}:{p.action.name}"
                if po.is_allowed:
                    effective_permissions.add(perm_string)
                    logger.debug(f"  -> Override ALLOW: Added permission '{perm_string}'.")
                else:
                    effective_permissions.discard(perm_string)
                    logger.debug(f"  -> Override DENY: Removed permission '{perm_string}'.")
            else:
                logger.warning("  -> Skipping malformed permission override link.")

    logger.info(f"--- User {user_id} final effective permissions: {effective_permissions} ---")
    return effective_permissions, sorted(list(role_names)), is_system_admin