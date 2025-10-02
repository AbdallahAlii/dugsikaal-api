# app/application_buying/query_builders/build_buying_queries.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, func
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_buying.models import (
    PurchaseQuotation, PurchaseReceipt, PurchaseInvoice, PurchaseReturn
)
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch


def _ymd(col):
    """Render a date-only ISO string (YYYY-MM-DD) for UI."""
    return func.to_char(col, 'YYYY-MM-DD')


def _is_super_admin(ctx: AffiliationContext) -> bool:
    """Check if user is a super admin (has Super Admin role)"""
    roles = getattr(ctx, "roles", []) or []
    return "Super Admin" in roles


def _is_company_owner(ctx: AffiliationContext) -> bool:
    """Check if user is a company owner (has primary affiliation with branch_id null)"""
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    """Check if user has company-wide access (system admin, super admin, or company owner)"""
    return getattr(ctx, "is_system_admin", False) or _is_super_admin(ctx) or _is_company_owner(ctx)


def build_purchase_receipts_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of purchase receipts with ERP-style presentation
    - Super Admins & Company Owners see ALL receipts in their company
    - Regular users see only receipts from their branches
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PurchaseReceipt.id).where(false())

    PR = PurchaseReceipt
    P = Party
    B = Branch

    q = (
        select(
            PR.id.label("id"),
            PR.code.label("document_number"),
            P.name.label("supplier_name"),
            PR.doc_status.label("status"),
            _ymd(PR.posting_date).label("posting_date"),
            PR.total_amount.label("total_amount"),
            B.name.label("branch_location"),
            PR.company_id.label("company_id"),
            PR.branch_id.label("branch_id"),
            PR.supplier_id.label("supplier_id"),
        )
        .select_from(PR)
        .join(P, P.id == PR.supplier_id)
        .join(B, B.id == PR.branch_id)
        .where(PR.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(PR.branch_id.in_(branch_ids))
        else:
            # Users with no specific branch access see nothing
            q = q.where(false())

    return q


def build_purchase_invoices_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of purchase invoices with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PurchaseInvoice.id).where(false())

    PI = PurchaseInvoice
    P = Party
    B = Branch

    q = (
        select(
            PI.id.label("id"),
            PI.code.label("document_number"),
            P.name.label("supplier_name"),
            PI.doc_status.label("status"),
            _ymd(PI.posting_date).label("posting_date"),
            PI.total_amount.label("total_amount"),
            PI.amount_paid.label("amount_paid"),
            PI.balance_due.label("balance_due"),
            B.name.label("branch_location"),
            PI.company_id.label("company_id"),
            PI.branch_id.label("branch_id"),
            PI.supplier_id.label("supplier_id"),
        )
        .select_from(PI)
        .join(P, P.id == PI.supplier_id)
        .join(B, B.id == PI.branch_id)
        .where(PI.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(PI.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


def build_purchase_quotations_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of purchase quotations with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PurchaseQuotation.id).where(false())

    PQ = PurchaseQuotation
    P = Party
    B = Branch

    q = (
        select(
            PQ.id.label("id"),
            PQ.code.label("document_number"),
            P.name.label("supplier_name"),
            PQ.doc_status.label("status"),
            _ymd(PQ.posting_date).label("posting_date"),
            B.name.label("branch_location"),
            PQ.company_id.label("company_id"),
            PQ.branch_id.label("branch_id"),
            PQ.supplier_id.label("supplier_id"),
        )
        .select_from(PQ)
        .join(P, P.id == PQ.supplier_id)
        .join(B, B.id == PQ.branch_id)
        .where(PQ.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(PQ.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


def build_purchase_returns_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of purchase returns with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PurchaseReturn.id).where(false())

    PRET = PurchaseReturn
    P = Party
    B = Branch

    q = (
        select(
            PRET.id.label("id"),
            PRET.code.label("document_number"),
            P.name.label("supplier_name"),
            PRET.doc_status.label("status"),
            _ymd(PRET.posting_date).label("posting_date"),
            B.name.label("branch_location"),
            PRET.company_id.label("company_id"),
            PRET.branch_id.label("branch_id"),
            PRET.supplier_id.label("supplier_id"),
        )
        .select_from(PRET)
        .join(P, P.id == PRET.supplier_id)
        .join(B, B.id == PRET.branch_id)
        .where(PRET.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(PRET.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q