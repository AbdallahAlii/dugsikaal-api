
# app/application_accounting/chart_of_accounts/Repository/party_ledger_repo.py
from __future__ import annotations

from typing import Optional, List, Dict, Literal, Tuple
from decimal import Decimal
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.common.date_utils import format_date_out
from config.database import db
from app.application_stock.stock_models import DocStatusEnum

# Models
from app.application_buying.models import PurchaseInvoice   # supplier bills
from app.application_selling.models import SalesInvoice     # customer invoices

PartyKind = Literal["Customer", "Supplier", "Employee", "Shareholder", "Other"]

# In this project, invoices move from DRAFT -> (UNPAID|PARTIALLY_PAID|PAID) after submit.
PAYMENT_ELIGIBLE_STATUSES: Tuple[DocStatusEnum, ...] = (
    DocStatusEnum.UNPAID,
    DocStatusEnum.PARTIALLY_PAID,
)

class PartyLedgerRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    # --------------------------- helpers ---------------------------

    def _doc_and_party_col(self, party_kind: PartyKind):
        if party_kind == "Customer":
            return SalesInvoice, SalesInvoice.customer_id
        if party_kind == "Supplier":
            return PurchaseInvoice, PurchaseInvoice.supplier_id
        return None, None

    # --------------------- outstanding (list) ----------------------

    def get_outstanding_invoices(
        self,
        *,
        company_id: int,
        party_kind: PartyKind,
        party_id: int,
        posting_from: Optional[date] = None,
        posting_to: Optional[date] = None,
        due_from: Optional[date] = None,
        due_to: Optional[date] = None,
        gt_amount: Optional[Decimal] = None,
        lt_amount: Optional[Decimal] = None,
        limit: int = 200,
    ) -> List[Dict]:
        """
        Return outstanding invoices for Customer/Supplier that are eligible for payment allocation.
        Includes both positive and negative outstanding, excludes zero.
        Ordered FIFO by (due_date ASC NULLS LAST, posting_date ASC, id ASC).
        """
        Doc, party_col = self._doc_and_party_col(party_kind)
        if Doc is None:
            return []

        q = (
            select(
                Doc.id.label("doc_id"),
                Doc.code.label("code"),
                Doc.posting_date.label("posting_date"),
                Doc.due_date.label("due_date"),
                Doc.outstanding_amount.label("outstanding_amount"),
            )
            .where(
                Doc.company_id == company_id,
                party_col == party_id,
                Doc.doc_status.in_(PAYMENT_ELIGIBLE_STATUSES),
                Doc.outstanding_amount != 0,
            )
        )

        # Optional filters
        if posting_from: q = q.where(Doc.posting_date >= posting_from)
        if posting_to:   q = q.where(Doc.posting_date <= posting_to)
        if due_from:     q = q.where(Doc.due_date >= due_from)
        if due_to:       q = q.where(Doc.due_date <= due_to)
        if gt_amount is not None: q = q.where(Doc.outstanding_amount > gt_amount)
        if lt_amount is not None: q = q.where(Doc.outstanding_amount < lt_amount)

        q = q.order_by(
            Doc.due_date.asc().nulls_last(),
            Doc.posting_date.asc(),
            Doc.id.asc(),
        ).limit(limit)

        rows = self.s.execute(q).all()
        return [
            dict(
                doctype=("SALES_INVOICE" if Doc is SalesInvoice else "PURCHASE_INVOICE"),
                doc_id=int(r.doc_id),
                code=r.code,
                posting_date=format_date_out(r.posting_date),
                due_date=r.due_date,
                outstanding_amount=Decimal(r.outstanding_amount or 0),
            )
            for r in rows
        ]

    # --------------------- outstanding (targeted) ------------------

    def get_outstanding_by_ids(
        self,
        *,
        company_id: int,
        party_kind: PartyKind,
        party_id: int,
        doc_ids: List[int],
    ) -> Dict[int, Dict]:
        """
        Fast targeted lookup used by validators:
        returns {invoice_id: {doc_id, code, posting_date, due_date, outstanding_amount}}
        Only returns rows that are payment-eligible and have non-zero outstanding.
        """
        if not doc_ids:
            return {}

        Doc, party_col = self._doc_and_party_col(party_kind)
        if Doc is None:
            return {}

        q = (
            select(Doc.id, Doc.code, Doc.posting_date, Doc.due_date, Doc.outstanding_amount)
            .where(
                Doc.company_id == company_id,
                party_col == party_id,
                Doc.id.in_([int(x) for x in doc_ids]),
                Doc.doc_status.in_(PAYMENT_ELIGIBLE_STATUSES),
                Doc.outstanding_amount != 0,
            )
        )

        rows = self.s.execute(q).all()
        return {
            int(r.id): dict(
                doc_id=int(r.id),
                code=r.code,
                posting_date=format_date_out(r.posting_date),
                due_date=r.due_date,
                outstanding_amount=Decimal(r.outstanding_amount or 0),
            )
            for r in rows
        }

    # ------------------------ apply allocation ---------------------

    def apply_allocation(
        self,
        *,
        party_kind: PartyKind,
        invoice_id: int,
        amount: Decimal,
    ) -> Decimal:
        """
        Apply 'amount' to the given invoice, updating:
          - outstanding_amount
          - paid_amount (maintain invariant: total = paid + outstanding)
          - doc_status -> PAID / PARTIALLY_PAID / UNPAID
        Returns the actual amount consumed (as Decimal).
        """
        amt = Decimal(str(amount or 0))
        if amt == 0:
            return Decimal("0")

        if party_kind == "Customer":
            inv = self.s.get(SalesInvoice, int(invoice_id))
        elif party_kind == "Supplier":
            inv = self.s.get(PurchaseInvoice, int(invoice_id))
        else:
            return Decimal("0")

        if not inv or inv.doc_status not in PAYMENT_ELIGIBLE_STATUSES:
            return Decimal("0")

        total = Decimal(str(inv.total_amount or 0))
        out0  = Decimal(str(inv.outstanding_amount or 0))
        if out0 == 0:
            return Decimal("0")

        consume = min(abs(amt), abs(out0))

        # Move outstanding toward zero
        new_out = out0 - consume if out0 > 0 else out0 + consume

        inv.outstanding_amount = new_out
        inv.paid_amount = total - new_out  # keep invariant

        # Derive status
        if new_out == 0:
            inv.doc_status = DocStatusEnum.PAID
        elif new_out == total:
            inv.doc_status = DocStatusEnum.UNPAID
        else:
            inv.doc_status = DocStatusEnum.PARTIALLY_PAID

        self.s.flush([inv])
        return consume
