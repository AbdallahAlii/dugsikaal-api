# seed_data/codes/seeder.py
from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from sqlalchemy.orm import Session

from app.application_org.models.code_counter_model import CodeType, CodeScopeEnum, ResetPolicyEnum
from .data import CODE_TYPES

logger = logging.getLogger(__name__)


def _get_or_create_code_type(
    db: Session,
    *,
    name: str,
    prefix: str,
    defaults: Optional[dict] = None,
) -> Tuple[CodeType, bool]:
    """
    Get or create CodeType by (prefix OR name).

    - If a row exists with the same prefix OR same name -> return it (no insert).
    - Otherwise, create a new row using defaults.
    """
    defaults = defaults or {}

    # 1) Try to load an existing row by prefix OR name
    query = select(CodeType).where(
        or_(
            CodeType.prefix == prefix,
            CodeType.name == name,
        )
    )

    try:
        obj = db.scalar(query)
    except MultipleResultsFound:
        # This *shouldn't* happen if you have proper unique constraints,
        # but if it does, log and take the first row.
        logger.error(
            "Multiple CodeType rows match name=%r or prefix=%r; using the first one.",
            name,
            prefix,
            exc_info=True,
        )
        obj = db.scalars(query).first()

    if obj is not None:
        # Existing row – no insert
        return obj, False

    # 2) Create new row
    obj = CodeType(
        prefix=prefix,
        **defaults,  # defaults should include name, pattern, scope, reset_policy, padding
    )
    db.add(obj)
    try:
        db.flush()
        return obj, True
    except IntegrityError as e:
        # Likely a race condition or legacy data conflicting on name/prefix.
        db.rollback()
        logger.error(
            "IntegrityError while creating CodeType name=%r prefix=%r: %s",
            name,
            prefix,
            e,
            exc_info=True,
        )
        # Re-query; if we can now see it, treat as existing.
        obj = db.scalar(query)
        if obj is None:
            # Still nothing → propagate the DB error so you see the real problem.
            raise
        return obj, False


def seed_code_types(db: Session) -> None:
    """
    Idempotent seeding of CodeType catalog.
    - Creates missing rows by (name/prefix)
    - Updates pattern/scope/reset_policy/padding/prefix if changed
    """
    logger.info("Seeding code types...")

    for spec in CODE_TYPES:
        name      = spec["name"].strip()
        prefix    = spec["prefix"].strip()
        pattern   = spec["pattern"].strip()
        scope_str = spec["scope"].strip().upper()
        reset_str = spec["reset_policy"].strip().upper()
        padding   = int(spec["padding"])

        scope        = CodeScopeEnum(scope_str)
        reset_policy = ResetPolicyEnum(reset_str)

        defaults = dict(
            name=name,
            pattern=pattern,
            scope=scope,
            reset_policy=reset_policy,
            padding=padding,
        )

        row, created = _get_or_create_code_type(
            db,
            name=name,
            prefix=prefix,
            defaults=defaults,
        )

        if created:
            logger.info("  + %s (%s) created", name, prefix)
        else:
            # Bring existing row fully up to date (idempotent updates)
            changed = False

            if row.name != name:
                row.name = name
                changed = True

            if row.prefix != prefix:
                row.prefix = prefix
                changed = True

            if row.pattern != pattern:
                row.pattern = pattern
                changed = True

            if row.scope != scope:
                row.scope = scope
                changed = True

            if row.reset_policy != reset_policy:
                row.reset_policy = reset_policy
                changed = True

            if row.padding != padding:
                row.padding = padding
                changed = True

            if changed:
                logger.info("  ~ %s (%s) updated", name, prefix)

    db.commit()
    logger.info("✅ Code types seeding complete.")
