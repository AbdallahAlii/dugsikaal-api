from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.database import db
from app.application_nventory.inventory_models import PriceList, ItemPrice


class PricingRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # -------- Price List --------
    def get_price_list_by_id(self, pl_id: int) -> Optional[PriceList]:
        return self.s.get(PriceList, pl_id)

    def get_price_list_by_name(self, company_id: int, name: str) -> Optional[PriceList]:
        return self.s.scalar(
            select(PriceList).where(PriceList.company_id == company_id, PriceList.name == name)
        )

    def list_price_lists_by_company(self, company_id: int) -> List[PriceList]:
        return list(self.s.scalars(
            select(PriceList).where(PriceList.company_id == company_id).order_by(PriceList.name.asc())
        ))

    def create_price_list(self, pl: PriceList) -> PriceList:
        self.s.add(pl)
        self.s.flush([pl])
        return pl

    def update_price_list(self, pl: PriceList, updates: dict) -> None:
        for k, v in updates.items():
            setattr(pl, k, v)
        self.s.flush([pl])

    # -------- Item Price --------
    def get_item_price_by_id(self, ip_id: int) -> Optional[ItemPrice]:
        return self.s.get(ItemPrice, ip_id)

    def get_item_price_by_code(self, company_id: int, code: str) -> Optional[ItemPrice]:
        return self.s.scalar(
            select(ItemPrice).where(ItemPrice.company_id == company_id, ItemPrice.code == code)
        )

    def item_price_code_exists(self, company_id: int, code: str) -> bool:
        return self.get_item_price_by_code(company_id, code) is not None

    def find_duplicate_item_price(
        self,
        *,
        price_list_id: int,
        item_id: int,
        uom_id: Optional[int],
        branch_id: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> Optional[ItemPrice]:
        q = select(ItemPrice).where(
            ItemPrice.price_list_id == price_list_id,
            ItemPrice.item_id == item_id,
            (ItemPrice.uom_id == uom_id) if uom_id is not None else ItemPrice.uom_id.is_(None),
            (ItemPrice.branch_id == branch_id) if branch_id is not None else ItemPrice.branch_id.is_(None),
        )
        if exclude_id:
            q = q.where(ItemPrice.id != exclude_id)
        return self.s.scalar(q)

    def create_item_price(self, ip: ItemPrice) -> ItemPrice:
        self.s.add(ip)
        self.s.flush([ip])
        return ip

    def update_item_price(self, ip: ItemPrice, updates: dict) -> None:
        for k, v in updates.items():
            setattr(ip, k, v)
        self.s.flush([ip])
