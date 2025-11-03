from __future__ import annotations
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_, or_, desc
from sqlalchemy.orm import Session

from config.database import db
from app.common.models.base import StatusEnum
from app.application_nventory.inventory_models import Item, PriceList, ItemPrice, ItemTypeEnum, PriceListType

log = logging.getLogger(__name__)

DEC4 = Decimal("0.0001")
def _q4(v) -> Decimal:
    return (Decimal(str(v or 0))).quantize(DEC4)


class PricingRepository:
    """DB reads for pricing (no UOM conversion)."""
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Item core ---
    def get_item_core(self, company_id: int, item_id: int) -> dict | None:
        row = self.s.execute(
            select(Item.item_type, Item.base_uom_id, Item.status)
            .where(Item.company_id == company_id, Item.id == item_id)
        ).first()
        if not row:
            return None
        out = {
            "is_stock_item": row.item_type == ItemTypeEnum.STOCK_ITEM,
            "base_uom_id": row.base_uom_id,
            "is_active": row.status == StatusEnum.ACTIVE,
        }
        log.debug("get_item_core: %s", out)
        return out

    # --- Price List by id or name ---
    def get_price_list(self, company_id: int, *, price_list_id: Optional[int], price_list_name: Optional[str]) -> dict | None:
        q = select(
            PriceList.id, PriceList.price_not_uom_dependent, PriceList.is_active, PriceList.list_type
        ).where(PriceList.company_id == company_id)
        if price_list_id:
            q = q.where(PriceList.id == price_list_id)
        elif price_list_name:
            q = q.where(PriceList.name == price_list_name)
        else:
            return None
        row = self.s.execute(q).first()
        if not row:
            return None
        out = {"id": int(row.id), "pnu": bool(row.price_not_uom_dependent), "active": bool(row.is_active), "type": row.list_type}
        log.debug("get_price_list: %s", out)
        return out

    # --- Validity clause helper ---
    def _validity_filter(self, at: Optional[datetime]):
        now = at or datetime.utcnow()
        return and_(
            or_(ItemPrice.valid_from.is_(None), ItemPrice.valid_from <= now),
            or_(ItemPrice.valid_upto.is_(None), ItemPrice.valid_upto >= now),
        )

    # --- Pick one row with precedence helper (now with ANY-BRANCH fallback) ---
    def _pick_one(self, base_q, prefer_branch: Optional[int], source_tag: str):
        """
        Precedence:
          If prefer_branch is not None: branch → global → any-branch
          If prefer_branch is None:     global → any-branch
        """
        def _one(q):
            return self.s.execute(q.limit(1)).first()

        # explicit branch first
        if prefer_branch is not None:
            r = _one(base_q.where(ItemPrice.branch_id == prefer_branch))
            if r:
                return {"rate": _q4(r.rate), "uom_id": r.uom_id, "branch_override": True, "source": f"{source_tag}_branch"}

            # then global
            r = _one(base_q.where(ItemPrice.branch_id.is_(None)))
            if r:
                return {"rate": _q4(r.rate), "uom_id": r.uom_id, "branch_override": False, "source": f"{source_tag}_global"}

            # finally ANY branch
            r = _one(base_q.where(ItemPrice.branch_id.is_not(None)))
            if r:
                return {"rate": _q4(r.rate), "uom_id": r.uom_id, "branch_override": True, "source": f"{source_tag}_any_branch"}

            return None

        # prefer_branch is None → global then ANY branch
        r = _one(base_q.where(ItemPrice.branch_id.is_(None)))
        if r:
            return {"rate": _q4(r.rate), "uom_id": r.uom_id, "branch_override": False, "source": f"{source_tag}_global"}

        r = _one(base_q.where(ItemPrice.branch_id.is_not(None)))
        if r:
            return {"rate": _q4(r.rate), "uom_id": r.uom_id, "branch_override": True, "source": f"{source_tag}_any_branch"}

        return None

    # --- SQL finder (NO UOM conversion) ---
    def find_item_price(
        self,
        *,
        company_id: int,
        item_id: int,
        price_list_id: int,
        branch_id: Optional[int],
        uom_id: Optional[int],
        at: Optional[datetime],
        pnu: bool,  # price_not_uom_dependent
    ) -> dict | None:
        """
        Selection (no conversion):
        - If branch_id is None => global first, then ANY branch.
        - If branch_id is set    => branch first, then global, then ANY branch.
        - If pnu=True            => prefer NULL uom_id rows; else follow uom preference if provided.
        - If a preferred row isn't found, fall back to ANY UOM with same branch precedence.
        Returns: {"rate": Decimal, "uom_id": Optional[int], "branch_override": bool, "source": str}
        """
        vf = self._validity_filter(at)

        base = (
            select(ItemPrice.rate, ItemPrice.uom_id, ItemPrice.branch_id)
            .where(ItemPrice.price_list_id == price_list_id, ItemPrice.item_id == item_id, vf)
            .order_by(desc(ItemPrice.valid_from).nullslast(), desc(ItemPrice.id))
        )

        if pnu:
            res = self._pick_one(base.where(ItemPrice.uom_id.is_(None)), branch_id, "NULL-UOM")
            if res:
                log.debug("find_item_price: PNU prefer NULL-UOM %s", res)
                return res
            if uom_id is not None:
                res = self._pick_one(base.where(ItemPrice.uom_id == uom_id), branch_id, "EXACT-UOM")
                if res:
                    log.debug("find_item_price: PNU exact UOM %s", res)
                    return res
            res = self._pick_one(base, branch_id, "ANY-UOM")
            if res:
                log.debug("find_item_price: PNU any UOM %s", res)
                return res
            log.debug("find_item_price: MISS (PNU)")
            return None

        # UOM-dependent
        if uom_id is not None:
            res = self._pick_one(base.where(ItemPrice.uom_id == uom_id), branch_id, "EXACT-UOM")
            if res:
                log.debug("find_item_price: EXACT-UOM %s", res)
                return res

        res = self._pick_one(base, branch_id, "ANY-UOM")
        if res:
            log.debug("find_item_price: ANY-UOM %s", res)
            return res

        log.debug("find_item_price: MISS")
        return None
