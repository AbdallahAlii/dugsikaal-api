from __future__ import annotations
from typing import Optional, Iterable, List, Tuple, Dict
from decimal import Decimal
from sqlalchemy import select, update, func, and_
from sqlalchemy.orm import Session

from config.database import db
from app.application_accounting.chart_of_accounts.finance_model import PaymentEntry, PaymentItem
from app.application_stock.stock_models import DocStatusEnum

class PaymentRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    # --- existence -----------------------------------------------------
    def code_exists_pe(self, company_id: int, branch_id: int, code: str) -> bool:
        q = select(PaymentEntry.id).where(
            PaymentEntry.company_id == company_id,
            PaymentEntry.branch_id == branch_id,
            PaymentEntry.code == code,
        )
        return self.s.execute(q).scalar_one_or_none() is not None

    # --- CRUD ----------------------------------------------------------
    def get(self, payment_id: int) -> Optional[PaymentEntry]:
        return self.s.get(PaymentEntry, payment_id)

    def add(self, obj: PaymentEntry) -> PaymentEntry:
        self.s.add(obj)
        self.s.flush()
        return obj

    def add_items(self, payment_id: int, rows: Iterable[Dict]) -> None:
        for r in rows or []:
            it = PaymentItem(
                payment_id=payment_id,
                source_doctype_id=r.get("source_doctype_id"),
                source_doc_id=r.get("source_doc_id"),
                allocated_amount=Decimal(str(r.get("allocated_amount") or "0")),
            )
            self.s.add(it)
        self.s.flush()

    def delete_items(self, payment_id: int) -> None:
        self.s.query(PaymentItem).filter(PaymentItem.payment_id == payment_id).delete()
        self.s.flush()

    # --- updates (DRAFT only; code immutable) -------------------------
    def update_header(self, pe: PaymentEntry, data: Dict) -> PaymentEntry:
        # immutable: code
        mutable = (
            "payment_type", "posting_date", "mode_of_payment_id",
            "party_type", "party_id",
            "paid_from_account_id", "paid_to_account_id",
            "paid_amount", "remarks"
        )
        for k in mutable:
            if k in data:
                setattr(pe, k, data[k])
        self.s.flush()
        return pe

    # --- totals --------------------------------------------------------
    def recompute_allocations(self, payment_id: int) -> Tuple[Decimal, Decimal]:
        total_alloc = self.s.execute(
            select(func.coalesce(func.sum(PaymentItem.allocated_amount), 0))
            .where(PaymentItem.payment_id == payment_id)
        ).scalar_one()
        pe = self.get(payment_id)
        paid = Decimal(pe.paid_amount or 0)
        pe.allocated_amount = Decimal(total_alloc)
        pe.unallocated_amount = paid - Decimal(total_alloc)
        self.s.flush()
        return (Decimal(total_alloc), paid - Decimal(total_alloc))

    # --- status --------------------------------------------------------
    def mark_submitted(self, payment_id: int) -> None:
        self.s.execute(
            update(PaymentEntry)
            .where(PaymentEntry.id == payment_id)
            .values(doc_status=DocStatusEnum.SUBMITTED)
        ); self.s.flush()

    def mark_cancelled(self, payment_id: int) -> None:
        self.s.execute(
            update(PaymentEntry)
            .where(PaymentEntry.id == payment_id)
            .values(doc_status=DocStatusEnum.CANCELLED)
        ); self.s.flush()
