# # # app/application_buying/invoice_repo.py

from __future__ import annotations
from typing import Optional, List, Dict, Set, Tuple
from decimal import Decimal
from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session, selectinload, aliased

from config.database import db
from app.common.models.base import StatusEnum
from app.application_buying.models import PurchaseInvoice, PurchaseInvoiceItem, PurchaseReceipt
from app.application_nventory.inventory_models import Item, ItemTypeEnum, UnitOfMeasure, UOMConversion
from app.application_stock.stock_models import DocStatusEnum, Warehouse
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_org.models.company import Branch


class PurchaseInvoiceRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_by_id(self, invoice_id: int, for_update: bool = False) -> Optional[PurchaseInvoice]:
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items))
            .where(PurchaseInvoice.id == invoice_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def get_original_for_return(self, invoice_id: int) -> Optional[PurchaseInvoice]:
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items).selectinload(PurchaseInvoiceItem.item))
            .where(
                PurchaseInvoice.id == invoice_id,
                PurchaseInvoice.doc_status == DocStatusEnum.SUBMITTED,
                PurchaseInvoice.is_return == False,
            )
            .with_for_update()
        )
        return self.s.execute(stmt).scalar_one_or_none()


    def get_receipt_with_items(self, receipt_id: int) -> Optional[PurchaseReceipt]:
        return self.s.execute(
            select(PurchaseReceipt)
            .options(selectinload(PurchaseReceipt.items))
            .where(PurchaseReceipt.id == receipt_id, PurchaseReceipt.doc_status == DocStatusEnum.SUBMITTED)
        ).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(
            exists().where(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.branch_id == branch_id,
                func.lower(PurchaseInvoice.code) == func.lower(code)
            )
        )
        if exclude_id:
            stmt = stmt.where(PurchaseInvoice.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    def save(self, pi: PurchaseInvoice) -> PurchaseInvoice:
        if pi not in self.s:
            self.s.add(pi)
        self.s.flush()
        return pi

    def sync_lines(self, pi: PurchaseInvoice, lines_data: List[Dict]) -> None:
        existing = {ln.id: ln for ln in pi.items}
        keep: Set[int] = set()
        for data in lines_data:
            lid = data.get("id")
            if lid and lid in existing:
                line = existing[lid]
                for k, v in data.items():
                    if hasattr(line, k) and k != "id":
                        setattr(line, k, v)
                keep.add(lid)
            else:
                self.s.add(PurchaseInvoiceItem(invoice_id=pi.id, **data))
        for lid, line in existing.items():
            if lid not in keep:
                self.s.delete(line)

    # master data
    def get_valid_supplier_ids(self, company_id: int, supplier_ids: List[int]) -> Set[int]:
        if not supplier_ids:
            return set()
        stmt = select(Party.id).where(
            Party.id.in_(supplier_ids),
            Party.company_id == company_id,
            Party.role == PartyRoleEnum.SUPPLIER,
            Party.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        if not warehouse_ids:
            return set()
        W2 = aliased(Warehouse)
        has_child = exists(select(1).where(W2.parent_warehouse_id == Warehouse.id))
        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~has_child,
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        if not item_ids:
            return {}
        rows = self.s.execute(
            select(Item.id, Item.status, Item.item_type, Item.base_uom_id)
            .where(Item.id.in_(item_ids), Item.company_id == company_id)
        ).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id,
            } for r in rows
        }

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        if not uom_ids:
            return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_compatible_uom_pairs(self, company_id: int, pairs: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        if not pairs:
            return set()
        item_ids = {p[0] for p in pairs}
        base_map = dict(self.s.execute(select(Item.id, Item.base_uom_id).where(Item.id.in_(item_ids))).all())
        conv_rows = self.s.execute(
            select(UOMConversion.item_id, UOMConversion.uom_id)
            .where(UOMConversion.item_id.in_(item_ids), UOMConversion.is_active == True)
        ).all()
        valid = {(r.item_id, r.uom_id) for r in conv_rows}
        out: Set[Tuple[int, int]] = set()
        for item_id, uom_id in pairs:
            base_uom = base_map.get(item_id)
            if base_uom and (uom_id == base_uom or (item_id, uom_id) in valid):
                out.add((item_id, uom_id))
        return out

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        return self.s.execute(select(Branch.company_id).where(Branch.id == branch_id)).scalar_one_or_none()
    def recalc_total(self, pi: PurchaseInvoice) -> None:
        total = sum((ln.amount or 0) for ln in pi.items)
        pi.total_amount = total
        # keep outstanding consistent while draft
        pi.outstanding_amount = total - (pi.paid_amount or 0)
        self.s.flush()
