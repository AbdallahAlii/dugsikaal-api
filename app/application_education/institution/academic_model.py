# app/application_education/core/models.py
from __future__ import annotations

import enum
from datetime import date
from typing import Optional, List

from sqlalchemy import (
    UniqueConstraint,
    Index,
    CheckConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


class AcademicStatusEnum(str, enum.Enum):
    OPEN = "Open"
    CLOSED = "Closed"
    DRAFT = "Draft"


class EducationSettings(BaseModel, TenantMixin):
    """
    One row per company.
    Stores defaults and education behaviour for the Education module.
    """
    __tablename__ = "edu_settings"

    # -------- Default academic context -------- #

    default_academic_year_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_academic_term_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # -------- Behaviour flags -------- #

    validate_batch_in_student_group: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        comment="If true, require batch when creating student group.",
    )

    attendance_based_on_course_schedule: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        comment=(
            "If true, attendance uses course schedule; "
            "otherwise uses student group as the main attendance unit."
        ),
    )

    # -------- Working week & holidays (education module) -------- #

    working_days: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        default="SUN,MON,TUE,WED,THU",
        comment="Comma-separated weekday codes: SUN,MON,TUE,WED,THU,FRI,SAT",
    )

    weekly_off_days: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        default="FRI,SAT",
        comment="Comma-separated weekday codes that are off for academic calendar.",
    )

    default_holiday_list_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("holiday_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Default holiday list used for academic calendar (timetables, attendance, exams).",
    )

    # -------- Relationships -------- #

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="education_settings",
        lazy="joined",
    )

    default_academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear",
        foreign_keys=[default_academic_year_id],
        lazy="joined",
    )

    default_academic_term: Mapped[Optional["AcademicTerm"]] = relationship(
        "AcademicTerm",
        foreign_keys=[default_academic_term_id],
        lazy="joined",
    )

    default_holiday_list: Mapped[Optional["HolidayList"]] = relationship(
        "HolidayList",
        foreign_keys=[default_holiday_list_id],
        lazy="joined",
    )

    __table_args__ = (
        # One settings row per company
        UniqueConstraint("company_id", name="uq_edu_settings_per_company"),
        # ✅ No composite ForeignKeyConstraint rows here anymore
    )

    def __repr__(self) -> str:
        return f"<EducationSettings id={self.id} company_id={self.company_id}>"


class AcademicYear(BaseModel, TenantMixin):
    __tablename__ = "edu_academic_years"

    name: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        comment="e.g. '2024-2025'",
    )
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(db.Date, nullable=False)

    is_current: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
    )

    status: Mapped[AcademicStatusEnum] = mapped_column(
        db.Enum(AcademicStatusEnum, name="academic_year_status_enum"),
        nullable=False,
        default=AcademicStatusEnum.DRAFT,
        index=True,
    )

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="academic_years",
        lazy="joined",
    )
    terms: Mapped[List["AcademicTerm"]] = relationship(
        "AcademicTerm",
        back_populates="academic_year",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_academic_year_per_company"),
        CheckConstraint("start_date <= end_date", name="ck_academic_year_range"),
        Index(
            "ix_current_year_per_company",
            "company_id",
            unique=True,
            postgresql_where=text("is_current = TRUE"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AcademicYear id={self.id} company_id={self.company_id} "
            f"name={self.name!r} current={self.is_current}>"
        )


class AcademicTerm(BaseModel, TenantMixin):
    __tablename__ = "edu_academic_terms"

    academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        comment="e.g. 'Term 1', 'Semester 2'",
    )
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(db.Date, nullable=False)

    status: Mapped[AcademicStatusEnum] = mapped_column(
        db.Enum(AcademicStatusEnum, name="academic_term_status_enum"),
        nullable=False,
        default=AcademicStatusEnum.DRAFT,
        index=True,
    )

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="academic_terms",
        lazy="joined",
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear",
        back_populates="terms",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "academic_year_id", "name",
            name="uq_term_name_per_year_per_company",
        ),
        CheckConstraint("start_date <= end_date", name="ck_academic_term_range"),
    )

    def __repr__(self) -> str:
        return (
            f"<AcademicTerm id={self.id} company_id={self.company_id} "
            f"year_id={self.academic_year_id} name={self.name!r}>"
        )
