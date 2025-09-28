# seed_data/codes/seeder.py
from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application_org.models.code_counter_model import CodeType, CodeScopeEnum, ResetPolicyEnum
from .data import CODE_TYPES

logger = logging.getLogger(__name__)


def _get_or_create_by_prefix(
    db: Session,
    *,
    prefix: str,
    defaults: Optional[dict] = None
) -> Tuple[CodeType, bool]:
    obj = db.scalar(select(CodeType).where(CodeType.prefix == prefix))
    if obj:
        return obj, False

    obj = CodeType(prefix=prefix, **(defaults or {}))
    db.add(obj)
    try:
        db.flush()
        return obj, True
    except IntegrityError:
        db.rollback()
        obj = db.scalar(select(CodeType).where(CodeType.prefix == prefix))
        return obj, False


def seed_code_types(db: Session) -> None:
    """
    Idempotent seeding of CodeType catalog.
    - Creates by prefix if missing
    - Updates pattern/scope/reset_policy/padding if changed
    """
    logger.info("Seeding code types...")

    for spec in CODE_TYPES:
        name          = spec["name"].strip()
        prefix        = spec["prefix"].strip()
        pattern       = spec["pattern"].strip()
        scope_str     = spec["scope"].strip().upper()
        reset_str     = spec["reset_policy"].strip().upper()
        padding       = int(spec["padding"])

        scope        = CodeScopeEnum(scope_str)
        reset_policy = ResetPolicyEnum(reset_str)

        defaults = dict(
            name=name,
            pattern=pattern,
            scope=scope,
            reset_policy=reset_policy,
            padding=padding,
        )

        row, created = _get_or_create_by_prefix(db, prefix=prefix, defaults=defaults)
        if created:
            logger.info("  + %s (%s) created", name, prefix)
        else:
            # Bring existing row up to date (idempotent updates)
            changed = False
            if row.name != name:
                row.name = name; changed = True
            if row.pattern != pattern:
                row.pattern = pattern; changed = True
            if row.scope != scope:
                row.scope = scope; changed = True
            if row.reset_policy != reset_policy:
                row.reset_policy = reset_policy; changed = True
            if row.padding != padding:
                row.padding = padding; changed = True
            if changed:
                logger.info("  ~ %s (%s) updated", name, prefix)

    db.commit()
    logger.info("✅ Code types seeding complete.")
