# app/application_selling/query_builders/build_selling_queries.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, func
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_sales.models import (
    SalesQuotation, SalesDeliveryNote, SalesInvoice, SalesReturn
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


def build_sales_quotations_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of sales quotations with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesQuotation.id).where(false())

    SQ = SalesQuotation
    P = Party
    B = Branch

    q = (
        select(
            SQ.id.label("id"),
            SQ.code.label("document_number"),
            P.name.label("customer_name"),
            SQ.doc_status.label("status"),
            _ymd(SQ.posting_date).label("posting_date"),
            B.name.label("branch_location"),
            SQ.company_id.label("company_id"),
            SQ.branch_id.label("branch_id"),
            SQ.customer_id.label("customer_id"),
        )
        .select_from(SQ)
        .join(P, P.id == SQ.customer_id)
        .join(B, B.id == SQ.branch_id)
        .where(SQ.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SQ.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


def build_sales_delivery_notes_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of sales delivery notes with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesDeliveryNote.id).where(false())

    SDN = SalesDeliveryNote
    P = Party
    B = Branch

    q = (
        select(
            SDN.id.label("id"),
            SDN.code.label("document_number"),
            P.name.label("customer_name"),
            SDN.doc_status.label("status"),
            _ymd(SDN.posting_date).label("posting_date"),
            SDN.total_amount.label("total_amount"),
            B.name.label("branch_location"),
            SDN.company_id.label("company_id"),
            SDN.branch_id.label("branch_id"),
            SDN.customer_id.label("customer_id"),
        )
        .select_from(SDN)
        .join(P, P.id == SDN.customer_id)
        .join(B, B.id == SDN.branch_id)
        .where(SDN.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SDN.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


def build_sales_invoices_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of sales invoices with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesInvoice.id).where(false())

    SI = SalesInvoice
    P = Party
    B = Branch

    q = (
        select(
            SI.id.label("id"),
            SI.code.label("document_number"),
            P.name.label("customer_name"),
            SI.doc_status.label("status"),
            _ymd(SI.posting_date).label("posting_date"),
            SI.total_amount.label("total_amount"),
            SI.amount_paid.label("amount_paid"),
            SI.balance_due.label("balance_due"),
            B.name.label("branch_location"),
            SI.company_id.label("company_id"),
            SI.branch_id.label("branch_id"),
            SI.customer_id.label("customer_id"),
        )
        .select_from(SI)
        .join(P, P.id == SI.customer_id)
        .join(B, B.id == SI.branch_id)
        .where(SI.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SI.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


def build_sales_returns_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of sales returns with ERP-style presentation
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesReturn.id).where(false())

    SR = SalesReturn
    P = Party
    B = Branch

    q = (
        select(
            SR.id.label("id"),
            SR.code.label("document_number"),
            P.name.label("customer_name"),
            SR.doc_status.label("status"),
            _ymd(SR.posting_date).label("posting_date"),
            B.name.label("branch_location"),
            SR.company_id.label("company_id"),
            SR.branch_id.label("branch_id"),
            SR.customer_id.label("customer_id"),
        )
        .select_from(SR)
        .join(P, P.id == SR.customer_id)
        .join(B, B.id == SR.branch_id)
        .where(SR.company_id == co_id)
    )

    # Apply branch restrictions only for non-company-wide users
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SR.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q