# app/application_accounting/chart_of_accounts/Repository/journal_repo.py
from __future__ import annotations

from typing import Optional, Sequence, List, Tuple
from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session

from config.database import db
from app.application_accounting.chart_of_accounts.models import (
    JournalEntry,
    JournalEntryItem,
    PeriodClosingVoucher,
    Account,
    GeneralLedgerEntry,
    FiscalYear,
)
from app.common.models.base import StatusEnum
from app.application_stock.stock_models import DocStatusEnum  # if used here


class JournalRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    # ---------- generic save ----------
    def save(self, obj):
        """Add object to session and flush (no commit)."""
        if obj not in self.s:
            self.s.add(obj)
        self.s.flush()
        return obj

    # ---------- code existence ----------
    def code_exists_je(self, company_id: int, branch_id: int, code: str) -> bool:
        stmt = select(
            exists().where(
                JournalEntry.company_id == company_id,
                JournalEntry.branch_id == branch_id,
                func.lower(JournalEntry.code) == func.lower(code),
            )
        )
        return bool(self.s.execute(stmt).scalar())

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        """Same pattern as SalesRepository.get_branch_company_id."""
        from app import Branch
        return self.s.execute(
            select(Branch.company_id).where(Branch.id == branch_id)
        ).scalar_one_or_none()

    # ---------- fetch ----------
    def get_je(self, je_id: int, for_update: bool = False) -> Optional[JournalEntry]:
        """
        Same idea as SalesRepository.get_si: just load the JE by id.
        Scope is enforced later via ensure_scope_by_ids.
        """
        stmt = select(JournalEntry).where(JournalEntry.id == je_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def list_je_items(self, je_id: int) -> List[JournalEntryItem]:
        return list(
            self.s.execute(
                select(JournalEntryItem)
                .where(JournalEntryItem.journal_entry_id == je_id)
                .order_by(JournalEntryItem.id.asc())
            )
            .scalars()
            .all()
        )


class PCVRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        """For resolve_company_branch_and_scope in PCV service."""
        from app import Branch
        return self.s.execute(
            select(Branch.company_id).where(Branch.id == branch_id)
        ).scalar_one_or_none()

    def get_pcv(
        self,
        pcv_id: int,
        company_ids: Sequence[int],
        branch_ids: Sequence[int],
    ) -> Optional[PeriodClosingVoucher]:
        return (
            self.s.execute(
                select(PeriodClosingVoucher).where(
                    PeriodClosingVoucher.id == pcv_id,
                    PeriodClosingVoucher.company_id.in_(company_ids),
                    PeriodClosingVoucher.branch_id.in_(branch_ids),
                )
            )
            .scalar_one_or_none()
        )

    def fy_by_id(
        self,
        fy_id: int,
        company_ids: Sequence[int],
    ) -> Optional[FiscalYear]:
        return (
            self.s.execute(
                select(FiscalYear).where(
                    FiscalYear.id == fy_id,
                    FiscalYear.company_id.in_(company_ids),
                )
            )
            .scalar_one_or_none()
        )

    def pl_account_balances(
        self,
        *,
        company_id: int,
        fiscal_year_id: int,
        up_to_date,
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
