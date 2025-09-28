
# seed_data/rbac/seeder.py
from __future__ import annotations

import logging
from typing import Optional, Iterable, Dict, Set, List, Tuple

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

# ✅ RBAC models
from app.application_rbac.rbac_models import (
    DocType,
    Action,
    Permission,
    Role,
    RolePermission,
    RoleScopeEnum,
)

# ✅ Seed constants
from .data import (
    DEFAULT_ACTIONS,
    DEFAULT_DOCTYPE_MODULES,
    DEFAULT_DOCTYPE_MAPPINGS,
    DEFAULT_ROLES,
    ROLE_PERMISSION_MAP,
    WILDCARD_DOCTYPE_NAME,
    WILDCARD_ACTION_NAME,
)

logger = logging.getLogger(__name__)


# ---------------- helpers ----------------
def _ensure_citext(db: Session) -> None:
    """Enable Postgres citext (safe to call multiple times)."""
    db.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))


def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters):
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False
    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    try:
        db.flush([obj])
        return obj, True
    except IntegrityError:
        db.rollback()
        return db.scalar(select(model).filter_by(**filters)), False


def _label_from_slug(slug: str) -> str:
    return slug.strip().replace("_", " ").title()


def _expand_manage_to_crud(actions_index: Dict[str, Action]) -> List[str]:
    """Order of CRUD expansion."""
    base = ["READ", "CREATE", "UPDATE", "DELETE"]
    return [a for a in base if a in actions_index]


def _expand_perm_strings(
    strings: Iterable[str],
    *,
    actions_index: Dict[str, Action],
    perm_index: Dict[Tuple[str, str], Permission],
) -> Set[int]:
    """
    Expand role permission strings into Permission IDs using indexes.

    Supports (case sensitive for names as stored):
      "*:*"            -> ONLY the single wildcard Permission (*:*)
      "DocType:*"      -> all actions (non-wildcard) for that DocType
      "*:ACTION"       -> ACTION for all DocTypes
      "DocType:ACTION" -> specific pair
      "DocType:MANAGE" -> expands to CRUD (READ, CREATE, UPDATE, DELETE)
    """
    out: Set[int] = set()

    for s in strings:
        if ":" not in s:
            logger.warning("Skipping malformed permission string %r (no ':')", s)
            continue
        raw_dt, raw_ac = s.split(":", 1)
        dt = raw_dt.strip()
        ac = raw_ac.strip().upper()

        # --- SINGLE WILDCARD PERMISSION ---
        if dt == WILDCARD_DOCTYPE_NAME and ac == WILDCARD_ACTION_NAME:
            perm = perm_index.get((WILDCARD_DOCTYPE_NAME, WILDCARD_ACTION_NAME))
            if not perm:
                logger.warning("Wildcard Permission (*:*) missing; check seeder order.")
                continue
            out.add(perm.id)
            continue

        # --- MANAGE -> CRUD expansion ---
        if ac == "MANAGE":
            for base_ac in _expand_manage_to_crud(actions_index):
                p = perm_index.get((dt, base_ac))
                if p:
                    out.add(p.id)
                else:
                    logger.debug("No permission for %s:%s (skipped)", dt, base_ac)
            continue

        # --- DocType:* (all non-wildcard actions for this DocType) ---
        if ac == WILDCARD_ACTION_NAME and dt != WILDCARD_DOCTYPE_NAME:
            for a_name in actions_index.keys():
                if a_name == WILDCARD_ACTION_NAME:
                    continue
                p = perm_index.get((dt, a_name))
                if p:
                    out.add(p.id)
            continue

        # --- *:ACTION (ACTION across all DocTypes) ---
        if dt == WILDCARD_DOCTYPE_NAME and ac != WILDCARD_ACTION_NAME:
            for (d_name, a_name), p in perm_index.items():
                if d_name == WILDCARD_DOCTYPE_NAME:
                    continue
                if a_name == ac:
                    out.add(p.id)
            continue

        # --- exact pair ---
        p = perm_index.get((dt, ac))
        if not p:
            logger.warning("Permission %r not found (DocType/Action missing?)", s)
            continue
        out.add(p.id)

    return out


# ---------------- seeders ----------------
def _seed_actions(db: Session) -> Dict[str, Action]:
    """Seed default Actions (INCLUDING the wildcard '*')."""
    logger.info("Seeding Actions...")
    index: Dict[str, Action] = {}
    for name, description in DEFAULT_ACTIONS:
        a, _ = _get_or_create(
            db,
            Action,
            name=name.upper(),
            defaults={
                "label": _label_from_slug(name),
                "description": description,
                "is_system_defined": True,
                "is_deprecated": False,
            },
        )
        index[a.name] = a
    logger.info("✅ Actions seeded: %d", len(index))
    return index


def _seed_doctypes(db: Session) -> Dict[str, DocType]:
    """Seed DocTypes: module roots (groups) + leaves + wildcard doctype '*'."""
    logger.info("Seeding DocTypes (modules + leaves + wildcard)...")

    # wildcard doctype first
    wd, _ = _get_or_create(
        db,
        DocType,
        module="System",
        name=WILDCARD_DOCTYPE_NAME,
        defaults={"is_group": False, "tree_depth": 0, "description": "Wildcard DocType"},
    )

    # union: ensures modules present even if only in mappings
    modules = sorted(set(DEFAULT_DOCTYPE_MODULES) | set(DEFAULT_DOCTYPE_MAPPINGS.keys()))

    # 1) module roots
    roots: Dict[str, DocType] = {}
    for module in modules:
        root, _ = _get_or_create(
            db,
            DocType,
            module=module,
            name=module,
            defaults={"is_group": True, "tree_depth": 0, "description": f"{module} root"},
        )
        roots[module.lower()] = root

    # 2) leaves per module
    for module, names in DEFAULT_DOCTYPE_MAPPINGS.items():
        root = roots.get(module.lower())
        if not root:
            logger.warning("Root module %r not found; skipping leaves.", module)
            continue
        for name in names:
            if name.lower() == module.lower():
                continue
            _get_or_create(
                db,
                DocType,
                module=module,
                name=name,
                defaults={"is_group": False, "tree_depth": 1, "parent_doctype_id": root.id},
            )

    logger.info("✅ DocTypes seeded.")
    # return quick lookup by name (case-sensitive for "*")
    all_leaves = db.scalars(select(DocType).where(DocType.is_group.is_(False))).all()
    return {d.name: d for d in all_leaves}


def _seed_permissions(db: Session, actions_idx: Dict[str, Action], doctypes_idx: Dict[str, DocType]) -> Dict[Tuple[str, str], Permission]:
    """
    Seed Permission rows:
      - For each leaf DocType (EXCEPT the wildcard doctype '*'), create DocType × every Action.
      - Ensure a SINGLE wildcard Permission (*:*) exists.
    """
    logger.info("Seeding Permissions...")

    # Create permissions for all leaves except the wildcard doctype
    leaves = db.scalars(
        select(DocType).where(DocType.is_group.is_(False), DocType.name != WILDCARD_DOCTYPE_NAME)
    ).all()

    for dt in leaves:
        for act in actions_idx.values():
            # Skip pairing leaves with wildcard action to avoid meaningless (DocType × '*') rows
            if act.name == WILDCARD_ACTION_NAME:
                continue

            exists = db.scalar(
                select(Permission).where(
                    Permission.doctype_id == dt.id,
                    Permission.action_id == act.id,
                    Permission.company_id.is_(None),
                )
            )
            if not exists:
                db.add(
                    Permission(
                        doctype_id=dt.id,
                        action_id=act.id,
                        company_id=None,
                        description=f"{act.label} on {dt.name}",
                        is_system_defined=True,
                    )
                )

    # Ensure ONE wildcard Permission (*:*) exists
    dt_wild = doctypes_idx.get(WILDCARD_DOCTYPE_NAME)
    ac_wild = actions_idx.get(WILDCARD_ACTION_NAME)
    if not dt_wild or not ac_wild:
        logger.error("Wildcard DocType or Action missing; cannot create (*:*) Permission.")
    else:
        _get_or_create(
            db,
            Permission,
            doctype_id=dt_wild.id,
            action_id=ac_wild.id,
            defaults={"company_id": None, "description": "Wildcard permission", "is_system_defined": True},
        )

    logger.info("✅ Permissions seeded.")
    # Build a quick index (DocTypeName, ActionName) -> Permission
    all_perms = db.scalars(
        select(Permission).options(joinedload(Permission.doctype), joinedload(Permission.action))
    ).all()
    out: Dict[Tuple[str, str], Permission] = {}
    for p in all_perms:
        out[(p.doctype.name, p.action.name)] = p
    return out


def _seed_roles(db: Session) -> Dict[str, Role]:
    """Seed Roles with scopes."""
    logger.info("Seeding Roles...")
    out: Dict[str, Role] = {}
    for r in DEFAULT_ROLES:
        scope = r["scope"]
        scope_enum = scope if isinstance(scope, RoleScopeEnum) else RoleScopeEnum[scope]
        role, _ = _get_or_create(
            db,
            Role,
            name=r["name"],
            scope=scope_enum,
            company_id=None,
            defaults={"description": r.get("description"), "is_system_defined": True},
        )
        out[role.name] = role
    logger.info("✅ Roles seeded: %d", len(out))
    return out


def _seed_role_permissions(db: Session, roles: Dict[str, Role], actions_idx: Dict[str, Action], perm_idx: Dict[Tuple[str, str], Permission]) -> None:
    """
    Assign role → permissions using ROLE_PERMISSION_MAP with compact wildcard:
      - '*:*' is mapped to the SINGLE (*:*) Permission (no expansion).
      - 'MANAGE' expands to CRUD when present in role maps.
    """
    logger.info("Assigning Role → Permission mappings...")
    for role_name, strings in ROLE_PERMISSION_MAP.items():
        role = roles.get(role_name)
        if not role:
            logger.warning("Role %r not found; skipping its permission map.", role_name)
            continue

        desired_perm_ids = _expand_perm_strings(strings, actions_index=actions_idx, perm_index=perm_idx)
        if not desired_perm_ids:
            logger.warning("No resolvable permissions for role %r (check constants).", role_name)
            continue

        existing = db.scalars(select(RolePermission).where(RolePermission.role_id == role.id)).all()
        existing_ids = {rp.permission_id for rp in existing}

        added = 0
        for pid in desired_perm_ids:
            if pid not in existing_ids:
                db.add(RolePermission(role_id=role.id, permission_id=pid))
                added += 1

        logger.info("  Role %-18s -> +%d permissions", role_name, added)
    logger.info("✅ Role → Permission mappings assigned.")


# ---------------- public entrypoint ----------------
def seed_rbac(db: Session) -> None:
    """
    Full RBAC seeding:
      1) citext extension
      2) Actions (includes '*')
      3) DocTypes (modules + leaves + wildcard '*')
      4) Permissions (leaf × action, plus single (*:*) permission)
      5) Roles
      6) RolePermission mappings (wildcard compact; MANAGE → CRUD)
    """
    logger.info("🚀 RBAC seed started")
    _ensure_citext(db)
    actions_idx = _seed_actions(db)
    doctypes_idx = _seed_doctypes(db)
    perm_idx = _seed_permissions(db, actions_idx, doctypes_idx)
    roles = _seed_roles(db)
    _seed_role_permissions(db, roles, actions_idx, perm_idx)
    logger.info("🎉 RBAC seed complete.")
