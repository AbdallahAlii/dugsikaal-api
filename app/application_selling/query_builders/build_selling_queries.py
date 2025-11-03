from __future__ import annotations
from sqlalchemy import select, false, func
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_selling.models import (
    SalesQuotation, SalesDeliveryNote, SalesInvoice
)
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch


def _ymd(col):
    """DB-side date-only (YYYY-MM-DD) for list views."""
    return func.to_char(col, 'YYYY-MM-DD')


def _is_super_admin(ctx: AffiliationContext) -> bool:
    roles = getattr(ctx, "roles", []) or []
    return "Super Admin" in roles


def _is_company_owner(ctx: AffiliationContext) -> bool:
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    return getattr(ctx, "is_system_admin", False) or _is_super_admin(ctx) or _is_company_owner(ctx)


# =========================
# Minimal list query: SI
# =========================
def build_sales_invoices_query(session: Session, context: AffiliationContext):
    """
    Sales Invoices list — minimal columns only:
      id, code, customer_name, status, posting_date, total_amount
    Still filters by company/branch and can search by customer/code.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesInvoice.id).where(false())

    SI = SalesInvoice
    C = Party
    B = Branch  # used only to enforce branch scope

    q = (
        select(
            SI.id.label("id"),
            SI.code.label("code"),
            C.name.label("customer_name"),
            SI.doc_status.label("status"),
            _ymd(SI.posting_date).label("posting_date"),
            SI.total_amount.label("total_amount"),
        )
        .select_from(SI)
        .join(C, C.id == SI.customer_id)       # for search_fields by customer
        .join(B, B.id == SI.branch_id)         # cheap FK join; helps branch scope planning
        .where(SI.company_id == co_id)
    )

    # Restrict branches unless user has company-wide access
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SI.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


# =========================
# Minimal list query: SDN
# =========================
def build_sales_delivery_notes_query(session: Session, context: AffiliationContext):
    """
    Delivery Notes list — minimal columns:
      id, code, customer_name, status, posting_date, total_amount
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesDeliveryNote.id).where(false())

    SDN = SalesDeliveryNote
    C = Party
    B = Branch

    q = (
        select(
            SDN.id.label("id"),
            SDN.code.label("code"),
            C.name.label("customer_name"),
            SDN.doc_status.label("status"),
            _ymd(SDN.posting_date).label("posting_date"),
            SDN.total_amount.label("total_amount"),
        )
        .select_from(SDN)
        .join(C, C.id == SDN.customer_id)
        .join(B, B.id == SDN.branch_id)
        .where(SDN.company_id == co_id)
    )

    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SDN.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


# =========================
# Minimal list query: SQ
# =========================
def build_sales_quotations_query(session: Session, context: AffiliationContext):
    """
    Sales Quotations list — minimal columns:
      id, code, customer_name, status, posting_date
    (No total_amount on header model, so we keep it off the list.)
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesQuotation.id).where(false())

    SQ = SalesQuotation
    C = Party
    B = Branch

    q = (
        select(
            SQ.id.label("id"),
            SQ.code.label("code"),
            C.name.label("customer_name"),
            SQ.doc_status.label("status"),
            _ymd(SQ.posting_date).label("posting_date"),
        )
        .select_from(SQ)
        .join(C, C.id == SQ.customer_id)
        .join(B, B.id == SQ.branch_id)
        .where(SQ.company_id == co_id)
    )

    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(SQ.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q
