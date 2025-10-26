from __future__ import annotations
from typing import Optional, Sequence, List, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.application_accounting.chart_of_accounts.models import (
    JournalEntry, JournalEntryItem, PeriodClosingVoucher, Account, GeneralLedgerEntry, FiscalYear
)

class JournalRepo:
    def __init__(self, s: Session):
        self.s = s

    def get_je(self, je_id: int, company_ids: Sequence[int], branch_ids: Sequence[int]) -> Optional[JournalEntry]:
        return self.s.execute(
            select(JournalEntry).where(
                JournalEntry.id == je_id,
                JournalEntry.company_id.in_(company_ids),
                JournalEntry.branch_id.in_(branch_ids),
            )
        ).scalar_one_or_none()

    def list_je_items(self, je_id: int) -> List[JournalEntryItem]:
        return list(self.s.execute(
            select(JournalEntryItem).where(JournalEntryItem.journal_entry_id == je_id).order_by(JournalEntryItem.id.asc())
        ).scalars().all())

class PCVRepo:
    def __init__(self, s: Session):
        self.s = s

    def get_pcv(self, pcv_id: int, company_ids: Sequence[int], branch_ids: Sequence[int]) -> Optional[PeriodClosingVoucher]:
        return self.s.execute(
            select(PeriodClosingVoucher).where(
                PeriodClosingVoucher.id == pcv_id,
                PeriodClosingVoucher.company_id.in_(company_ids),
                PeriodClosingVoucher.branch_id.in_(branch_ids),
            )
        ).scalar_one_or_none()

    def fy_by_id(self, fy_id: int, company_ids: Sequence[int]) -> Optional[FiscalYear]:
        return self.s.execute(
            select(FiscalYear).where(
                FiscalYear.id == fy_id,
                FiscalYear.company_id.in_(company_ids)
            )
        ).scalar_one_or_none()

    def pl_account_balances(
        self, *, company_id: int, fiscal_year_id: int, up_to_date
    ) -> List[Tuple[int, float, float]]:
        """
        Return [(account_id, sum_debit, sum_credit)] for all P&L leaf accounts up to posting date.
        """
        q = (
            select(
                GeneralLedgerEntry.account_id,
                func.coalesce(func.sum(GeneralLedgerEntry.debit), 0),
                func.coalesce(func.sum(GeneralLedgerEntry.credit), 0),
            )
            .join(Account, Account.id == GeneralLedgerEntry.account_id)
            .where(
                GeneralLedgerEntry.company_id == company_id,
                GeneralLedgerEntry.fiscal_year_id == fiscal_year_id,
                GeneralLedgerEntry.posting_date <= up_to_date,
                Account.report_type == "Profit & Loss",
                Account.is_group == False,  # noqa
            )
            .group_by(GeneralLedgerEntry.account_id)
        )
        return list(self.s.execute(q).all())
