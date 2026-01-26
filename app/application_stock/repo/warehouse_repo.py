from __future__ import annotations

from typing import Optional, Dict, Any

from sqlalchemy import select, func, exists, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch

# Optional Bin stock guard
try:
    from app.application_stock.stock_models import Bin  # type: ignore
    HAS_BIN = True
except Exception:
    HAS_BIN = False


class WarehouseRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---------- basic reads ----------
    def get_by_id(self, wid: int, *, for_update: bool = False) -> Optional[Warehouse]:
        stmt = select(Warehouse).where(Warehouse.id == wid)
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    # IMPORTANT: root is unique per company by DB constraint now.
    # Do NOT filter by status here, otherwise you may try to create a new root and hit IntegrityError.
    def get_company_root(self, company_id: int) -> Optional[Warehouse]:
        stmt = (
            select(Warehouse)
            .where(
                Warehouse.company_id == company_id,
                Warehouse.parent_warehouse_id.is_(None),
                Warehouse.branch_id.is_(None),
                Warehouse.is_group.is_(True),
            )
            .order_by(Warehouse.id.asc())
            .limit(1)
        )
        return self.s.execute(stmt).scalar_one_or_none()

    def company_root_exists(self, company_id: int) -> bool:
        stmt = select(
            exists().where(
                Warehouse.company_id == company_id,
                Warehouse.parent_warehouse_id.is_(None),
                Warehouse.branch_id.is_(None),
                Warehouse.is_group.is_(True),
            )
        )
        return bool(self.s.execute(stmt).scalar())

    def has_children(self, wid: int) -> bool:
        # If you want to block delete even when children are inactive, remove the status filter.
        stmt = select(
            exists().where(
                Warehouse.parent_warehouse_id == wid,
                # Warehouse.status == StatusEnum.ACTIVE,
            )
        )
        return bool(self.s.execute(stmt).scalar())

    def parent_info(self, parent_id: int) -> Optional[tuple[int, Optional[int], bool]]:
        stmt = select(Warehouse.company_id, Warehouse.branch_id, Warehouse.is_group).where(Warehouse.id == parent_id)
        row = self.s.execute(stmt).first()
        if not row:
            return None
        return (int(row[0]), row[1], bool(row[2]))

    # ---------- branch helpers ----------
    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()

    # ---------- uniqueness ----------
    # Per-company, case-insensitive (matches uq_wh_company_code_lower)
    def code_exists_in_company(self, *, company_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        base = exists().where(
            Warehouse.company_id == company_id,
            func.lower(Warehouse.code) == func.lower(code),
        )
        if exclude_id:
            base = base.where(Warehouse.id != exclude_id)
        return bool(self.s.execute(select(base)).scalar())

    # Legacy helper (keep only if other modules still use it).
    def code_exists_global(self, code: str, exclude_id: Optional[int] = None) -> bool:
        base = exists().where(func.lower(Warehouse.code) == func.lower(code))
        if exclude_id:
            base = base.where(Warehouse.id != exclude_id)
        return bool(self.s.execute(select(base)).scalar())

    # Matches your name uniqueness logic:
    # - branch_id NULL => unique within company
    # - branch_id set  => unique within (company, branch)
    def name_exists_in_branch(
        self,
        company_id: int,
        branch_id: Optional[int],
        name: str,
        exclude_id: Optional[int] = None,
    ) -> bool:
        pred_branch = Warehouse.branch_id.is_(None) if branch_id is None else (Warehouse.branch_id == branch_id)
        base = exists().where(
            Warehouse.company_id == company_id,
            pred_branch,
            func.lower(Warehouse.name) == func.lower(name),
        )
        if exclude_id:
            base = base.where(Warehouse.id != exclude_id)
        return bool(self.s.execute(select(base)).scalar())

    # ---------- stock guard ----------
    def sum_stock_qty(self, company_id: int, warehouse_id: int):
        if not HAS_BIN:
            return None
        from decimal import Decimal

        stmt = select(func.coalesce(func.sum(Bin.actual_qty), 0)).where(
            Bin.company_id == company_id,
            Bin.warehouse_id == warehouse_id,
        )
        return Decimal(str(self.s.execute(stmt).scalar() or 0))

    # ---------- linked-doc guard (Frappe style) ----------
    def find_first_linked_document(self, *, company_id: int, warehouse_id: int) -> Optional[Dict[str, Any]]:
        """
        Returns first found link:
          {"doctype": "...", "code": "..."}
        Fast: short-circuits with LIMIT 1 per check.
        """

        # ---- Stock Reconciliation Item -> Stock Reconciliation.code ----
        try:
            from app.application_stock.stock_models import StockReconciliationItem, StockReconciliation  # type: ignore
            stmt = (
                select(StockReconciliation.code)
                .join(StockReconciliation, StockReconciliation.id == StockReconciliationItem.reconciliation_id)
                .where(
                    StockReconciliation.company_id == company_id,
                    StockReconciliationItem.warehouse_id == warehouse_id,
                )
                .limit(1)
            )
            code = self.s.execute(stmt).scalar_one_or_none()
            if code:
                return {"doctype": "Stock Reconciliation", "code": str(code)}
        except Exception:
            pass

        # ---- Stock Entry Item -> Stock Entry.code (source or target) ----
        try:
            from app.application_stock.stock_models import StockEntryItem, StockEntry  # type: ignore
            stmt = (
                select(StockEntry.code)
                .join(StockEntry, StockEntry.id == StockEntryItem.stock_entry_id)
                .where(
                    StockEntry.company_id == company_id,
                    or_(
                        StockEntryItem.source_warehouse_id == warehouse_id,
                        StockEntryItem.target_warehouse_id == warehouse_id,
                    ),
                )
                .limit(1)
            )
            code = self.s.execute(stmt).scalar_one_or_none()
            if code:
                return {"doctype": "Stock Entry", "code": str(code)}
        except Exception:
            pass

        # ---- Sales Delivery Note Item -> Sales Delivery Note.code ----
        try:
            from app.application_selling.models import SalesDeliveryNoteItem, SalesDeliveryNote  # type: ignore
            stmt = (
                select(SalesDeliveryNote.code)
                .join(SalesDeliveryNote, SalesDeliveryNote.id == SalesDeliveryNoteItem.delivery_note_id)
                .where(
                    SalesDeliveryNote.company_id == company_id,
                    SalesDeliveryNoteItem.warehouse_id == warehouse_id,
                )
                .limit(1)
            )
            code = self.s.execute(stmt).scalar_one_or_none()
            if code:
                return {"doctype": "Sales Delivery Note", "code": str(code)}
        except Exception:
            pass

        # ---- Sales Invoice Item -> Sales Invoice.code ----
        try:
            from app.application_selling.models import SalesInvoiceItem, SalesInvoice  # type: ignore
            stmt = (
                select(SalesInvoice.code)
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceItem.invoice_id)
                .where(
                    SalesInvoice.company_id == company_id,
                    SalesInvoiceItem.warehouse_id == warehouse_id,
                )
                .limit(1)
            )
            code = self.s.execute(stmt).scalar_one_or_none()
            if code:
                return {"doctype": "Sales Invoice", "code": str(code)}
        except Exception:
            pass

        # ---- Stock Ledger Entry (fallback) ----
        try:
            from app.application_stock.stock_models import StockLedgerEntry, DocumentType  # type: ignore
            stmt = (
                select(DocumentType.code, StockLedgerEntry.doc_id)
                .join(DocumentType, DocumentType.id == StockLedgerEntry.doc_type_id)
                .where(
                    StockLedgerEntry.company_id == company_id,
                    StockLedgerEntry.warehouse_id == warehouse_id,
                )
                .limit(1)
            )
            row = self.s.execute(stmt).first()
            if row:
                dt_code, doc_id = row
                return {"doctype": str(dt_code), "code": str(doc_id)}
        except Exception:
            pass

        return None

    # ---------- writes ----------
    def create(self, wh: Warehouse) -> Warehouse:
        self.s.add(wh)
        self.s.flush([wh])
        return wh

    def save(self, wh: Warehouse) -> Warehouse:
        self.s.flush([wh])
        return wh

    def delete(self, wh: Warehouse) -> None:
        self.s.delete(wh)
        self.s.flush([wh])
