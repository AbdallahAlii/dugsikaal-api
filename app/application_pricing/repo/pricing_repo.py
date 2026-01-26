from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, List, Tuple

import sqlalchemy as sa
from sqlalchemy import select, and_, or_, desc, case, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import array as pg_array

from config.database import db
from app.common.models.base import StatusEnum
from app.application_nventory.inventory_models import (
    Item, PriceList, ItemPrice, ItemTypeEnum, PriceListType, UOMConversion
)
from app.application_stock.stock_models import Bin, StockLedgerEntry, DocStatusEnum

log = logging.getLogger(__name__)
DEC4 = Decimal("0.0001")


class PricingRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_item_core_bulk(self, *, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        if not item_ids:
            return {}
        rows = self.s.execute(
            select(Item.id, Item.item_type, Item.base_uom_id, Item.status)
            .where(Item.company_id == company_id, Item.id.in_(item_ids))
        ).all()
        out: Dict[int, Dict] = {}
        for r in rows:
            out[int(r.id)] = {
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": int(r.base_uom_id) if r.base_uom_id is not None else None,
                "is_active": r.status == StatusEnum.ACTIVE,
            }
        return out

    def get_price_list(self, company_id: int, *, price_list_id: Optional[int], price_list_name: Optional[str]) -> dict | None:
        q = select(
            PriceList.id,
            PriceList.price_not_uom_dependent,
            PriceList.is_active,
            PriceList.list_type,
            PriceList.is_default,
        ).where(PriceList.company_id == company_id)

        if price_list_id:
            q = q.where(PriceList.id == int(price_list_id))
        elif price_list_name:
            q = q.where(PriceList.name == str(price_list_name))
        else:
            return None

        row = self.s.execute(q).first()
        if not row:
            return None
        return {
            "id": int(row.id),
            "pnu": bool(row.price_not_uom_dependent),
            "active": bool(row.is_active),
            "type": row.list_type,
            "is_default": bool(row.is_default),
        }

    def resolve_company_default_price_list_id(self, company_id: int, target: PriceListType) -> Optional[int]:
        q = (
            select(PriceList.id)
            .where(
                PriceList.company_id == company_id,
                PriceList.is_active.is_(True),
                PriceList.list_type.in_([target, PriceListType.BOTH]),
            )
            .order_by(desc(PriceList.is_default), PriceList.id.asc())
            .limit(1)
        )
        row = self.s.execute(q).first()
        return int(row[0]) if row else None

    def get_uom_factor(self, *, item_id: int, txn_uom_id: int) -> Decimal:
        row = self.s.execute(
            select(UOMConversion.conversion_factor)
            .where(
                UOMConversion.item_id == int(item_id),
                UOMConversion.uom_id == int(txn_uom_id),
                UOMConversion.is_active.is_(True),
            )
        ).first()
        return Decimal(str(row[0])) if row else Decimal("1")

    def _validity_filter(self, at: Optional[datetime]):
        now = at or datetime.utcnow()
        return and_(
            or_(ItemPrice.valid_from.is_(None), ItemPrice.valid_from <= now),
            or_(ItemPrice.valid_upto.is_(None), ItemPrice.valid_upto >= now),
        )

    def find_item_prices_best_bulk(
        self,
        *,
        company_id: int,
        price_list_id: int,
        branch_id: Optional[int],
        when: datetime,
        lines: List[object],
        price_not_uom_dependent: bool,
        core_map: Dict[int, Dict],
    ) -> List[Dict]:
        if not lines:
            return []

        vf = self._validity_filter(when)

        req_rows = [
            (str(ln.row_id), int(ln.item_id), int(ln.uom_id) if ln.uom_id is not None else None)
            for ln in lines
        ]

        row_ids = [r[0] for r in req_rows]
        item_ids = [r[1] for r in req_rows]
        txn_uoms = [r[2] for r in req_rows]

        req = select(
            func.unnest(pg_array(row_ids, type_=sa.Text())).label("row_id"),
            func.unnest(pg_array(item_ids, type_=sa.Integer())).label("item_id"),
            func.unnest(pg_array(txn_uoms, type_=sa.Integer())).label("txn_uom_id"),
        ).subquery("req")

        if branch_id is None:
            branch_filter = ItemPrice.branch_id.is_(None)
            branch_rank = case((ItemPrice.branch_id.is_(None), 0), else_=99)
        else:
            branch_filter = or_(ItemPrice.branch_id == int(branch_id), ItemPrice.branch_id.is_(None))
            branch_rank = case(
                (ItemPrice.branch_id == int(branch_id), 0),
                (ItemPrice.branch_id.is_(None), 1),
                else_=99,
            )

        uom_rank = case(
            (ItemPrice.uom_id == req.c.txn_uom_id, 0),
            (ItemPrice.uom_id.is_(None), 1),
            else_=2,
        )

        if price_not_uom_dependent:
            uom_filter = or_(ItemPrice.uom_id == req.c.txn_uom_id, ItemPrice.uom_id.is_(None))
        else:
            uom_filter = sa.true()

        cand = (
            select(
                req.c.row_id,
                ItemPrice.item_id,
                ItemPrice.rate,
                ItemPrice.uom_id.label("stored_uom_id"),
                ItemPrice.valid_from,
                ItemPrice.id.label("ip_id"),
                branch_rank.label("branch_rank"),
                uom_rank.label("uom_rank"),
                func.row_number().over(
                    partition_by=req.c.row_id,
                    order_by=(
                        branch_rank,
                        uom_rank,
                        desc(ItemPrice.valid_from).nullslast(),
                        desc(ItemPrice.id),
                    ),
                ).label("rn"),
            )
            .select_from(req)
            .join(
                ItemPrice,
                and_(
                    ItemPrice.company_id == company_id,
                    ItemPrice.price_list_id == price_list_id,
                    ItemPrice.item_id == req.c.item_id,
                    vf,
                    branch_filter,
                    uom_filter,
                ),
            )
        ).subquery("cand")

        best = select(cand.c.row_id, cand.c.item_id, cand.c.rate, cand.c.stored_uom_id).where(cand.c.rn == 1)
        rows = self.s.execute(best).all()

        txn_map = {r[0]: r[2] for r in req_rows}
        out: List[Dict] = []

        for row_id, item_id, rate, stored_uom_id in rows:
            core = core_map.get(int(item_id)) or {}
            base_uom_id = int(core.get("base_uom_id") or 0)
            txn_uom_id = txn_map.get(str(row_id)) or base_uom_id

            rr = float(rate)

            if stored_uom_id is None and txn_uom_id and base_uom_id and txn_uom_id != base_uom_id:
                factor = self.get_uom_factor(item_id=int(item_id), txn_uom_id=int(txn_uom_id))
                rr = rr * float(factor)

            out.append({
                "row_id": str(row_id),
                "item_id": int(item_id),
                "uom_id": int(txn_uom_id) if txn_uom_id else None,
                "rate": float(rr),
                "source": "item_price",
            })

        return out

    # ---------------- Buying fallbacks ----------------

    def get_last_purchase_rate(self, *, company_id: int, item_id: int, branch_id: Optional[int], warehouse_id: Optional[int]) -> Optional[Decimal]:
        q = select(StockLedgerEntry.incoming_rate).where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.is_cancelled.is_(False),
            StockLedgerEntry.actual_qty > 0,
            StockLedgerEntry.incoming_rate.is_not(None),
        )

        if warehouse_id is not None:
            q = q.where(StockLedgerEntry.warehouse_id == int(warehouse_id))
        elif branch_id is not None:
            q = q.where(StockLedgerEntry.branch_id == int(branch_id))

        q = q.order_by(StockLedgerEntry.posting_time.desc(), StockLedgerEntry.id.desc()).limit(1)
        row = self.s.execute(q).first()
        return Decimal(str(row[0])) if row and row[0] is not None else None

    def get_valuation_rate_from_bin(self, *, company_id: int, item_id: int, branch_id: Optional[int], warehouse_id: Optional[int]) -> Optional[Decimal]:
        q = select(Bin.valuation_rate).where(Bin.company_id == company_id, Bin.item_id == item_id)

        if warehouse_id is not None:
            row = self.s.execute(q.where(Bin.warehouse_id == int(warehouse_id)).limit(1)).first()
            return Decimal(str(row[0])) if row and row[0] is not None else None

        row = self.s.execute(q.order_by(Bin.actual_qty.desc(), Bin.id.desc()).limit(1)).first()
        return Decimal(str(row[0])) if row and row[0] is not None else None

    # ---------------- Selling fallback ----------------

    def get_last_selling_rate(self, *, company_id: int, item_id: int, branch_id: Optional[int]) -> Optional[Tuple[Decimal, Optional[int]]]:
        # Import inside to avoid circular imports
        from app.application_selling.models import SalesInvoice, SalesInvoiceItem

        def _query_for_status(status: DocStatusEnum, use_branch: bool):
            q = (
                select(SalesInvoiceItem.rate, SalesInvoiceItem.uom_id)
                .join(SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id)
                .where(
                    SalesInvoice.company_id == company_id,
                    SalesInvoiceItem.item_id == item_id,
                    SalesInvoice.is_return.is_(False),
                    SalesInvoice.doc_status == status,
                    SalesInvoiceItem.rate.is_not(None),
                    SalesInvoiceItem.quantity > 0,
                )
            )
            if use_branch and branch_id is not None:
                q = q.where(SalesInvoice.branch_id == int(branch_id))
            return q.order_by(SalesInvoice.posting_date.desc(), SalesInvoice.id.desc(), SalesInvoiceItem.id.desc()).limit(1)

        # 1) Submitted + branch (best)
        if branch_id is not None:
            row = self.s.execute(_query_for_status(DocStatusEnum.SUBMITTED, use_branch=True)).first()
            if row and row[0] is not None:
                return (Decimal(str(row[0])), int(row[1]) if row[1] is not None else None)

            # 2) Draft + branch (helpful in your workflow)
            row = self.s.execute(_query_for_status(DocStatusEnum.DRAFT, use_branch=True)).first()
            if row and row[0] is not None:
                return (Decimal(str(row[0])), int(row[1]) if row[1] is not None else None)

        # 3) Submitted without branch (company-wide)
        row = self.s.execute(_query_for_status(DocStatusEnum.SUBMITTED, use_branch=False)).first()
        if row and row[0] is not None:
            return (Decimal(str(row[0])), int(row[1]) if row[1] is not None else None)

        # 4) Draft without branch
        row = self.s.execute(_query_for_status(DocStatusEnum.DRAFT, use_branch=False)).first()
        if row and row[0] is not None:
            return (Decimal(str(row[0])), int(row[1]) if row[1] is not None else None)

        return None
