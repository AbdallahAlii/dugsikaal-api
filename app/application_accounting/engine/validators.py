# application_accounting/engine/validators.py
from __future__ import annotations
from decimal import Decimal
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.application_accounting.chart_of_accounts.models import FiscalYear, Account, JournalEntry
from app.application_accounting.engine.errors import FiscalYearClosedError, AccountNotFoundError, \
    PostingValidationError, IdempotencyError
from app.common.models.base import StatusEnum
from app.application_stock.stock_models import DocStatusEnum

def ensure_fiscal_year_open(s: Session, company_id: int, posting_date: datetime) -> int:
    fy = s.execute(
        select(FiscalYear).where(
            FiscalYear.company_id == company_id,
            FiscalYear.start_date <= posting_date,
            FiscalYear.end_date >= posting_date,
            FiscalYear.status == "Open",
        )
    ).scalar_one_or_none()
    if not fy:
        raise FiscalYearClosedError("Posting date is outside an open fiscal year.")
    return fy.id

def ensure_accounts_exist(s: Session, company_id: int, account_ids: Iterable[int]) -> None:
    if not account_ids:
        return
    q = select(Account.id, Account.is_group).where(Account.company_id == company_id, Account.id.in_(list(account_ids)))
    rows = {row.id: row for row in s.execute(q)}
    for aid in set(account_ids):
        row = rows.get(aid)
        if not row:
            raise AccountNotFoundError(f"Account id {aid} not found in company {company_id}.")
        if getattr(row, "is_group", True):
            raise AccountNotFoundError(f"Account id {aid} is a group account; posting allowed only on leaf accounts.")

def ensure_balanced(total_debit: Decimal, total_credit: Decimal) -> None:
    if (total_debit or 0) != (total_credit or 0):
        raise PostingValidationError(f"Journal not balanced. DR={total_debit} CR={total_credit}.")

# def ensure_idempotent_absent(
#     s: Session,
#     *, company_id: int, source_doctype_id: int, source_doc_id: int, entry_type: str
# ) -> None:
#     """
#     Soft idempotency guard: reject if an AUTO journal already exists for same doc and entry type.
#     """
#     exists = s.execute(
#         select(JournalEntry.id).where(
#             JournalEntry.company_id == company_id,
#             JournalEntry.source_doctype_id == source_doctype_id,
#             JournalEntry.source_doc_id == source_doc_id,
#             JournalEntry.entry_type == entry_type,
#             JournalEntry.is_auto_generated == True,   # noqa
#             JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
#         ).limit(1)
#     ).scalar_one_or_none()
#     if exists:
#         raise IdempotencyError("An auto-generated journal for this document/action already exists.")
def ensure_idempotent_absent(
        s: Session,
        *, company_id: int, source_doctype_id: int, source_doc_id: int, entry_type: str
) -> None:
    """
    Soft idempotency guard: reject if an AUTO journal already exists for same doc and entry type.
    """
    # DEBUG: Log what we're looking for
    print(
        f"🔍 IDEMPOTENCY CHECK: Looking for company_id={company_id}, source_doctype_id={source_doctype_id}, source_doc_id={source_doc_id}, entry_type={entry_type}")

    exists = s.execute(
        select(JournalEntry.id).where(
            JournalEntry.company_id == company_id,
            JournalEntry.source_doctype_id == source_doctype_id,
            JournalEntry.source_doc_id == source_doc_id,
            JournalEntry.entry_type == entry_type,
            JournalEntry.is_auto_generated == True,  # noqa
            JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
        ).limit(1)
    ).scalar_one_or_none()

    # DEBUG: Log what we found
    if exists:
        print(f"🚫 IDEMPOTENCY BLOCKED: Found existing Journal Entry ID {exists}")
        # Let's see what this journal actually is
        je = s.execute(
            select(JournalEntry).where(JournalEntry.id == exists)
        ).scalar_one_or_none()
        if je:
            print(
                f"📄 Existing JE: source_doctype_id={je.source_doctype_id}, source_doc_id={je.source_doc_id}, code={je.code}")
    else:
        print(f"✅ IDEMPOTENCY PASSED: No existing journal found")

    if exists:
        raise IdempotencyError("An auto-generated journal for this document/action already exists.")