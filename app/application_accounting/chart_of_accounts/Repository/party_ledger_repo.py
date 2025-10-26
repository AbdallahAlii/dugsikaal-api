from __future__ import annotations
from typing import Optional, List, Dict, Literal
from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import select

from config.database import db

from app.application_stock.stock_models import DocStatusEnum

from app.application_buying.models import PurchaseInvoice  # fields: company_id, branch_id, customer_id, outstanding_amount, posting_date, due_date, doc_status
from app.application_selling.models import SalesInvoice    # fields: company_id, branch_id, supplier_id, outstanding_amount, posting_date, due_date, doc_status


PartyKind = Literal["Customer", "Supplier", "Employee", "Shareholder", "Other"]

class PartyLedgerRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

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
        # Only Customer/Supplier have SI/PI docs; others are advance/ledger-only (no refs)
        if party_kind == "Customer":
            Doc = SalesInvoice
            doctype = "SALES_INVOICE"
            q = select(
                Doc.id.label("doc_id"), Doc.code.label("code"),
                Doc.posting_date.label("posting_date"), Doc.due_date.label("due_date"),
                Doc.outstanding_amount.label("outstanding_amount")
            ).where(
                Doc.company_id == company_id,
                Doc.customer_id == party_id,
                Doc.doc_status == DocStatusEnum.SUBMITTED,
                Doc.outstanding_amount != 0
            )
        elif party_kind == "Supplier":
            Doc = PurchaseInvoice
            doctype = "PURCHASE_INVOICE"
            q = select(
                Doc.id.label("doc_id"), Doc.code.label("code"),
                Doc.posting_date.label("posting_date"), Doc.due_date.label("due_date"),
                Doc.outstanding_amount.label("outstanding_amount")
            ).where(
                Doc.company_id == company_id,
                Doc.supplier_id == party_id,
                Doc.doc_status == DocStatusEnum.SUBMITTED,
                Doc.outstanding_amount != 0
            )
        else:
            return []  # no reference docs for Employee/Shareholder/Other

        # filters
        if posting_from: q = q.where(Doc.posting_date >= posting_from)
        if posting_to:   q = q.where(Doc.posting_date <= posting_to)
        if due_from:     q = q.where(Doc.due_date >= due_from)
        if due_to:       q = q.where(Doc.due_date <= due_to)
        if gt_amount is not None: q = q.where(Doc.outstanding_amount > gt_amount)
        if lt_amount is not None: q = q.where(Doc.outstanding_amount < lt_amount)

        q = q.order_by(Doc.due_date.asc().nulls_last(), Doc.posting_date.asc(), Doc.id.asc()).limit(limit)
        rows = self.s.execute(q).all()
        return [
            dict(
                doctype=doctype, doc_id=int(r.doc_id), code=r.code,
                posting_date=r.posting_date, due_date=r.due_date,
                outstanding_amount=Decimal(r.outstanding_amount or 0),
            )
            for r in rows
        ]

    def apply_allocation(self, *, party_kind: PartyKind, invoice_id: int, amount: Decimal) -> Decimal:
        if amount == 0: return Decimal("0")
        if party_kind == "Customer":
            inv = self.s.get(SalesInvoice, invoice_id)
        elif party_kind == "Supplier":
            inv = self.s.get(PurchaseInvoice, invoice_id)
        else:
            return Decimal("0")
        if not inv or inv.doc_status != DocStatusEnum.SUBMITTED:
            return Decimal("0")

        o = Decimal(inv.outstanding_amount or 0)
        if o == 0: return Decimal("0")
        consume = min(abs(amount), abs(o))
        if o > 0: inv.outstanding_amount = o - consume
        else:     inv.outstanding_amount = o + consume
        self.s.flush()
        return consume
