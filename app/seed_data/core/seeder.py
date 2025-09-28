# seed_data/core/seeder.py
from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Org models (all three are in this module)
from app.application_org.models.company import Company, Branch, Department

# Users / affiliations
from app.auth.models.users import User, UserAffiliation, UserType

# Password hashing
try:
    from app.common.security.passwords import hash_password
except Exception:
    from src.common.security.passwords import hash_password  # type: ignore

# Seed constants (relative import from this package)
from .data import (
    DEFAULT_DEPARTMENTS,
    DEFAULT_USER_TYPES,
    INITIAL_COMPANIES,
    SYSTEM_OWNER_USERS,
)

logger = logging.getLogger(__name__)


# ---------- helpers ----------
def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters) -> Tuple[object, bool]:
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


# ---------- seeders ----------
def _seed_user_types(db: Session) -> None:
    """
    Create user types:
      - Owner

      - System User
      - System Administrator
    """
    logger.info("Seeding user types...")
    DESCRIPTIONS = {
        "Owner": "Company owner / primary controller for a tenant.",

        "System User": "Generic system user type for day-to-day users.",
        "System Administrator": "System-wide administration and management.",
    }
    for name in DEFAULT_USER_TYPES:
        _get_or_create(
            db, UserType,
            name=name,
            defaults={"description": DESCRIPTIONS.get(name, f"Default '{name}' user type")}
        )
    logger.info("✅ User types seeded.")


def _seed_company_and_hq(db: Session, payload: dict) -> tuple[Company, Branch]:
    """Upsert company + its HQ branch."""
    company, created = _get_or_create(
        db,
        Company,
        name=payload["name"],
        defaults={
            "headquarters_address": payload.get("headquarters_address"),
            "contact_email": payload.get("contact_email"),
            "contact_phone": payload.get("contact_phone"),
            "prefix": payload.get("prefix"),
        },
    )
    if not created:
        # update changed fields if provided (idempotent)
        dirty = False
        for f in ("headquarters_address", "contact_email", "contact_phone" ,"prefix"):
            v = payload.get(f)
            if v and getattr(company, f) != v:
                setattr(company, f, v)
                dirty = True
        if dirty:
            db.flush()

    hq = payload.get("hq_branch", {}) or {}
    branch, _ = _get_or_create(
        db,
        Branch,
        company_id=company.id,
        code=hq.get("code"),
        defaults={
            "name": hq.get("name", "Head Office"),
            "location": hq.get("location", company.headquarters_address),
            "is_hq": bool(hq.get("is_hq", True)),
            "created_by": None,  # no user yet — safe audit default
        },
    )
    return company, branch


def _seed_departments_for_company(db: Session, company: Company) -> None:
    """Pre-seed a handful of common departments (system-defined)."""
    logger.info("Seeding default departments for %s...", company.name)
    for idx, name in enumerate(DEFAULT_DEPARTMENTS, start=1):
        _get_or_create(
            db,
            Department,
            company_id=company.id,
            name=name,
            defaults={
                "code": f"D{idx:02d}",
                "description": f"Default {name} department",
                "is_system_defined": True,
            },
        )
    logger.info("✅ Departments seeded for %s.", company.name)


def _seed_owner_user_and_affiliation(db: Session, company: Company, owner_spec: dict) -> User:
    """
    Create the company owner user + affiliation (company-level, no branch).
    Uses UserType = 'Owner' (as requested).
    """
    username = owner_spec["username"].strip()
    password = owner_spec["password"]

    # User
    user, created = _get_or_create(
        db,
        User,
        username=username,
        defaults={"password_hash": _safe_hash(password)},
    )
    if not created:
        # don't rotate password if user already exists
        pass

    # UserType: Owner
    owner_ut, _ = _get_or_create(db, UserType, name="Owner", defaults={"description": "Company owner"})

    # Affiliation (company only, branch=None)
    _get_or_create(
        db,
        UserAffiliation,
        user_id=user.id,
        company_id=company.id,
        branch_id=None,
        user_type_id=owner_ut.id,
        linked_entity_id=None,
        defaults={"is_primary": True},
    )
    return user


def _seed_system_owner_users(db: Session) -> None:
    """
    Create two global “system owner” logins:
      - sys_owner1
      - sys_owner2
    NOTE: Your UserAffiliation requires company_id NOT NULL, so we do NOT
    create affiliations for these users. If you want affiliations with no company,
    either relax the model (company_id nullable) or introduce a dedicated
    “Platform” company and affiliate them there.
    """
    logger.info("Seeding global system owner users (no affiliations)...")
    for spec in SYSTEM_OWNER_USERS:
        _get_or_create(
            db, User,
            username=spec["username"].strip(),
            defaults={"password_hash": _safe_hash(spec["password"])},
        )
    logger.info("✅ System owner users created.")


def seed_initial_organization(db: Session) -> None:
    """
    Create:
      - UserTypes (Owner, Staff, System User, System Administrator)
      - System owner users (sys_owner1, sys_owner2) — users only, no affiliations
      - Companies (2)
      - HQ Branch for each
      - Default Departments per company
      - Company owner user for each + company-level affiliation using UserType 'Owner'
    """
    logger.info("🏢 Seeding initial organization data...")

    _seed_user_types(db)
    _seed_system_owner_users(db)

    for spec in INITIAL_COMPANIES:
        company, hq_branch = _seed_company_and_hq(db, spec)
        _seed_departments_for_company(db, company)
        _seed_owner_user_and_affiliation(db, company, spec["owner_user"])
        logger.info("✅ Seeded company %s (HQ: %s)", company.name, hq_branch.code)

    logger.info("🎉 Organization seeding complete.")
