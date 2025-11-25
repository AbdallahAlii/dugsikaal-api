# app/seed_data/subscriptions/seeder.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application_org.models.company import Company
from app.navigation_workspace.models.subscription import (
    ModulePackage,
    CompanyPackageSubscription,
)
from .data import DEFAULT_COMPANY_PACKAGE_SUBSCRIPTIONS

logger = logging.getLogger(__name__)


def _get_or_create(
    db: Session,
    model,
    *,
    defaults: Optional[dict] = None,
    **filters,
) -> Tuple[object, bool]:
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


def seed_company_packages(db: Session) -> None:
    """
    Idempotently seed CompanyPackageSubscription entries based on
    DEFAULT_COMPANY_PACKAGE_SUBSCRIPTIONS.

    Example mapping:
      - company_name: "Haji Technologies"
      - package_slug: "full_suite"
    """
    logger.info("🌱 Seeding Company → Package subscriptions...")

    for spec in DEFAULT_COMPANY_PACKAGE_SUBSCRIPTIONS:
        company_name = spec["company_name"].strip()
        package_slug = spec["package_slug"].strip()

        company = db.scalar(
            select(Company).where(Company.name == company_name)
        )
        if not company:
            logger.warning(
                "Company %r not found; skipping subscription to package %r",
                company_name,
                package_slug,
            )
            continue

        package = db.scalar(
            select(ModulePackage).where(ModulePackage.slug == package_slug)
        )
        if not package:
            logger.warning(
                "ModulePackage slug=%r not found; skipping subscription for company %r",
                package_slug,
                company_name,
            )
            continue

        now_utc = datetime.now(timezone.utc)

        cps, created = _get_or_create(
            db,
            CompanyPackageSubscription,
            company_id=company.id,
            package_id=package.id,
            defaults={
                "is_enabled": True,
                "valid_from": now_utc,
                "valid_until": None,
                "extra": {},
            },
        )

        if created:
            logger.info(
                "✅ Created subscription: company=%s (id=%s) -> package=%s",
                company.name,
                company.id,
                package.slug,
            )
        else:
            # Ensure enabled / sensible defaults on re-run
            changed = False
            if not cps.is_enabled:
                cps.is_enabled = True
                changed = True
            if cps.valid_from is None:
                cps.valid_from = now_utc
                changed = True
            if changed:
                logger.info(
                    "🔄 Updated subscription flags for company=%s (id=%s) -> package=%s",
                    company.name,
                    company.id,
                    package.slug,
                )

    logger.info("✅ Company → Package subscription seeding complete.")
