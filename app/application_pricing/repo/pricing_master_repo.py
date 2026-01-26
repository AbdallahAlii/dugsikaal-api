from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, exists, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_nventory.inventory_models import (
    PriceList, ItemPrice, Item, UnitOfMeasure, UOMConversion, PriceListType
)
from app.application_org.models.company import Branch


class PricingMasterRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def save(self, obj):
        if obj not in self.s:
            self.s.add(obj)
        self.s.flush([obj])
        return obj

    # -----------------------
    # Branch / Company
    # -----------------------
    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        return self.s.scalar(select(Branch.company_id).where(Branch.id == int(branch_id)))

    # -----------------------
    # Price List
    # -----------------------
    def get_price_list_by_id(self, *, company_id: int, price_list_id: int) -> Optional[PriceList]:
        return self.s.scalar(
            select(PriceList).where(
                PriceList.company_id == int(company_id),
                PriceList.id == int(price_list_id),
            )
        )

    def price_list_name_exists(self, *, company_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        nm = (name or "").strip()
        if not nm:
            return False

        q = exists().where(
            PriceList.company_id == int(company_id),
            func.lower(PriceList.name) == func.lower(nm),
        )
        if exclude_id:
            q = q.where(PriceList.id != int(exclude_id))
        return bool(self.s.scalar(select(q)))

    def default_price_list_exists(self, *, company_id: int, list_type: PriceListType, exclude_id: Optional[int]) -> bool:
        if list_type in (PriceListType.SELLING, PriceListType.BOTH):
            lt_set = (PriceListType.SELLING, PriceListType.BOTH)
        else:
            lt_set = (PriceListType.BUYING, PriceListType.BOTH)

        q = exists().where(
            PriceList.company_id == int(company_id),
            PriceList.is_default.is_(True),
            PriceList.is_active.is_(True),
            PriceList.list_type.in_(lt_set),
        )
        if exclude_id:
            q = q.where(PriceList.id != int(exclude_id))
        return bool(self.s.scalar(select(q)))

    # -----------------------
    # Item / UOM checks - UPDATED for ERPNext style
    # -----------------------
    def get_item_base_uom_id(self, *, company_id: int, item_id: int) -> Optional[int]:
        """Get item's base UOM ID - returns None if item doesn't exist OR if base_uom_id is NULL."""
        return self.s.scalar(
            select(Item.base_uom_id).where(
                Item.company_id == int(company_id),
                Item.id == int(item_id),
            )
        )

    def item_exists_and_belongs_to_company(self, *, company_id: int, item_id: int) -> bool:
        """Check if item exists and belongs to company - proper validation."""
        q = exists().where(
            Item.company_id == int(company_id),
            Item.id == int(item_id),
        )
        return bool(self.s.scalar(select(q)))

    def uom_belongs_to_company(self, *, company_id: int, uom_id: int) -> bool:
        q = exists().where(
            UnitOfMeasure.company_id == int(company_id),
            UnitOfMeasure.id == int(uom_id),
        )
        return bool(self.s.scalar(select(q)))

    def uom_conversion_exists(self, *, item_id: int, uom_id: int) -> bool:
        """Check if UOM conversion exists for item (active conversion)."""
        q = exists().where(
            UOMConversion.item_id == int(item_id),
            UOMConversion.uom_id == int(uom_id),
            UOMConversion.is_active.is_(True),
        )
        return bool(self.s.scalar(select(q)))

    def get_item_type(self, *, company_id: int, item_id: int) -> Optional[str]:
        """Get item type (STOCK_ITEM, SERVICE, etc.)."""
        return self.s.scalar(
            select(Item.item_type).where(
                Item.company_id == int(company_id),
                Item.id == int(item_id),
            )
        )

    # -----------------------
    # Item Price
    # -----------------------
    def get_item_price_by_id(self, *, item_price_id: int) -> Optional[ItemPrice]:
        return self.s.scalar(select(ItemPrice).where(ItemPrice.id == int(item_price_id)))

    def item_price_code_exists(self, *, company_id: int, code: str) -> bool:
        q = exists().where(
            ItemPrice.company_id == int(company_id),
            ItemPrice.code == str(code),
        )
        return bool(self.s.scalar(select(q)))

    def item_price_overlaps(
        self,
        *,
        company_id: int,
        price_list_id: int,
        item_id: int,
        branch_id: Optional[int],
        uom_id: Optional[int],
        valid_from_utc: Optional[datetime],
        valid_upto_utc: Optional[datetime],
        exclude_id: Optional[int] = None,
    ) -> bool:
        conds = [
            ItemPrice.company_id == int(company_id),
            ItemPrice.price_list_id == int(price_list_id),
            ItemPrice.item_id == int(item_id),
            ItemPrice.branch_id == (int(branch_id) if branch_id is not None else None),
            ItemPrice.uom_id == (int(uom_id) if uom_id is not None else None),
            (True if valid_from_utc is None else or_(ItemPrice.valid_upto.is_(None), ItemPrice.valid_upto >= valid_from_utc)),
            (True if valid_upto_utc is None else or_(ItemPrice.valid_from.is_(None), ItemPrice.valid_from <= valid_upto_utc)),
        ]

        q = exists().where(*conds)
        if exclude_id:
            q = q.where(ItemPrice.id != int(exclude_id))
        return bool(self.s.scalar(select(q)))