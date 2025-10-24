from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session
import logging

from app.application_accounting.chart_of_accounts.models import FiscalYear, FiscalYearStatusEnum
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

    def check_date_overlap(self, company_id: int, start_date: datetime, end_date: datetime,
                           exclude_id: Optional[int] = None) -> bool:
        """Check if fiscal year dates overlap with existing ones"""
        query = select(FiscalYear).where(
            FiscalYear.company_id == company_id,
            or_(
                and_(FiscalYear.start_date <= start_date, FiscalYear.end_date >= start_date),
                and_(FiscalYear.start_date <= end_date, FiscalYear.end_date >= end_date),
                and_(FiscalYear.start_date >= start_date, FiscalYear.end_date <= end_date)
            )
        )

        if exclude_id:
            query = query.where(FiscalYear.id != exclude_id)

        return self.s.scalar(query) is not None

    def create_fiscal_year(self, fiscal_year: FiscalYear) -> FiscalYear:
        self.s.add(fiscal_year)
        self.s.flush()
        return fiscal_year

    def update_fiscal_year(self, fiscal_year: FiscalYear, updates: dict) -> None:
        for key, value in updates.items():
            setattr(fiscal_year, key, value)
        self.s.flush([fiscal_year])