from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, desc, func
from sqlalchemy.orm import Session, aliased

from app.application_accounting.chart_of_accounts.models import (
    JournalEntry,
    JournalEntryItem,
    Account,
)
from app.application_org.models.company import Branch, Company
from app.auth.models.users import User
from app.security.rbac_effective import AffiliationContext


def build_journal_entries_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Journal Entries with ERP-style presentation.

    Columns:
      - id
      - code
      - posting_date (formatted)
      - status
      - entry_type
      - location (branch)
      - created_by (username)
      - title (smart-ish: first account name or code)
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(JournalEntry.id).where(false())

    je = JournalEntry
    b = Branch
    c = Company
    u = User
    jli = aliased(JournalEntryItem)
    acc = aliased(Account)

    posting_date_formatted = func.to_char(je.posting_date, "MM/DD/YYYY").label(
        "posting_date"
    )

    # "First" account name (min is fine) → used for smart title
    first_account_name = func.min(acc.name)

    q = (
        select(
            je.id.label("id"),
            je.code.label("code"),
            posting_date_formatted,
            je.doc_status.label("status"),
            je.entry_type.label("entry_type"),
            b.name.label("location"),
            u.username.label("created_by"),
            func.coalesce(first_account_name, je.code).label("title"),
        )
        .select_from(je)
        .join(c, c.id == je.company_id)
        .join(b, b.id == je.branch_id)
        .join(u, u.id == je.created_by_id)
        .outerjoin(jli, jli.journal_entry_id == je.id)
        .outerjoin(acc, acc.id == jli.account_id)
        .where(je.company_id == co_id)
        .group_by(
            je.id,
            je.code,
            posting_date_formatted,
            je.doc_status,
            je.entry_type,
            b.name,
            u.username,
        )
        .order_by(desc(je.posting_date), desc(je.id))  # newest first
    )

    return q
