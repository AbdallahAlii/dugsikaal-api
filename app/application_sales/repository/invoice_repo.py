# app/application_sales/repository/invoice_repo.py

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Set, Tuple
from sqlalchemy import select, func, exists, and_
from sqlalchemy.orm import Session, selectinload

from config.database import db
from app.application_stock.stock_models import DocStatusEnum, StockLedgerEntry
from app.application_sales.models import (
    SalesInvoice, SalesInvoiceItem, SalesDeliveryNote
)


class SalesInvoiceRepository:
    """Data Access Layer for Sales Invoice documents."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_by_id(self, si_id: int, for_update: bool = False) -> Optional[SalesInvoice]:
        stmt = (
            select(SalesInvoice)
            .options(selectinload(SalesInvoice.items))
            .where(SalesInvoice.id == si_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            SalesInvoice.company_id == company_id,
            SalesInvoice.branch_id == branch_id,
            func.lower(SalesInvoice.code) == func.lower(code)
        ))
        if exclude_id:
            stmt = stmt.where(SalesInvoice.id != exclude_id)
        return self.s.execute(stmt).scalar()

    def get_delivery_note_billable_status(self, delivery_note_id: int) -> Dict:
        """
        Fetch a SUBMITTED Sales Delivery Note and quantities already billed per line
        to prevent over-billing.
        """
        dn = self.s.execute(
            select(SalesDeliveryNote)
            .options(selectinload(SalesDeliveryNote.items))
            .where(
                SalesDeliveryNote.id == delivery_note_id,
                SalesDeliveryNote.doc_status == DocStatusEnum.SUBMITTED,
            )
        ).scalar_one_or_none()
        if not dn:
            return {}

        dn_item_ids = [it.id for it in dn.items]
        billed_stmt = (
            select(
                SalesInvoiceItem.delivery_note_item_id,
                func.sum(SalesInvoiceItem.quantity).label("total_billed"),
            )
            .join(SalesInvoice)
            .where(
                SalesInvoiceItem.delivery_note_item_id.in_(dn_item_ids),
                SalesInvoice.doc_status != DocStatusEnum.CANCELLED,
            )
            .group_by(SalesInvoiceItem.delivery_note_item_id)
        )
        billed = {
            r.delivery_note_item_id: r.total_billed
            for r in self.s.execute(billed_stmt).all()
        }
        return {"delivery_note": dn, "billed_quantities": billed}

    def has_future_sle(self, company_id: int, start_dt: datetime, pairs: Set[tuple[int, int]]) -> bool:
        """
        Return True if there exists any NON-CANCELLED SLE for (company,item,warehouse)
        strictly AFTER start_dt. Used to decide whether we must replay downstream rows.
        """
        if not pairs:
            return False

        for (item_id, wh_id) in pairs:
            q = (
                self.s.query(StockLedgerEntry.id)
                .filter(
                    StockLedgerEntry.company_id == company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                            (StockLedgerEntry.posting_date > start_dt.date())
                            | and_(
                        StockLedgerEntry.posting_date == start_dt.date(),
                        StockLedgerEntry.posting_time > start_dt,
                    )
                    ),
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                )
                .limit(1)
            )
            if self.s.query(q.exists()).scalar():
                return True
        return False

        return self.session.execute(stmt).scalar_one_or_none() is not None
    def save(self, si: SalesInvoice) -> SalesInvoice:
        if si not in self.s:
            self.s.add(si)
        self.s.flush()
        return si

    def sync_lines(self, si: SalesInvoice, lines_data: List[Dict]) -> None:
        existing = {ln.id: ln for ln in si.items}
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
                self.s.add(SalesInvoiceItem(invoice_id=si.id, **data))
        for line_id in set(existing.keys()) - keep:
            self.s.delete(existing[line_id])
