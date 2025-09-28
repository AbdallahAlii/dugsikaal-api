# app/application_sales/repository/delivery_note_repo.py
from __future__ import annotations

from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime

from sqlalchemy import select, exists, and_, func
from sqlalchemy.orm import Session, aliased, selectinload

from config.database import db
from app.common.models.base import StatusEnum
from app.application_stock.stock_models import (
    Warehouse, DocStatusEnum, StockLedgerEntry, DocumentType
)
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_nventory.inventory_models import (
    Item, ItemTypeEnum, UnitOfMeasure, UOMConversion
)
from app.application_sales.models import SalesDeliveryNote, SalesDeliveryNoteItem


class SalesDeliveryNoteRepository:
    """
    Data Access + Lookups for Sales Delivery Notes (mirrors purchase receipt repo pattern).
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # -------------------- Document read/write ops --------------------

    def get_by_id(self, sdn_id: int, for_update: bool = False) -> Optional[SalesDeliveryNote]:
        stmt = (
            select(SalesDeliveryNote)
            .options(selectinload(SalesDeliveryNote.items))
            .where(SalesDeliveryNote.id == sdn_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            SalesDeliveryNote.company_id == company_id,
            SalesDeliveryNote.branch_id == branch_id,
            func.lower(SalesDeliveryNote.code) == func.lower(code),
        ))
        if exclude_id:
            stmt = stmt.where(SalesDeliveryNote.id != exclude_id)
        return self.s.execute(stmt).scalar()

    def save(self, sdn: SalesDeliveryNote) -> SalesDeliveryNote:
        if sdn not in self.s:
            self.s.add(sdn)
        self.s.flush()
        return sdn

    def sync_lines(self, sdn: SalesDeliveryNote, lines_data: List[Dict]) -> None:
        existing = {ln.id: ln for ln in sdn.items}
        keep: Set[int] = set()

        for data in lines_data:
            line_id = data.get("id")
            if line_id and line_id in existing:
                row = existing[line_id]
                for k, v in data.items():
                    if hasattr(row, k):
                        setattr(row, k, v)
                keep.add(line_id)
            else:
                self.s.add(SalesDeliveryNoteItem(delivery_note_id=sdn.id, **data))

        for line_id in set(existing.keys()) - keep:
            self.s.delete(existing[line_id])

    def get_doc_type_id_by_code(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise ValueError(f"DocumentType '{code}' not found.")
        return dt

    def has_future_sle(self, company_id: int, posting_dt: datetime, pairs: Set[Tuple[int, int]]) -> bool:
        """
        Return True if any future SLE exists after posting_dt for the given (item_id, warehouse_id) pairs.
        """
        if not pairs:
            return False

        def _has_future(item_id: int, wh_id: int) -> bool:
            q = self.s.query(StockLedgerEntry.id).filter(
                StockLedgerEntry.company_id == company_id,
                StockLedgerEntry.item_id == item_id,
                StockLedgerEntry.warehouse_id == wh_id,
                (
                    (StockLedgerEntry.posting_date > posting_dt.date()) |
                    and_(
                        StockLedgerEntry.posting_date == posting_dt.date(),
                        StockLedgerEntry.posting_time > posting_dt,
                    )
                ),
                StockLedgerEntry.is_cancelled == False,  # noqa: E712
            ).limit(1)
            return self.s.query(q.exists()).scalar()

        return any(_has_future(item_id, wh_id) for (item_id, wh_id) in pairs)

    # -------------------- Canonicalization helper --------------------

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        from app.application_org.models.company import Branch
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()

    # -------------------- Party / Warehouse lookups --------------------

    def get_valid_customer_ids(self, company_id: int, party_ids: List[int]) -> Set[int]:
        if not party_ids:
            return set()
        stmt = select(Party.id).where(
            Party.id.in_(party_ids),
            Party.company_id == company_id,
            Party.role == PartyRoleEnum.CUSTOMER,
            Party.status == StatusEnum.ACTIVE,
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        if not warehouse_ids:
            return set()

        W_child = aliased(Warehouse)
        child_exists = exists(select(1).where(W_child.parent_warehouse_id == Warehouse.id))

        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~child_exists,  # leaf/transactional only
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    # -------------------- Item / UOM lookups --------------------

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        if not item_ids:
            return {}
        stmt = select(Item.id, Item.status, Item.item_type, Item.base_uom_id).where(
            Item.id.in_(item_ids),
            Item.company_id == company_id,
        )
        rows = self.s.execute(stmt).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id,
            }
            for r in rows
        }

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        if not uom_ids:
            return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE,
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_compatible_uom_pairs(self, company_id: int, pairs: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        if not pairs:
            return set()

        item_ids = {p[0] for p in pairs}
        item_stmt = select(Item.id, Item.base_uom_id).where(Item.id.in_(item_ids))
        base_uom_map = dict(self.s.execute(item_stmt).all())

        conv_stmt = select(
            UOMConversion.item_id,
            UOMConversion.from_uom_id,
            UOMConversion.to_uom_id
        ).where(UOMConversion.item_id.in_(item_ids))
        conversions = {(c.item_id, c.from_uom_id, c.to_uom_id) for c in self.s.execute(conv_stmt).all()}

        compatible: Set[Tuple[int, int]] = set()
        for item_id, uom_id in pairs:
            base_uom_id = base_uom_map.get(item_id)
            if not base_uom_id:
                continue
            if (
                uom_id == base_uom_id or
                (item_id, base_uom_id, uom_id) in conversions or
                (item_id, uom_id, base_uom_id) in conversions
            ):
                compatible.add((item_id, uom_id))
        return compatible
