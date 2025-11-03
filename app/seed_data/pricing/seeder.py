# seed_data/pricing/seeder.py
from __future__ import annotations

import logging
from typing import List, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application_org.models.company import Company
from app.application_nventory.inventory_models import PriceList, PriceListType
from app.application_pricing.services.price_day_cache import bump_price_list_version
from .data import DEFAULT_PRICE_LISTS

logger = logging.getLogger(__name__)


def _get_company(db: Session, company_id: int) -> Optional[Company]:
    return db.scalar(select(Company).where(Company.id == company_id))


def _find_pl(db: Session, company_id: int, name: str) -> Optional[PriceList]:
    return db.scalar(
        select(PriceList).where(
            PriceList.company_id == company_id,
            PriceList.name == name
        ).limit(1)
    )


def _upsert_pl(
    db: Session,
    company_id: int,
    row: Dict,
) -> tuple[PriceList, bool, bool]:
    """
    Returns: (pl, created, updated)
    - created=True if new row inserted
    - updated=True if existing row changed
    """
    name = row["name"].strip()
    list_type_str = row["list_type"]
    pnu = bool(row.get("price_not_uom_dependent", False))
    active = bool(row.get("is_active", True))

    list_type = PriceListType(list_type_str)  # map "Buying"/"Selling"/"Both"

    existing = _find_pl(db, company_id, name)
    if not existing:
        pl = PriceList(
            company_id=company_id,
            name=name,
            list_type=list_type,
            price_not_uom_dependent=pnu,
            is_active=active,
        )
        db.add(pl)
        db.flush([pl])
        return pl, True, False

    # Update if needed (idempotent)
    changed = False
    if existing.list_type != list_type:
        existing.list_type = list_type; changed = True
    if bool(existing.price_not_uom_dependent) != pnu:
        existing.price_not_uom_dependent = pnu; changed = True
    if bool(existing.is_active) != active:
        existing.is_active = active; changed = True

    if changed:
        db.flush([existing])

    return existing, False, changed


def seed_price_lists(
    db: Session,
    company_id: int,
    rows: Optional[List[Dict]] = None,
) -> None:
    """
    Idempotent seed for default Price Lists:
      - Standard Buying (Buying, PNU=False, Active)
      - Standard Selling (Selling, PNU=False, Active)
    """
    company = _get_company(db, company_id)
    if not company:
        logger.error("Company id=%s not found; skipping Price List seed.", company_id)
        return

    data = rows or DEFAULT_PRICE_LISTS

    created, updated = 0, 0
    touched_pl_ids: List[int] = []

    logger.info("🧾 Seeding Price Lists for company_id=%s ...", company_id)
    try:
        for row in data:
            pl, was_created, was_updated = _upsert_pl(db, company_id, row)
            if was_created:
                created += 1
            if was_updated:
                updated += 1
            touched_pl_ids.append(int(pl.id))

        # bump snapshot versions so caches see new/updated lists immediately
        for pl_id in touched_pl_ids:
            bump_price_list_version(company_id, pl_id)

        db.commit()
        logger.info(
            "✅ Price Lists seed complete (company_id=%s): created=%d, updated=%d",
            company_id, created, updated
        )
    except IntegrityError as e:
        db.rollback()
        logger.exception("Price List seeding failed for company_id=%s", company_id)
        raise RuntimeError(f"Price List seeding failed: {getattr(e, 'orig', e)}")
