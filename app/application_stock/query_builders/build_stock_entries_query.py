from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, desc, func
from sqlalchemy.orm import Session, aliased

from app.application_stock.stock_models import StockEntry, StockEntryItem, Warehouse
from app.application_org.models.company import Branch, Company
from app.security.rbac_effective import AffiliationContext


def build_stock_entries_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Stock Entries with ERP-style presentation.

    Columns:
      - id
      - code
      - posting_date (formatted)
      - status
      - entry_type
      - source_warehouse   (first / min source warehouse name across lines)
      - target_warehouse   (first / min target warehouse name across lines)
      - location (branch name)

    Scope:
      - Company-only (no branch RBAC). If context.company_id matches, the user
        can see all Stock Entries of that company.
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(StockEntry.id).where(false())

    se = StockEntry
    sei = StockEntryItem
    b = Branch
    c = Company
    w_from = aliased(Warehouse)
    w_to = aliased(Warehouse)

    location_display = b.name.label("location")

    posting_date_formatted = func.to_char(se.posting_date, "MM/DD/YYYY").label(
        "posting_date"
    )

    # Aggregate "first" source/target warehouse names using min()
    first_source_wh_name = func.min(w_from.name).label("source_warehouse")
    first_target_wh_name = func.min(w_to.name).label("target_warehouse")

    q = (
        select(
            se.id.label("id"),
            se.code.label("code"),
            posting_date_formatted,
            se.doc_status.label("status"),
            se.stock_entry_type.label("entry_type"),
            first_source_wh_name,
            first_target_wh_name,
            location_display,
        )
        .select_from(se)
        .join(c, c.id == se.company_id)
        .join(b, b.id == se.branch_id)
        .outerjoin(sei, sei.stock_entry_id == se.id)
        .outerjoin(w_from, w_from.id == sei.source_warehouse_id)
        .outerjoin(w_to, w_to.id == sei.target_warehouse_id)
        .where(se.company_id == co_id)
        .group_by(
            se.id,
            se.code,
            posting_date_formatted,
            se.doc_status,
            se.stock_entry_type,
            b.name,
        )
        .order_by(desc(se.posting_date), desc(se.id))  # newest first
    )

    return q
