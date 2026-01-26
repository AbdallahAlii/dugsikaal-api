# app/application_quran_memorization/models.py

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    UniqueConstraint,
    CheckConstraint,
    Index,
    ForeignKeyConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


class HifzCategoryEnum(str, enum.Enum):
    """What type of content is this lesson about?"""
    QURAN = "QURAN"
    NOORANI_QAIDA = "NOORANI_QAIDA"
    TAJWEED = "TAJWEED"
    OTHER_BOOK = "OTHER_BOOK"


class HifzLessonTypeEnum(str, enum.Enum):
    """Why is this lesson given?"""
    NEW = "NEW"            # New memorization
    REVISION = "REVISION"  # Revision of old surahs/juz
    TEST = "TEST"          # Short test
    EXAM = "EXAM"          # Bigger exam


class HifzLessonStatusEnum(str, enum.Enum):
    """Where is the student on this lesson?"""
    ASSIGNED = "ASSIGNED"          # Teacher gave but student not yet checked
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Teacher said repeat it later
    CANCELLED = "CANCELLED"


class RecitationOutcomeEnum(str, enum.Enum):
    """Teacher decision after listening."""
    PASSED = "PASSED"   # Good, can move on
    RETRY = "RETRY"     # Not good yet, repeat same lesson
    FAILED = "FAILED"   # For tests/exams, clearly failed


# =====================================================================================
# HifzBook
# =====================================================================================

class HifzBook(BaseModel, TenantMixin):
    """
    Educational book used together with Qur'an memorization:
    - Noorani Qaida
    - Tajweed book
    - Other reading books
    """
    __tablename__ = "hifz_books"

    title: Mapped[str] = mapped_column(db.String(255), nullable=False)

    category: Mapped[HifzCategoryEnum] = mapped_column(
        db.Enum(HifzCategoryEnum, name="hifz_book_category_enum"),
        nullable=False,
        default=HifzCategoryEnum.NOORANI_QAIDA,
        index=True,
    )

    total_pages: Mapped[Optional[int]] = mapped_column(db.Integer)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    # Optional: PDF or images in object storage
    file_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        comment="Object-storage key/path for the book file (PDF/images).",
    )

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="hifz_books",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "title", name="uq_hifz_book_title_per_company"),
        Index("ix_hifz_books_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<HifzBook id={self.id} company_id={self.company_id} "
            f"title={self.title!r}>"
        )


# =====================================================================================
# HifzLesson
# =====================================================================================

class HifzLesson(BaseModel, TenantMixin):
    """
    A memorization lesson for a single student.

    Examples:
      - Qur'an: Surah Al-Mulk, ayah 1–10 (NEW)
      - Qur'an: Juz 30 pages 602–604 (REVISION)
      - Noorani: page 10, first line (NEW)
    """
    __tablename__ = "hifz_lessons"

    # Branch context (campus)
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Campus/branch where this lesson is managed.",
    )

    # Who is this for?
    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional: which halaqa / class / group (StudentGroup at assignment time)
    student_group_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_student_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Halaqa / class (StudentGroup) at the time of assignment.",
    )

    # Who gave this lesson? (system user with teacher role)
    assigned_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User (teacher) who assigned this lesson.",
    )

    # Context (year/term) if you want it
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

    # What type of content & lesson?
    category: Mapped[HifzCategoryEnum] = mapped_column(
        db.Enum(HifzCategoryEnum, name="hifz_lesson_category_enum"),
        nullable=False,
        default=HifzCategoryEnum.QURAN,
        index=True,
    )

    lesson_type: Mapped[HifzLessonTypeEnum] = mapped_column(
        db.Enum(HifzLessonTypeEnum, name="hifz_lesson_type_enum"),
        nullable=False,
        default=HifzLessonTypeEnum.NEW,
        index=True,
    )

    status: Mapped[HifzLessonStatusEnum] = mapped_column(
        db.Enum(HifzLessonStatusEnum, name="hifz_lesson_status_enum"),
        nullable=False,
        default=HifzLessonStatusEnum.ASSIGNED,
        index=True,
    )

    # Is this the current "main" lesson for that student?
    is_current: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="If true, this is the current main lesson for the student.",
    )

    title: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        comment="Optional label, e.g., 'Al-Mulk 1–10 (NEW)'.",
    )
    notes_for_student: Mapped[Optional[str]] = mapped_column(db.Text)

    # ---------- QURAN FIELDS (used when category = QURAN) ----------

    # Link to Quran Mushaf/edition (matches QuranMushaf.code)
    quran_mushaf_code: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        index=True,
        comment="Qur'an mushaf/edition code, e.g. 'madani_hafs_v1'.",
    )

    # Either use surah/ayah range:
    quran_surah_from: Mapped[Optional[int]] = mapped_column(db.Integer)
    quran_ayah_from: Mapped[Optional[int]] = mapped_column(db.Integer)
    quran_surah_to: Mapped[Optional[int]] = mapped_column(db.Integer)
    quran_ayah_to: Mapped[Optional[int]] = mapped_column(db.Integer)

    # Or use page range (for Mushaf page-based lessons):
    quran_page_from: Mapped[Optional[int]] = mapped_column(db.Integer)
    quran_page_to: Mapped[Optional[int]] = mapped_column(db.Integer)

    # ---------- BOOK FIELDS (used when category != QURAN) ----------

    book_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("hifz_books.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    book_page_from: Mapped[Optional[int]] = mapped_column(db.Integer)
    book_page_to: Mapped[Optional[int]] = mapped_column(db.Integer)

    # Free text to describe which words / line / exercise:
    book_unit_label: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        comment="e.g. 'first line words 1–4', 'exercise 3 on page 5'.",
    )

    # ---------- Dates ----------

    assigned_at: Mapped[datetime] = mapped_column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime)
    closed_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime)

    # ------------ Relationships ------------

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="hifz_lessons",
        lazy="joined",
    )
    branch: Mapped["Branch"] = relationship(
        "Branch",
        lazy="joined",
    )
    student: Mapped["Student"] = relationship(
        "Student",
        lazy="joined",
    )
    student_group: Mapped[Optional["StudentGroup"]] = relationship(
        "StudentGroup",
        lazy="joined",
    )
    assigned_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        lazy="joined",
        foreign_keys=[assigned_by_user_id],
    )
    academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear",
        lazy="joined",
    )
    academic_term: Mapped[Optional["AcademicTerm"]] = relationship(
        "AcademicTerm",
        lazy="joined",
    )
    book: Mapped[Optional["HifzBook"]] = relationship(
        "HifzBook",
        lazy="joined",
    )

    recitations: Mapped[List["HifzRecitation"]] = relationship(
        "HifzRecitation",
        back_populates="lesson",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Page ranges sanity
        CheckConstraint(
            "(quran_page_from IS NULL) OR (quran_page_to IS NULL) "
            "OR (quran_page_from <= quran_page_to)",
            name="ck_hifz_lesson_quran_pages_ok",
        ),
        CheckConstraint(
            "(book_page_from IS NULL) OR (book_page_to IS NULL) "
            "OR (book_page_from <= book_page_to)",
            name="ck_hifz_lesson_book_pages_ok",
        ),

        # Same-company & same-branch guards (optional but good safety)
        ForeignKeyConstraint(
            ["company_id", "branch_id"],
            ["branches.company_id", "branches.id"],
            ondelete="CASCADE",
            name="fk_hifz_lesson_branch_company_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "branch_id", "student_id"],
            ["students.company_id", "students.branch_id", "students.id"],
            ondelete="CASCADE",
            name="fk_hifz_lesson_student_company_branch_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "student_group_id"],
            ["edu_student_groups.company_id", "edu_student_groups.id"],
            ondelete="SET NULL",
            name="fk_hifz_lesson_group_company_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "academic_year_id"],
            ["edu_academic_years.company_id", "edu_academic_years.id"],
            ondelete="SET NULL",
            name="fk_hifz_lesson_ay_company_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "academic_term_id"],
            ["edu_academic_terms.company_id", "edu_academic_terms.id"],
            ondelete="SET NULL",
            name="fk_hifz_lesson_term_company_guard",
        ),

        Index("ix_hifz_lessons_company_id", "company_id"),
        Index("ix_hifz_lessons_company_branch_student", "company_id", "branch_id", "student_id"),
        Index("ix_hifz_lessons_status", "status"),
        Index("ix_hifz_lessons_is_current", "is_current"),
    )

    def __repr__(self) -> str:
        return (
            f"<HifzLesson id={self.id} company_id={self.company_id} "
            f"branch_id={self.branch_id} student_id={self.student_id} "
            f"category={self.category.value} type={self.lesson_type.value} "
            f"status={self.status.value}>"
        )


# =====================================================================================
# HifzRecitation
# =====================================================================================

class HifzRecitation(BaseModel, TenantMixin):
    """
    One recitation session for a lesson:
    - teacher listens to the student
    - decides PASS / RETRY / FAILED
    """
    __tablename__ = "hifz_recitations"

    # Branch context (copy from lesson/student branch)
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Campus/branch where this recitation happened.",
    )

    lesson_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("hifz_lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    heard_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User (teacher) who listened to this recitation.",
    )

    # When did it happen?
    recited_at: Mapped[datetime] = mapped_column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # Result / decision
    outcome: Mapped[RecitationOutcomeEnum] = mapped_column(
        db.Enum(RecitationOutcomeEnum, name="hifz_recitation_outcome_enum"),
        nullable=False,
        default=RecitationOutcomeEnum.RETRY,
        index=True,
    )

    score: Mapped[Optional[float]] = mapped_column(
        db.Numeric(5, 2),
        comment="Optional numeric score (0-10, 0-100, etc.).",
    )

    comment: Mapped[Optional[str]] = mapped_column(
        db.Text,
        comment="Teacher notes (e.g. tajweed mistakes, weak memorization, portion covered).",
    )

    # Optional: if you record student recitation audio
    audio_url: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        comment="URL or storage key for recitation audio (if recorded).",
    )

    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="hifz_recitations",
        lazy="joined",
    )
    branch: Mapped["Branch"] = relationship(
        "Branch",
        lazy="joined",
    )
    lesson: Mapped["HifzLesson"] = relationship(
        "HifzLesson",
        back_populates="recitations",
        lazy="joined",
    )
    student: Mapped["Student"] = relationship(
        "Student",
        lazy="joined",
    )
    heard_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        lazy="joined",
        foreign_keys=[heard_by_user_id],
    )

    __table_args__ = (
        # Same-company & same-branch guards
        ForeignKeyConstraint(
            ["company_id", "branch_id"],
            ["branches.company_id", "branches.id"],
            ondelete="CASCADE",
            name="fk_hifz_recitation_branch_company_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "branch_id", "student_id"],
            ["students.company_id", "students.branch_id", "students.id"],
            ondelete="CASCADE",
            name="fk_hifz_recitation_student_company_branch_guard",
        ),
        ForeignKeyConstraint(
            ["company_id", "lesson_id"],
            ["hifz_lessons.company_id", "hifz_lessons.id"],
            ondelete="CASCADE",
            name="fk_hifz_recitation_lesson_company_guard",
        ),

        Index("ix_hifz_recitations_company_id", "company_id"),
        Index("ix_hifz_recitations_company_branch_student", "company_id", "branch_id", "student_id"),
        Index("ix_hifz_recitations_outcome", "outcome"),
    )

    def __repr__(self) -> str:
        return (
            f"<HifzRecitation id={self.id} company_id={self.company_id} "
            f"branch_id={self.branch_id} lesson_id={self.lesson_id} "
            f"student_id={self.student_id} outcome={self.outcome.value}>"
        )
