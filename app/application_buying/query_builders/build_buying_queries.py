# app/application_buying/query_builders/build_buying_queries.py
from __future__ import annotations

from typing import Optional, Iterable
from sqlalchemy import select, false, func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.security.rbac_effective import AffiliationContext
from app.application_buying.models import (
    PurchaseQuotation, PurchaseReceipt, PurchaseInvoice, PurchaseReturn
)
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch


def _ymd(col):
    """Render a date-only ISO string (YYYY-MM-DD) for UI."""
    return func.to_char(col, 'YYYY-MM-DD')


def _scope_predicates(model, co_id: Optional[int], branch_ids: Iterable[int]) -> ColumnElement[bool]:
    if co_id is None:
        return false()
    pred = (model.company_id == co_id)
    branch_ids = list(branch_ids or [])
    if branch_ids:
        pred = pred & (model.branch_id.in_(branch_ids))
    return pred


def _company_and_branch(context: AffiliationContext) -> tuple[Optional[int], list[int]]:
    return getattr(context, "company_id", None), list(getattr(context, "branch_ids", []) or [])


# --------------------------- Purchase Receipts ---------------------------
def build_purchase_receipts_query(session: Session, context: AffiliationContext):
    co_id, branch_ids = _company_and_branch(context)
    PR = PurchaseReceipt
    pred = _scope_predicates(PR, co_id, branch_ids)

    return (
        select(
            PR.id.label("id"),
            PR.code.label("code"),
            Party.name.label("supplier_name"),
            PR.doc_status.label("doc_status"),
            _ymd(PR.posting_date).label("posting_date"),   # << date-only
            PR.total_amount.label("total_amount"),
            Branch.name.label("branch_name"),
            PR.company_id.label("company_id"),
            PR.branch_id.label("branch_id"),
            PR.supplier_id.label("supplier_id"),
        )
        .select_from(PR)
        .join(Party, Party.id == PR.supplier_id)
        .join(Branch, Branch.id == PR.branch_id)
        .where(pred)
    )


# --------------------------- Purchase Invoices ---------------------------
def build_purchase_invoices_query(session: Session, context: AffiliationContext):
    co_id, branch_ids = _company_and_branch(context)
    PI = PurchaseInvoice
    pred = _scope_predicates(PI, co_id, branch_ids)

    return (
        select(
            PI.id.label("id"),
            PI.code.label("code"),
            Party.name.label("supplier_name"),
            PI.doc_status.label("doc_status"),
            _ymd(PI.posting_date).label("posting_date"),   # << date-only
            PI.total_amount.label("total_amount"),
            PI.amount_paid.label("amount_paid"),
            Branch.name.label("branch_name"),
            PI.company_id.label("company_id"),
            PI.branch_id.label("branch_id"),
            PI.supplier_id.label("supplier_id"),
        )
        .select_from(PI)
        .join(Party, Party.id == PI.supplier_id)
        .join(Branch, Branch.id == PI.branch_id)
        .where(pred)
    )


# --------------------------- Purchase Quotations ---------------------------
def build_purchase_quotations_query(session: Session, context: AffiliationContext):
    co_id, branch_ids = _company_and_branch(context)
    PQ = PurchaseQuotation
    pred = _scope_predicates(PQ, co_id, branch_ids)

    return (
        select(
            PQ.id.label("id"),
            PQ.code.label("code"),
            Party.name.label("supplier_name"),
            PQ.doc_status.label("doc_status"),
            _ymd(PQ.posting_date).label("posting_date"),   # << date-only
            Branch.name.label("branch_name"),
            PQ.company_id.label("company_id"),
            PQ.branch_id.label("branch_id"),
            PQ.supplier_id.label("supplier_id"),
        )
        .select_from(PQ)
        .join(Party, Party.id == PQ.supplier_id)
        .join(Branch, Branch.id == PQ.branch_id)
        .where(pred)
    )


# --------------------------- Purchase Returns ---------------------------
def build_purchase_returns_query(session: Session, context: AffiliationContext):
    co_id, branch_ids = _company_and_branch(context)
    PRET = PurchaseReturn
    pred = _scope_predicates(PRET, co_id, branch_ids)

    return (
        select(
            PRET.id.label("id"),
            PRET.code.label("code"),
            Party.name.label("supplier_name"),
            PRET.doc_status.label("doc_status"),
            _ymd(PRET.posting_date).label("posting_date"),  # << date-only
            Branch.name.label("branch_name"),
            PRET.company_id.label("company_id"),
            PRET.branch_id.label("branch_id"),
            PRET.supplier_id.label("supplier_id"),
        )
        .select_from(PRET)
        .join(Party, Party.id == PRET.supplier_id)
        .join(Branch, Branch.id == PRET.branch_id)
        .where(pred)
    )
