from __future__ import annotations
from typing import Optional, List, Dict, Set, Tuple
from decimal import Decimal
from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session, selectinload, joinedload, aliased

from config.database import db
from app.common.models.base import StatusEnum
from app.application_stock.stock_models import DocStatusEnum, DocumentType, Warehouse
from app.application_nventory.inventory_models import Item, ItemTypeEnum, UnitOfMeasure, UOMConversion, ItemGroup
from app.application_accounting.chart_of_accounts.models import Account
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_selling.models import (
    SalesDeliveryNote, SalesDeliveryNoteItem,
    SalesInvoice, SalesInvoiceItem
)

class SalesRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---------- Save ----------
    def save(self, obj):
        if obj not in self.s:
            self.s.add(obj)
        self.s.flush()
        return obj

    # ---------- Codes ----------
    def code_exists_dn(self, company_id: int, branch_id: int, code: str) -> bool:
        stmt = select(exists().where(
            SalesDeliveryNote.company_id == company_id,
            SalesDeliveryNote.branch_id == branch_id,
            func.lower(SalesDeliveryNote.code) == func.lower(code)
        ))
        return self.s.execute(stmt).scalar()

    def code_exists_si(self, company_id: int, branch_id: int, code: str) -> bool:
        stmt = select(exists().where(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            func.lower(SalesInvoice.code) == func.lower(code)
        ))
        return self.s.execute(stmt).scalar()

    # ---------- Fetch ----------
    def get_dn(self, dn_id: int, for_update: bool = False) -> Optional[SalesDeliveryNote]:
        stmt = select(SalesDeliveryNote).options(selectinload(SalesDeliveryNote.items)).where(SalesDeliveryNote.id == dn_id)
        if for_update: stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def get_si(self, si_id: int, for_update: bool = False) -> Optional[SalesInvoice]:
        stmt = select(SalesInvoice).options(selectinload(SalesInvoice.items)).where(SalesInvoice.id == si_id)
        if for_update: stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def get_si_with_items(self, si_id: int) -> Optional[SalesInvoice]:
        return self.s.query(SalesInvoice).options(joinedload(SalesInvoice.items)).filter(SalesInvoice.id == si_id).first()

    # ---------- Update line sync ----------
    def sync_dn_lines(self, dn: SalesDeliveryNote, lines: List[Dict]) -> None:
        existing = {l.id: l for l in dn.items}
        keep: Set[int] = set()
        for d in lines:
            lid = d.get("id")
            if lid and lid in existing:
                line = existing[lid]
                for k, v in d.items():
                    if hasattr(line, k):
                        setattr(line, k, v)
                keep.add(lid)
            else:
                self.s.add(SalesDeliveryNoteItem(delivery_note_id=dn.id, **d))
        for lid in set(existing.keys()) - keep:
            self.s.delete(existing[lid])

    def sync_si_lines(self, si: SalesInvoice, lines: List[Dict]) -> None:
        """
        Upsert invoice lines. Ignore generated / read-only columns like `amount`.
        """
        # Only these fields can be set via app logic
        UPDATABLE = {
            "item_id", "uom_id", "warehouse_id",
            "delivery_note_item_id", "return_against_item_id",
            "quantity", "rate", "income_account_id",
            "cost_center_id", "remarks"
        }

        existing = {l.id: l for l in si.items}
        keep: Set[int] = set()

        for d in lines:
            lid = d.get("id")
            payload = {k: v for k, v in d.items() if k in UPDATABLE}

            if lid and lid in existing:
                line = existing[lid]
                for k, v in payload.items():
                    setattr(line, k, v)
                keep.add(lid)
            else:
                # insert new line; do NOT pass generated columns like `amount`
                self.s.add(SalesInvoiceItem(invoice_id=si.id, **payload))

        # delete removed lines
        for lid in set(existing.keys()) - keep:
            self.s.delete(existing[lid])

    # ---------- Master data ----------
    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        from app import Branch
        return self.s.execute(select(Branch.company_id).where(Branch.id == branch_id)).scalar_one_or_none()

    def get_valid_customer_ids(self, company_id: int, customer_ids: List[int]) -> Set[int]:
        if not customer_ids: return set()
        stmt = select(Party.id).where(
            Party.id.in_(customer_ids),
            Party.company_id == company_id,
            Party.role == PartyRoleEnum.CUSTOMER,
            Party.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        if not warehouse_ids: return set()
        W = aliased(Warehouse)
        child_exists = self.s.execute(
            select(Warehouse.id, func.exists(select(1).where(W.parent_warehouse_id == Warehouse.id))).where(
                Warehouse.id.in_(warehouse_ids)
            )
        )  # not used directly; below is efficient path
        # efficient form:
        W_child = aliased(Warehouse)
        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~exists(select(1).where(W_child.parent_warehouse_id == Warehouse.id)),
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        if not item_ids: return {}
        rows = self.s.execute(
            select(Item.id, Item.status, Item.item_type, Item.base_uom_id, Item.item_group_id)
            .where(Item.id.in_(item_ids), Item.company_id == company_id)
        ).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "item_type": r.item_type,
                "base_uom_id": r.base_uom_id,
                "item_group_id": r.item_group_id,
            } for r in rows
        }

    def get_item_group_defaults(self, group_ids: List[int]) -> Dict[int, Dict]:
        if not group_ids: return {}
        rows = self.s.execute(
            select(
                ItemGroup.id,
                ItemGroup.default_income_account_id,
                ItemGroup.default_expense_account_id,
                ItemGroup.default_inventory_account_id
            ).where(ItemGroup.id.in_(group_ids))
        ).all()
        return {
            r.id: {
                "default_income_account_id": r.default_income_account_id,
                "default_expense_account_id": r.default_expense_account_id,
                "default_inventory_account_id": r.default_inventory_account_id,
            } for r in rows
        }

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        if not uom_ids: return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_compatible_uom_pairs(self, company_id: int, pairs: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        if not pairs: return set()
        item_ids = {p[0] for p in pairs}
        base_map = dict(self.s.execute(select(Item.id, Item.base_uom_id).where(Item.id.in_(item_ids))).all())
        valid = {(c.item_id, c.uom_id) for c in self.s.execute(
            select(UOMConversion.item_id, UOMConversion.uom_id).where(
                UOMConversion.item_id.in_(item_ids),
                UOMConversion.is_active == True
            )
        ).all()}
        out: Set[Tuple[int, int]] = set()
        for item_id, uom_id in pairs:
            bu = base_map.get(item_id)
            if not bu: continue
            if uom_id == bu or (item_id, uom_id) in valid:
                out.add((item_id, uom_id))
        return out

    # ---------- Accounts ----------
    def get_account_id_by_code(self, company_id: int, code: str) -> Optional[int]:
        return self.s.execute(select(Account.id).where(Account.company_id == company_id, Account.code == code).limit(1)).scalar_one_or_none()

    def get_default_receivable_account(self, company_id: int) -> int:
        acc = self.get_account_id_by_code(company_id, "1131")  # Debtors
        if not acc:
            raise ValueError("Default A/R account 1131 (Debtors) not found.")
        return acc

    def get_doc_type_id(self, code: str) -> Optional[int]:
        return self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
