from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application_education.groups.student_group_model import Section
# Org models (kept for future tenant seeding)
from app.application_org.models.company import Company, Branch, Department

# Users / affiliations
from app.auth.models.users import User, UserAffiliation, UserType
from app.application_rbac.rbac_models import Role, UserRole

# Password hashing
try:
    from app.common.security.passwords import hash_password
except Exception:
    from src.common.security.passwords import hash_password  # type: ignore

# Seed constants
from .data import (
    DEFAULT_DEPARTMENTS,   # KEPT
    DEFAULT_USER_TYPES,
    SYSTEM_OWNER_USERS,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# helpers
# ------------------------------------------------------------

def _get_or_create(
    db: Session,
    model,
    *,
    defaults: Optional[dict] = None,
    **filters
) -> Tuple[object, bool]:
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False

    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    try:
        db.flush()
        return obj, True
    except IntegrityError:
        db.rollback()
        return db.scalar(select(model).filter_by(**filters)), False


def _safe_hash(plain: str) -> str:
    return hash_password(plain)


# ------------------------------------------------------------
# seeders
# ------------------------------------------------------------
GLOBAL_SECTIONS = ["A", "B", "C", "D", "E", "F", "G"]

def _seed_global_sections(db: Session) -> None:
    logger.info("Seeding global education sections...")

    created = 0
    for name in GLOBAL_SECTIONS:
        name = name.strip().upper()
        exists = db.scalar(select(Section).where(Section.section_name == name))
        if exists:
            continue

        db.add(Section(section_name=name))
        created += 1

    if created:
        db.flush()

    logger.info("✅ Sections seeded (created=%s)", created)
def _seed_user_types(db: Session) -> None:
    logger.info("Seeding user types...")

    DESCRIPTIONS = {
        "Owner": "Company owner / primary controller for a tenant.",
        "System User": "Generic system user type for day-to-day users.",
        "System Administrator": "System-wide administration and management.",
    }

    for name in DEFAULT_USER_TYPES:
        _get_or_create(
            db,
            UserType,
            name=name,
            defaults={"description": DESCRIPTIONS.get(name, name)},
        )

    logger.info("✅ User types seeded.")


def _seed_system_owner_users(db: Session) -> None:
    """
    Create global system owner users.
    NO companies. NO affiliations.
    """
    logger.info("Seeding global system owner users (no affiliations)...")

    system_admin_role = db.scalar(select(Role).filter_by(name="System Admin"))
    if not system_admin_role:
        logger.error("❌ Role 'System Admin' not found. Cannot seed system owners.")
        return

    for spec in SYSTEM_OWNER_USERS:
        user, _ = _get_or_create(
            db,
            User,
            username=spec["username"].strip(),
            defaults={"password_hash": _safe_hash(spec["password"])},
        )

        _get_or_create(
            db,
            UserRole,
            user_id=user.id,
            role_id=system_admin_role.id,
            company_id=None,          # SYSTEM scope
            branch_id=None,           # SYSTEM scope
            user_affiliation_id=None, # NO affiliation
            defaults={
                "is_active": True,
                "assigned_by": None,
            },
        )

    logger.info("✅ System owner users created.")


# ------------------------------------------------------------
# PUBLIC ENTRY POINT (THIS is what flask seed core should call)
# ------------------------------------------------------------

def seed_core(db: Session) -> None:
    """
    CORE seeding only:
      - UserTypes
      - System owner users (System Admins)

    ❌ No companies
    ❌ No branches
    ❌ No departments
    """
    logger.info("🚀 Seeding CORE system data...")

    _seed_user_types(db)
    _seed_system_owner_users(db)
    _seed_global_sections(db)
    logger.info("🎉 Core seeding complete.")
