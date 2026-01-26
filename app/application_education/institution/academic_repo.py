from __future__ import annotations

from typing import Optional, List

from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from config.database import db
from app.application_education.institution.academic_model import (
    EducationSettings,
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)


class EducationRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ----------------------------
    # Settings
    # ----------------------------

    def get_settings(self, company_id: int) -> Optional[EducationSettings]:
        return self.s.scalar(
            select(EducationSettings).where(EducationSettings.company_id == company_id)
        )

    def create_settings(self, row: EducationSettings) -> EducationSettings:
        self.s.add(row)
        self.s.flush([row])
        return row

    def ensure_settings(self, company_id: int) -> EducationSettings:
        row = self.get_settings(company_id)
        if row:
            return row
        row = EducationSettings(company_id=company_id)
        self.s.add(row)
        self.s.flush([row])
        return row

    def update_settings_fields(self, row: EducationSettings, data: dict) -> None:
        for k, v in data.items():
            if hasattr(row, k) and v is not None:
                setattr(row, k, v)
        self.s.flush([row])

    # ----------------------------
    # Academic Year
    # ----------------------------

    def get_year(self, year_id: int) -> Optional[AcademicYear]:
        return self.s.get(AcademicYear, year_id)

    def year_name_exists(self, company_id: int, name: str, *, exclude_id: Optional[int] = None) -> bool:
        stmt = select(AcademicYear.id).where(
            AcademicYear.company_id == company_id,
            func.lower(AcademicYear.name) == func.lower(name.strip()),
        )
        if exclude_id:
            stmt = stmt.where(AcademicYear.id != exclude_id)
        return bool(self.s.scalar(stmt))

    def create_year(self, row: AcademicYear) -> AcademicYear:
        self.s.add(row)
        self.s.flush([row])
        return row

    def update_year_fields(self, row: AcademicYear, data: dict) -> None:
        for k, v in data.items():
            if hasattr(row, k) and v is not None:
                setattr(row, k, v)
        self.s.flush([row])

    def clear_other_current_years(self, company_id: int, keep_year_id: int) -> None:
        # enforces your partial unique index expectation
        self.s.execute(
            update(AcademicYear)
            .where(AcademicYear.company_id == company_id)
            .where(AcademicYear.id != keep_year_id)
            .values(is_current=False)
        )
        self.s.flush()

    def get_current_year(self, company_id: int) -> Optional[AcademicYear]:
        return self.s.scalar(
            select(AcademicYear)
            .where(AcademicYear.company_id == company_id)
            .where(AcademicYear.is_current.is_(True))
            .order_by(AcademicYear.start_date.desc())
        )

    def get_open_year(self, company_id: int) -> Optional[AcademicYear]:
        return self.s.scalar(
            select(AcademicYear)
            .where(AcademicYear.company_id == company_id)
            .where(AcademicYear.status == AcademicStatusEnum.OPEN)
            .order_by(AcademicYear.start_date.desc())
        )

    def list_years(self, company_id: int) -> List[AcademicYear]:
        stmt = (
            select(AcademicYear)
            .where(AcademicYear.company_id == company_id)
            .order_by(AcademicYear.start_date.desc())
        )
        return list(self.s.scalars(stmt))

    # ----------------------------
    # Academic Term
    # ----------------------------

    def get_term(self, term_id: int) -> Optional[AcademicTerm]:
        return self.s.get(AcademicTerm, term_id)

    def term_name_exists(
        self,
        company_id: int,
        academic_year_id: int,
        name: str,
        *,
        exclude_id: Optional[int] = None,
    ) -> bool:
        stmt = select(AcademicTerm.id).where(
            AcademicTerm.company_id == company_id,
            AcademicTerm.academic_year_id == academic_year_id,
            func.lower(AcademicTerm.name) == func.lower(name.strip()),
        )
        if exclude_id:
            stmt = stmt.where(AcademicTerm.id != exclude_id)
        return bool(self.s.scalar(stmt))

    def create_term(self, row: AcademicTerm) -> AcademicTerm:
        self.s.add(row)
        self.s.flush([row])
        return row

    def update_term_fields(self, row: AcademicTerm, data: dict) -> None:
        for k, v in data.items():
            if hasattr(row, k) and v is not None:
                setattr(row, k, v)
        self.s.flush([row])

    def list_terms_for_year(self, academic_year_id: int) -> List[AcademicTerm]:
        stmt = (
            select(AcademicTerm)
            .where(AcademicTerm.academic_year_id == academic_year_id)
            .order_by(AcademicTerm.start_date.asc())
        )
        return list(self.s.scalars(stmt))

    def get_open_term(self, company_id: int) -> Optional[AcademicTerm]:
        return self.s.scalar(
            select(AcademicTerm)
            .where(AcademicTerm.company_id == company_id)
            .where(AcademicTerm.status == AcademicStatusEnum.OPEN)
            .order_by(AcademicTerm.start_date.desc())
        )
