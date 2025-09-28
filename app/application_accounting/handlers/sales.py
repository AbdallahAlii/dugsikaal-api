# application_accounting/handlers/sales.py
from __future__ import annotations
from datetime import datetime
from typing import Dict, Any, Iterable
from sqlalchemy.orm import Session

from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.application_accounting.engine.posting_service import PostingContext, PostingService


def post_delivery_note(
    s: Session, *,
    company_id: int, branch_id: int, customer_id: int,
    posting_date: datetime, created_by_id: int,
    source_doctype_id: int, source_doc_id: int,
    cogs_total: float
) -> None:
    payload = {"cogs_total": cogs_total}
    ctx = PostingContext(
        company_id=company_id, branch_id=branch_id,
        source_doctype_id=source_doctype_id, source_doc_id=source_doc_id,
        posting_date=posting_date, created_by_id=created_by_id,
        is_auto_generated=True, remarks=f"Delivery Note {source_doc_id}",
        template_code="DELIVERY_NOTE_COGS",
        payload=payload, runtime_accounts={},
        party_id=customer_id, party_type=PartyTypeEnum.CUSTOMER
    )
    PostingService(s).post(ctx)

def post_sales_invoice_ar(
    s: Session, *,
    company_id: int, branch_id: int, customer_id: int,
    posting_date: datetime, created_by_id: int,
    source_doctype_id: int, source_doc_id: int,
    document_subtotal: float, tax_amount: float, rounding_adjustment: float, grand_total: float,
    income_account_id: int, ar_account_id: int
) -> None:
    payload = dict(
        document_subtotal=document_subtotal, tax_amount=tax_amount,
        rounding_adjustment=rounding_adjustment, document_total=grand_total
    )
    runtime = {
        "income_account_id": income_account_id,
        "accounts_receivable_account_id": ar_account_id,
    }
    ctx = PostingContext(
        company_id=company_id, branch_id=branch_id,
        source_doctype_id=source_doctype_id, source_doc_id=source_doc_id,
        posting_date=posting_date, created_by_id=created_by_id,
        is_auto_generated=True, remarks=f"Sales Invoice {source_doc_id}",
        template_code="SALES_INV_AR",
        payload=payload, runtime_accounts=runtime,
        party_id=customer_id, party_type=PartyTypeEnum.CUSTOMER
    )
    PostingService(s).post(ctx)

def post_sales_invoice_with_stock(
    s: Session, *,
    company_id: int, branch_id: int, customer_id: int,
    posting_date: datetime, created_by_id: int,
    source_doctype_id: int, source_doc_id: int,
    document_subtotal: float, tax_amount: float, rounding_adjustment: float, grand_total: float,
    cogs_total: float,
    income_account_id: int, ar_account_id: int
) -> None:
    payload = dict(
        document_subtotal=document_subtotal, tax_amount=tax_amount,
        rounding_adjustment=rounding_adjustment, document_total=grand_total,
        cogs_total=cogs_total,
    )
    runtime = {
        "income_account_id": income_account_id,
        "accounts_receivable_account_id": ar_account_id,
    }
    ctx = PostingContext(
        company_id=company_id, branch_id=branch_id,
        source_doctype_id=source_doctype_id, source_doc_id=source_doc_id,
        posting_date=posting_date, created_by_id=created_by_id,
        is_auto_generated=True, remarks=f"Sales Invoice {source_doc_id}",
        template_code="SALES_INV_WITH_STOCK",
        payload=payload, runtime_accounts=runtime,
        party_id=customer_id, party_type=PartyTypeEnum.CUSTOMER
    )
    PostingService(s).post(ctx)
