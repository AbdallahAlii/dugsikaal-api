# app/inventory/repo.py

from __future__ import annotations
from typing import Optional, List
import logging
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.application_nventory.inventory_models import Brand, UnitOfMeasure, Item, UOMConversion, BranchItemPricing
from config.database import db

from app.application_org.models.company import Company, Branch

log = logging.getLogger(__name__)


class InventoryRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Brand CRUD ---
    def get_brand_by_id(self, brand_id: int) -> Optional[Brand]:
        return self.s.get(Brand, brand_id)

    def get_brand_by_name(self, company_id: int, name: str) -> Optional[Brand]:
        return self.s.scalar(
            select(Brand).where(
                Brand.company_id == company_id,
                func.lower(Brand.name) == func.lower(name)
            )
        )

    def create_brand(self, brand: Brand) -> Brand:
        self.s.add(brand)
        self.s.flush()
        return brand

    def update_brand(self, brand: Brand, updates: dict) -> None:
        for key, value in updates.items():
            setattr(brand, key, value)
        self.s.flush([brand])

    def delete_brand(self, brand_id: int) -> int:
        return self.s.query(Brand).filter(Brand.id == brand_id).delete(synchronize_session='fetch')

    # --- UnitOfMeasure CRUD ---
    def get_uom_by_id(self, uom_id: int) -> Optional[UnitOfMeasure]:
        return self.s.get(UnitOfMeasure, uom_id)

    def get_uom_by_name(self, company_id: int, name: str) -> Optional[UnitOfMeasure]:
        return self.s.scalar(
            select(UnitOfMeasure).where(
                UnitOfMeasure.company_id == company_id,
                func.lower(UnitOfMeasure.name) == func.lower(name)
            )
        )

    def create_uom(self, uom: UnitOfMeasure) -> UnitOfMeasure:
        self.s.add(uom)
        self.s.flush()
        return uom

    def delete_uom(self, uom_id: int) -> int:
        return self.s.query(UnitOfMeasure).filter(UnitOfMeasure.id == uom_id).delete(synchronize_session='fetch')

    # --- Item CRUD ---
    def get_item_by_id(self, item_id: int) -> Optional[Item]:
        return self.s.get(Item, item_id)
    def get_item_by_name(self, company_id: int, name: str) -> Optional[Item]:
        return self.s.scalar(
            select(Item).where(
                Item.company_id == company_id,
                func.lower(Item.name) == func.lower(name)
            )
        )
    def get_item_by_sku(self, company_id: int, sku: str) -> Optional[Item]:
        return self.s.scalar(
            select(Item).where(
                Item.company_id == company_id,
                func.lower(Item.sku) == func.lower(sku)
            )
        )

    def create_item(self, item: Item) -> Item:
        self.s.add(item)
        self.s.flush()
        return item

    def update_item(self, item: Item, updates: dict) -> None:
        for key, value in updates.items():
            setattr(item, key, value)
        self.s.flush([item])

    def delete_item(self, item_id: int) -> int:
        return self.s.query(Item).filter(Item.id == item_id).delete(synchronize_session='fetch')

    # --- UOMConversion CRUD ---
    def create_uom_conversion(self, conversion: UOMConversion) -> UOMConversion:
        self.s.add(conversion)
        self.s.flush()
        return conversion

    def get_uom_conversion_by_ids(self, item_id: int, from_uom_id: int, to_uom_id: int) -> Optional[UOMConversion]:
        return self.s.scalar(
            select(UOMConversion).where(
                UOMConversion.item_id == item_id,
                UOMConversion.from_uom_id == from_uom_id,
                UOMConversion.to_uom_id == to_uom_id
            )
        )

    # --- BranchItemPricing CRUD ---
    def create_branch_item_pricing(self, pricing: BranchItemPricing) -> BranchItemPricing:
        self.s.add(pricing)
        self.s.flush()
        return pricing

    def get_pricing_by_item_branch(self, item_id: int, branch_id: int) -> Optional[BranchItemPricing]:
        return self.s.scalar(
            select(BranchItemPricing).where(
                BranchItemPricing.item_id == item_id,
                BranchItemPricing.branch_id == branch_id
            )
        )

    def update_branch_item_pricing(self, pricing: BranchItemPricing, updates: dict) -> None:
        for key, value in updates.items():
            setattr(pricing, key, value)
        self.s.flush([pricing])