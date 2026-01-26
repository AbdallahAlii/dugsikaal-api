from __future__ import annotations

from sqlalchemy import select, false, func, and_
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_selling.models import SalesQuotation,  SalesInvoice
from app.application_parties.parties_models import Party


def _ymd(col):
    """DB-side date-only (YYYY-MM-DD) for list views."""
    return func.to_char(col, "YYYY-MM-DD")


def _require_company_scope(context: AffiliationContext) -> int:
    """
    Enforce: user must be in a company scope (unless System Admin).
    Returns the resolved company_id used for filtering.
    """
    co_id = getattr(context, "company_id", None)
    # Uses your centralized scope rules (System Admin bypass included)
    ensure_scope_by_ids(context=context, target_company_id=co_id, target_branch_id=None)
    return co_id  # type: ignore[return-value]


# =========================
# Minimal list query: SI
# =========================
def build_sales_invoices_query(session: Session, context: AffiliationContext):
    """
    Sales Invoices list — minimal columns only:
      id, code, customer_name, status, posting_date, total_amount

    Tenant rule (ERP-style):
      ✅ Same company: all branches visible (no branch restriction)
      ✅ Different company: never visible (company_id filter + scope guard)
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesInvoice.id).where(false())

    co_id = _require_company_scope(context)

    SI = SalesInvoice
    C = Party

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
        # tenant-safe join (prevents accidental cross-company joins if data is corrupted)
        .join(C, and_(C.id == SI.customer_id, C.company_id == SI.company_id))
        .where(SI.company_id == co_id)
    )

    return q


# =========================
# Minimal list query: SDN
# =========================

# =========================
# Minimal list query: SQ
# =========================
def build_sales_quotations_query(session: Session, context: AffiliationContext):
    """
    Sales Quotations list — minimal columns:
      id, code, customer_name, status, posting_date
    (No total_amount on header model.)
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(SalesQuotation.id).where(false())

    co_id = _require_company_scope(context)

    SQ = SalesQuotation
    C = Party

    q = (
        select(
            SQ.id.label("id"),
            SQ.code.label("code"),
            C.name.label("customer_name"),
            SQ.doc_status.label("status"),
            _ymd(SQ.posting_date).label("posting_date"),
        )
        .select_from(SQ)
        .join(C, and_(C.id == SQ.customer_id, C.company_id == SQ.company_id))
        .where(SQ.company_id == co_id)
    )

    return q
