# app/application_pricing/repo/pricing_master_repo.py
from __future__ import annotations
from typing import Optional, Tuple
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session

from config.database import db
from app.common.models.base import StatusEnum
from app.application_nventory.inventory_models import (
    PriceList, ItemPrice, Item, UnitOfMeasure, UOMConversion
)

DEC4 = Decimal("0.0001")


class PricingMasterRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --------- save / flush ----------
    def save(self, obj):
        if obj not in self.s:
            self.s.add(obj)
        self.s.flush([obj])
        return obj

    # --------- company from branch (defensive import) ----------
    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        try:
            from app.application_org.models.company import Branch  # canonical path
        except Exception:  # legacy fallback
            try:
                from app import Branch  # type: ignore
            except Exception:
                return None
        return self.s.execute(select(Branch.company_id).where(Branch.id == branch_id)).scalar_one_or_none()

    # --------- PriceList lookups ----------
    def price_list_by_id(self, company_id: int, pl_id: int) -> Optional[PriceList]:
        return self.s.execute(
            select(PriceList).where(PriceList.company_id == company_id, PriceList.id == pl_id)
        ).scalar_one_or_none()

    def price_list_by_name(self, company_id: int, name: str) -> Optional[PriceList]:
        return self.s.execute(
            select(PriceList).where(
                PriceList.company_id == company_id,
                func.lower(PriceList.name) == func.lower((name or "").strip())
            )
        ).scalar_one_or_none()

    def price_list_name_exists(self, company_id: int, name: str, *, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            PriceList.company_id == company_id,
            func.lower(PriceList.name) == func.lower((name or "").strip())
        ))
        if exclude_id:
            stmt = stmt.where(PriceList.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    # --------- Item / UOM checks ----------
    def item_core(self, company_id: int, item_id: int) -> Optional[Tuple[bool, Optional[int]]]:
        row = self.s.execute(
            select(Item.status, Item.base_uom_id).where(Item.company_id == company_id, Item.id == item_id)
        ).first()
        if not row:
            return None
        return (row.status == StatusEnum.ACTIVE, row.base_uom_id)

    def uom_exists(self, company_id: int, uom_id: int) -> bool:
        return bool(self.s.execute(
            select(exists().where(UnitOfMeasure.company_id == company_id,
                                  UnitOfMeasure.id == uom_id,
                                  UnitOfMeasure.status == StatusEnum.ACTIVE))
        ).scalar())

    def uom_compatible_with_item(self, item_id: int, uom_id: int, base_uom_id: Optional[int]) -> bool:
        if base_uom_id and uom_id == base_uom_id:
            return True
        ok = self.s.execute(
            select(exists().where(UOMConversion.item_id == item_id,
                                  UOMConversion.uom_id == uom_id,
                                  UOMConversion.is_active == True))  # noqa: E712
        ).scalar()
        return bool(ok)

    # --------- ItemPrice fetch ----------
    def item_price_by_id(self, ip_id: int) -> Optional[ItemPrice]:
        return self.s.execute(select(ItemPrice).where(ItemPrice.id == ip_id)).scalar_one_or_none()

    def item_price_code_exists(self, company_id: int, code: str) -> bool:
        return bool(self.s.execute(
            select(exists().where(ItemPrice.company_id == company_id, ItemPrice.code == code))
        ).scalar())

    def duplicate_item_price_exists(
        self, *, price_list_id: int, item_id: int,
        uom_id: Optional[int], branch_id: Optional[int],
        exclude_id: Optional[int] = None
    ) -> bool:
        stmt = select(exists().where(
            ItemPrice.price_list_id == price_list_id,
            ItemPrice.item_id == item_id,
            (ItemPrice.uom_id == uom_id) if uom_id is not None else ItemPrice.uom_id.is_(None),
            (ItemPrice.branch_id == branch_id) if branch_id is not None else ItemPrice.branch_id.is_(None),
        ))
        if exclude_id:
            stmt = stmt.where(ItemPrice.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    # --------- validity predicate ----------
    @staticmethod
    def validity_ok(valid_from: Optional[datetime], valid_upto: Optional[datetime]) -> bool:
        if valid_from and valid_upto and valid_from > valid_upto:
            return False
        return True
