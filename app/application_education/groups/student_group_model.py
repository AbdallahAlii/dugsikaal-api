# app/application_education/groups/models.py
from __future__ import annotations

import enum
from datetime import date
from typing import Optional, List

from sqlalchemy import (
    UniqueConstraint,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


# =========================
# Simple global Section
# =========================

class Section(BaseModel):
    """
    Simple label for sections/shifts:
    - 'A', 'B'
    - 'Morning', 'Afternoon'
    Global (no TenantMixin) so all companies reuse the same names.
    """
    __tablename__ = "edu_sections"

    section_name: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        unique=True,
    )

    __table_args__ = (
        UniqueConstraint("section_name", name="uq_section_name_global"),
    )

    def __repr__(self) -> str:
        return f"<Section id={self.id} name={self.section_name!r}>"


# =========================
# Batch & Category
# =========================

class Batch(BaseModel, TenantMixin):
    """
    Batch = intake/cohort at company level.

    Examples:
      - '2025-2026 Intake'
      - 'Spring 2026'
      - '2025 Boarding Intake'

    Optionally tied to a branch (campus).
    """
    __tablename__ = "edu_batches"

    batch_name: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
    )

    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # ------------ Relationships ------------

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="batches",
        lazy="joined",
    )
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )

    student_groups: Mapped[List["StudentGroup"]] = db.relationship(
        "StudentGroup",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "batch_name", "branch_id",
            name="uq_batch_name_per_company_branch",
        ),
        Index("ix_edu_batches_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Batch id={self.id} company_id={self.company_id} "
            f"name={self.batch_name!r} branch_id={self.branch_id}>"
        )


class StudentCategory(BaseModel, TenantMixin):
    """
    Logical grouping of students for fees / reporting:
    - 'Scholarship'
    - 'Special Needs'
    - 'Boarding'
    - 'Staff Children'
    """
    __tablename__ = "student_categories"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)
    is_default: Mapped[bool] = mapped_column(
        db.Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="student_categories",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_student_category_per_company"),
        Index("ix_student_categories_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentCategory id={self.id} company_id={self.company_id} "
            f"name={self.name!r}>"
        )


# =========================
# Group enums
# =========================

class GroupBasedOnEnum(str, enum.Enum):
    """
    Optional flag: what logic is used to create this group.
    Just metadata for UI/filters.
    """
    BATCH = "BATCH"
    COURSE = "COURSE"
    ACTIVITY = "ACTIVITY"  # free-form; manual rostering


# =========================
# StudentGroup
# =========================

class StudentGroup(BaseModel, TenantMixin):
    """
    The 'class' / 'cohort' entity.

    Links:
      - Program (grade/track)
      - AcademicYear (optional)
      - AcademicTerm (optional)
      - Batch (intake)
      - Section (A/B/Morning)
      - StudentCategory (Scholarship etc.)

    Examples:
      - 'Grade 1 - A (2025-26)'
      - 'Diploma IT - Evening Batch 3'
    """
    __tablename__ = "edu_student_groups"

    program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_year_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    academic_term_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    batch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    section_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    student_category_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("student_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Optional: campus context (if you want groups per branch)
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        comment="Human label, e.g., 'Grade 1 - A (2025-26)'.",
    )

    group_based_on: Mapped[Optional[GroupBasedOnEnum]] = mapped_column(
        db.Enum(GroupBasedOnEnum, name="edu_group_based_on_enum"),
        nullable=True,
        index=True,
        comment="Optional metadata on how this group was created.",
    )

    capacity: Mapped[Optional[int]] = mapped_column(db.Integer)
    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # ------------ Relationships ------------

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="student_groups",
        lazy="joined",
    )
    program: Mapped["Program"] = db.relationship(
        "Program",
        back_populates="groups",
        lazy="joined",
    )
    academic_year: Mapped[Optional["AcademicYear"]] = db.relationship(
        "AcademicYear",
        lazy="joined",
    )
    academic_term: Mapped[Optional["AcademicTerm"]] = db.relationship(
        "AcademicTerm",
        lazy="joined",
    )

    batch: Mapped[Optional["Batch"]] = db.relationship(
        "Batch",
        back_populates="student_groups",
        lazy="joined",
    )
    section: Mapped[Optional["Section"]] = db.relationship(
        "Section",
        lazy="joined",
    )
    student_category: Mapped[Optional["StudentCategory"]] = db.relationship(
        "StudentCategory",
        lazy="joined",
    )

    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )

    members: Mapped[List["StudentGroupMembership"]] = db.relationship(
        "StudentGroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Unique section per program + year (nice safety)
        UniqueConstraint(
            "company_id", "program_id", "academic_year_id", "section_id",
            name="uq_group_program_year_section",
        ),
        # Unique name per program + year
        UniqueConstraint(
            "company_id", "program_id", "academic_year_id", "name",
            name="uq_group_name_per_program_year",
        ),

        CheckConstraint(
            "capacity IS NULL OR capacity >= 0",
            name="ck_group_capacity_nonneg",
        ),
        Index("ix_edu_student_groups_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentGroup id={self.id} company_id={self.company_id} "
            f"name={self.name!r} program_id={self.program_id}>"
        )


# =========================
# StudentGroupMembership
# =========================

class StudentGroupMembership(BaseModel, TenantMixin):
    """
    Roster row: a student belonging to a group for some time.

    You can move students between groups by:
      - closing old membership (set left_on)
      - creating new membership with new group_id
    """
    __tablename__ = "edu_student_group_memberships"

    group_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_student_groups.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    joined_on: Mapped[Optional[date]] = mapped_column(db.Date)
    left_on: Mapped[Optional[date]] = mapped_column(db.Date)

    # ------------ Relationships ------------

    group: Mapped["StudentGroup"] = db.relationship(
        "StudentGroup",
        back_populates="members",
        lazy="joined",
    )
    student: Mapped["Student"] = db.relationship(
        "Student",
        lazy="joined",
    )

    __table_args__ = (
        # A student cannot appear twice in the same group
        UniqueConstraint(
            "group_id", "student_id", name="uq_student_once_per_group"
        ),

        # Valid date range
        CheckConstraint(
            "(joined_on IS NULL) OR (left_on IS NULL) OR (joined_on <= left_on)",
            name="ck_sgm_dates_ok",
        ),

        Index("ix_edu_student_group_memberships_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentGroupMembership id={self.id} company_id={self.company_id} "
            f"group_id={self.group_id} student_id={self.student_id}>"
        )
