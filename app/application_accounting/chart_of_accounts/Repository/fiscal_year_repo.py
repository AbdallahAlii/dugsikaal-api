from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session
import logging

from app.application_accounting.chart_of_accounts.models import (
    FiscalYear,
    FiscalYearStatusEnum,
    JournalEntry,
    GeneralLedgerEntry,
    PeriodClosingVoucher,
)
from config.database import db

log = logging.getLogger(__name__)


class FiscalYearRepository:
    def __init__(self, session: Session):
        self.s: Session = session

    def get_fiscal_year_by_id(self, fiscal_year_id: int) -> Optional[FiscalYear]:
        return self.s.get(FiscalYear, fiscal_year_id)

    def get_fiscal_year_by_name(self, company_id: int, name: str) -> Optional[FiscalYear]:
        return self.s.scalar(
            select(FiscalYear).where(
                FiscalYear.company_id == company_id,
                FiscalYear.name == name
            )
        )

    def get_open_fiscal_year(self, company_id: int) -> Optional[FiscalYear]:
        return self.s.scalar(
            select(FiscalYear).where(
                FiscalYear.company_id == company_id,
                FiscalYear.status == FiscalYearStatusEnum.OPEN
            )
        )

    def get_fiscal_years_by_company(self, company_id: int) -> List[FiscalYear]:
        return list(self.s.scalars(
            select(FiscalYear)
            .where(FiscalYear.company_id == company_id)
            .order_by(FiscalYear.start_date.desc())
        ))

    def check_date_overlap(
        self,
        company_id: int,
        start_date: datetime,
        end_date: datetime,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """
        Return True if the [start_date, end_date] range overlaps
        any existing fiscal year for the same company.
        Allows back-to-back years (no overlap when new.start > old.end
        or new.end < old.start).
        """
        query = select(FiscalYear).where(
            FiscalYear.company_id == company_id,
            FiscalYear.start_date <= end_date,
            FiscalYear.end_date >= start_date,
        )

        if exclude_id:
            query = query.where(FiscalYear.id != exclude_id)

        exists = self.s.scalar(query)
        return exists is not None

    # ------------ “in use” checks for delete ---------------- #

    def has_journal_entries(self, company_id: int, fiscal_year_id: int) -> bool:
        q = select(func.count(JournalEntry.id)).where(
            JournalEntry.company_id == company_id,
            JournalEntry.fiscal_year_id == fiscal_year_id,
        )
        return (self.s.scalar(q) or 0) > 0

    def has_general_ledger_entries(self, company_id: int, fiscal_year_id: int) -> bool:
        q = select(func.count(GeneralLedgerEntry.id)).where(
            GeneralLedgerEntry.company_id == company_id,
            GeneralLedgerEntry.fiscal_year_id == fiscal_year_id,
        )
        return (self.s.scalar(q) or 0) > 0

    def has_period_closing_vouchers(self, company_id: int, fiscal_year_id: int) -> bool:
        q = select(func.count(PeriodClosingVoucher.id)).where(
            PeriodClosingVoucher.company_id == company_id,
            PeriodClosingVoucher.closing_fiscal_year_id == fiscal_year_id,
        )
        return (self.s.scalar(q) or 0) > 0

    # ------------ CRUD helpers ---------------- #

    def create_fiscal_year(self, fiscal_year: FiscalYear) -> FiscalYear:
        self.s.add(fiscal_year)
        self.s.flush()
        return fiscal_year

    def update_fiscal_year(self, fiscal_year: FiscalYear, updates: dict) -> None:
        for key, value in updates.items():
            setattr(fiscal_year, key, value)
        self.s.flush([fiscal_year])

    def delete_fiscal_year(self, fiscal_year: FiscalYear) -> None:
        self.s.delete(fiscal_year)
        self.s.flush()
