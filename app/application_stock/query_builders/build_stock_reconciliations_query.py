#
#
# from __future__ import annotations
# from typing import Optional
#
# from sqlalchemy import select, false, desc, func
# from sqlalchemy.orm import Session
#
# from app.application_stock.stock_models import StockReconciliation
# from app.application_org.models.company import Branch, Company
# from app.auth.models.users import User
# from app.security.rbac_effective import AffiliationContext
#
#
# def build_stock_reconciliations_query(session: Session, context: AffiliationContext):
#     """
#     Fast, secure stock reconciliation list with Frappe-style ERP presentation.
#     Uses database functions for date formatting.
#     """
#     co_id: Optional[int] = getattr(context, "company_id", None)
#     if co_id is None:
#         return select(StockReconciliation.id).where(false())
#
#     sr = StockReconciliation
#     b = Branch
#     c = Company
#     u = User
#
#     # Frappe-style location display (branch name)
#     location_display = b.name.label("location")
#     created_by_display = u.username.label("created_by")
#
#     # Format posting_date as separate date and time for clean display
#     # Use database functions for optimal performance
#     posting_date_formatted = func.to_char(sr.posting_date, 'MM/DD/YYYY').label("posting_date")
#     posting_time_formatted = func.to_char(sr.posting_date, 'HH12:MI AM').label("posting_time")
#
#     # Main query with clean ERP display fields only
#     q = (
#         select(
#             sr.id.label("id"),
#             sr.code.label("code"),
#             posting_date_formatted,  # Formatted as MM/DD/YYYY
#             posting_time_formatted,  # Formatted as HH12:MI AM
#             sr.doc_status.label("status"),
#             location_display,
#             created_by_display,
#             sr.purpose.label("purpose"),
#         )
#         .select_from(sr)
#         .join(c, c.id == sr.company_id)
#         .join(b, b.id == sr.branch_id)
#         .join(u, u.id == sr.created_by_id)
#         .where(sr.company_id == co_id)
#     )
#
#     # RBAC Filtering
#     if not getattr(context, "is_system_admin", False):
#         roles = getattr(context, "roles", []) or []
#         has_company_wide_access = any(role in ["Owner", "Super Admin"] for role in roles)
#
#         if not has_company_wide_access:
#             branch_ids = list(getattr(context, "branch_ids", []) or [])
#             if branch_ids:
#                 q = q.where(sr.branch_id.in_(branch_ids))
#             else:
#                 return select(sr.id).where(false())
#
#     return q
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, desc, func
from sqlalchemy.orm import Session

from app.application_stock.stock_models import StockReconciliation
from app.application_org.models.company import Branch, Company
from app.auth.models.users import User
from app.security.rbac_effective import AffiliationContext


def build_stock_reconciliations_query(session: Session, context: AffiliationContext):
    """
    Fast, secure stock reconciliation list with Frappe-style ERP presentation.

    Scope:
    - Company-wide: any user whose context.company_id == doc.company_id
      can see all Stock Reconciliations for that company (no branch filter).

    Presentation:
    - Frappe-style columns (code, posting date/time, status, location, created_by, purpose)
    - Newest posting_date first.
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        # No company in context → nothing
        return select(StockReconciliation.id).where(false())

    sr = StockReconciliation
    b = Branch
    c = Company
    u = User

    location_display = b.name.label("location")
    created_by_display = u.username.label("created_by")

    posting_date_formatted = func.to_char(sr.posting_date, "MM/DD/YYYY").label(
        "posting_date"
    )
    posting_time_formatted = func.to_char(sr.posting_date, "HH12:MI AM").label(
        "posting_time"
    )

    q = (
        select(
            sr.id.label("id"),
            sr.code.label("code"),
            posting_date_formatted,
            posting_time_formatted,
            sr.doc_status.label("status"),
            location_display,
            created_by_display,
            sr.purpose.label("purpose"),
        )
        .select_from(sr)
        .join(c, c.id == sr.company_id)
        .join(b, b.id == sr.branch_id)
        .join(u, u.id == sr.created_by_id)
        .where(sr.company_id == co_id)
        .order_by(desc(sr.posting_date), desc(sr.id))  # newest first
    )

    # ❗ No branch-level filtering here: ERP-style company scope
    return q
