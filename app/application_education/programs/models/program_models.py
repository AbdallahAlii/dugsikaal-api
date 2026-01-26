from __future__ import annotations

import enum
from datetime import date
from typing import Optional, List

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


# ---------------- Enums ----------------

class ProgramTypeEnum(str, enum.Enum):
    """
    K12      -> grades (Grade 1, Grade 2, Form 1 ...)
    INSTITUTE -> vocational / college programs (Diploma, Course tracks)
    QURAN    -> dedicated Quran/Hifz programs
    """
    K12 = "K12"
    INSTITUTE = "INSTITUTE"
    QURAN = "QURAN"


class CourseTypeEnum(str, enum.Enum):
    CORE = "Core"
    ELECTIVE = "Elective"


# ---------------- Program ----------------

class Program(BaseModel, TenantMixin):
    """
    Program = "Grade" or "Course Track"

    - K-12:
        One Program per grade (e.g. 'Grade 1', 'Grade 2', 'Form 1').
    - Institute:
        'English A1 (6 months)', 'AutoCAD Diploma', 'IT Level 1'.
    - Quran:
        'Quran Hifz Full', 'Quran Recitation', etc.

    Programs are NOT recreated every year.
    Student groups (cohorts) are yearly/term based and link here.
    """
    __tablename__ = "edu_programs"

    name: Mapped[str] = mapped_column(db.String(255), nullable=False)

    program_type: Mapped[ProgramTypeEnum] = mapped_column(
        db.Enum(ProgramTypeEnum, name="program_type_enum"),
        nullable=False,
        default=ProgramTypeEnum.K12,
        index=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Disable to stop using program in new records.",
    )

    # ------------- Relationships -------------

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="programs",
        lazy="joined",
    )

    # Curriculum links: which courses belong to this program
    courses: Mapped[List["ProgramCourse"]] = db.relationship(
        "ProgramCourse",
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Enrollments + groups
    enrollments: Mapped[List["ProgramEnrollment"]] = db.relationship(
        "ProgramEnrollment",
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    groups: Mapped[List["StudentGroup"]] = db.relationship(
        "StudentGroup",
        back_populates="program",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    progression_from_rules: Mapped[list["ProgramProgressionRule"]] = db.relationship(
        "ProgramProgressionRule",
        foreign_keys="[ProgramProgressionRule.from_program_id]",
        back_populates="from_program",
        lazy="selectin",
    )

    progression_to_rules: Mapped[list["ProgramProgressionRule"]] = db.relationship(
        "ProgramProgressionRule",
        foreign_keys="[ProgramProgressionRule.to_program_id]",
        back_populates="to_program",
        lazy="selectin",
    )

    __table_args__ = (
        # Each company cannot have two programs with the same name
        UniqueConstraint("company_id", "name", name="uq_program_name_per_company"),
        Index("ix_edu_programs_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<Program id={self.id} company_id={self.company_id} name={self.name!r}>"


# ---------------- Course ----------------

class Course(BaseModel, TenantMixin):
    """
    Course = 'Subject' / 'Module'.

    - K-12: 'Mathematics', 'Physics', 'Somali', 'Islamic Studies'
    - Institute: 'AutoCAD Level 1', 'Python Basics', 'Networking 101'
    - Quran: 'Juz 1–2', 'Tajweed Basics', etc.

    Course is generic. It becomes part of a curriculum when linked
    to a Program via ProgramCourse.
    """
    __tablename__ = "edu_courses"

    name: Mapped[str] = mapped_column(db.String(255), nullable=False)

    course_type: Mapped[CourseTypeEnum] = mapped_column(
        db.Enum(CourseTypeEnum, name="course_type_enum"),
        nullable=False,
        default=CourseTypeEnum.CORE,
        index=True,
    )

    credit_hours: Mapped[Optional[int]] = mapped_column(
        db.Integer,
        comment="Optional credit hours / weekly periods.",
    )
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # ------------- Relationships -------------

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="courses",
        lazy="joined",
    )

    # Links to programs (curriculum)
    program_links: Mapped[List["ProgramCourse"]] = db.relationship(
        "ProgramCourse",
        back_populates="course",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    course_enrollments: Mapped[list["CourseEnrollment"]] = db.relationship(
        "CourseEnrollment",
        back_populates="course",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_course_name_per_company"),
        Index("ix_edu_courses_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<Course id={self.id} company_id={self.company_id} name={self.name!r}>"


# ---------------- ProgramCourse ----------------

class ProgramCourse(BaseModel, TenantMixin):
    """
    Curriculum link:

    - Which Courses belong to which Program.
    - 'curriculum_version' lets you change curriculum in future
      without breaking old student records.

    Example:
        Program: Grade 8
        Courses: Math, English, Physics
        curriculum_version = 1 (for AY 2025-26)

    For Quran:
        Program: Quran Hifz
        Course example 1: 'Juz 1–5'
        Course example 2: 'Juz 6–10'
        With sequence_no to control order.
    """
    __tablename__ = "edu_program_courses"

    program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    curriculum_version: Mapped[int] = mapped_column(
        db.Integer,
        nullable=False,
        default=1,
        index=True,
        comment="Version number of curriculum for this program.",
    )

    is_mandatory: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        comment="False = elective course.",
    )
    sequence_no: Mapped[Optional[int]] = mapped_column(
        db.Integer,
        comment="Order in timetable / report cards.",
    )

    # Optional validity window: if you want to date-bound a curriculum
    effective_start: Mapped[Optional[date]] = mapped_column(db.Date)
    effective_end: Mapped[Optional[date]] = mapped_column(db.Date)

    # ------------- Relationships -------------

    program: Mapped["Program"] = db.relationship(
        "Program",
        back_populates="courses",
        lazy="joined",
    )
    course: Mapped["Course"] = db.relationship(
        "Course",
        back_populates="program_links",
        lazy="joined",
    )

    __table_args__ = (
        # Same Program+Course can exist multiple times, but not with same version
        UniqueConstraint(
            "program_id", "course_id", "curriculum_version",
            name="uq_program_course_per_version",
        ),
        CheckConstraint(
            "sequence_no IS NULL OR sequence_no >= 0",
            name="ck_pc_sequence_nonneg",
        ),
        CheckConstraint(
            "(effective_start IS NULL) OR (effective_end IS NULL) "
            "OR (effective_start <= effective_end)",
            name="ck_pc_dates_ok",
        ),
        Index("ix_edu_program_courses_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProgramCourse id={self.id} program_id={self.program_id} "
            f"course_id={self.course_id} v={self.curriculum_version}>"
        )
