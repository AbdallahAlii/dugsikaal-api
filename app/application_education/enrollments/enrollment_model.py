from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    UniqueConstraint,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


# ==============================================
# Enrollment status & result enums
# ==============================================

class EnrollmentStatusEnum(str, enum.Enum):
    DRAFT = "Draft"         # created but not confirmed
    ENROLLED = "Enrolled"   # active
    SUSPENDED = "Suspended" # temporarily blocked
    LEFT = "Left"           # left mid-year
    COMPLETED = "Completed" # finished the year/program
    CANCELLED = "Cancelled" # record voided (mistake)


class PromotionJobStatusEnum(str, enum.Enum):
    DRAFT = "Draft"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    PARTIAL = "Partial"


class PromotionItemStatusEnum(str, enum.Enum):
    SUCCESS = "Success"
    SKIPPED = "Skipped"   # already enrolled / not eligible / filtered out
    FAILED = "Failed"

class EnrollmentResultEnum(str, enum.Enum):
    """
    Academic result at end of the enrollment (end-of-year verdict).
    """
    NONE = "None"               # not decided yet
    PROMOTED = "Promoted"
    RETAINED = "Retained"
    GRADUATED = "Graduated"
    FAILED = "Failed"           # optional
    TRANSFERRED_OUT = "Transferred Out"  # optional (if you track reason)


# ==============================================
# ProgramEnrollment
# ==============================================

class ProgramEnrollment(BaseModel, TenantMixin):
    """
    Official enrollment in a Program for a given academic year (and optional term).

    Example (K-12):
        - Student 123 enrolled in Program 'Grade 8'
          for AcademicYear '2025-26'.

    Example (Institute):
        - Student 456 enrolled in Program 'Diploma in IT'
          for AcademicYear '2025'.

    This is higher level than StudentGroupMembership:
      - ProgramEnrollment = admission / registration (per student per year)
      - StudentGroupMembership = which class/section they sit in inside that year.
    """
    __tablename__ = "edu_program_enrollments"

    # ---- Human-readable code ----
    enrollment_code: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
        comment="Human-readable enrollment/admission reference for this record.",
    )

    # ---- Core links ----

    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_year_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=False,
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

    # Campus where this enrollment is happening
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
        comment="Campus/branch where the student attends this program.",
    )

    # Optional convenience: student's main class/group for this enrollment
    student_group_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_student_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Main StudentGroup for this enrollment (optional shortcut).",
    )

    # ---- Status & result ----

    enrollment_status: Mapped[EnrollmentStatusEnum] = mapped_column(
        db.Enum(EnrollmentStatusEnum, name="enrollment_status_enum"),
        nullable=False,
        default=EnrollmentStatusEnum.ENROLLED,
        index=True,
    )

    result_status: Mapped[EnrollmentResultEnum] = mapped_column(
        db.Enum(EnrollmentResultEnum, name="enrollment_result_enum"),
        nullable=False,
        default=EnrollmentResultEnum.NONE,
        index=True,
        comment="End-of-year result: promoted, retained, graduated, etc.",
    )

    # ---- Dates ----

    application_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Date of application (if used).",
    )
    admission_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Date student was admitted/approved.",
    )
    enrollment_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Date student officially started this enrollment.",
    )
    completion_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Date student completed this program/year.",
    )
    cancellation_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Date enrollment was cancelled/withdrawn.",
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # ---- Relationships ----

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="program_enrollments",
        lazy="joined",
    )
    student: Mapped["Student"] = db.relationship(
        "Student",
        back_populates="program_enrollments",
        lazy="joined",
    )
    program: Mapped["Program"] = db.relationship(
        "Program",
        back_populates="enrollments",
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
        lazy="joined",
    )
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )
    student_group: Mapped[Optional["StudentGroup"]] = db.relationship(
        "StudentGroup",
        lazy="joined",
    )

    # Reverse link from CourseEnrollment
    course_enrollments: Mapped[list["CourseEnrollment"]] = db.relationship(
        "CourseEnrollment",
        back_populates="program_enrollment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # At most one enrollment per student+program+year
        UniqueConstraint(
            "student_id",
            "program_id",
            "academic_year_id",
            name="uq_enrollment_per_program_year",
        ),
        # Enrollment code unique per company
        UniqueConstraint(
            "company_id",
            "enrollment_code",
            name="uq_program_enrollment_code_per_company",
        ),

        # Date sanity
        CheckConstraint(
            "(enrollment_date IS NULL) OR (admission_date IS NULL) "
            "OR (admission_date <= enrollment_date)",
            name="ck_enrollment_admission_before_enrollment",
        ),
        CheckConstraint(
            "(completion_date IS NULL) OR (enrollment_date IS NULL) "
            "OR (enrollment_date <= completion_date)",
            name="ck_enrollment_completion_after_enrollment",
        ),

        Index("ix_edu_program_enrollments_company_id", "company_id"),
        Index(
            "ix_edu_program_enrollments_student_program_year",
            "student_id",
            "program_id",
            "academic_year_id",
        ),
        Index(
            "ix_edu_program_enrollments_status",
            "enrollment_status",
        ),
        Index(
            "ix_edu_program_enrollments_result",
            "result_status",
        ),
        Index(
            "ix_edu_program_enrollments_company_branch_year_program",
            "company_id",
            "branch_id",
            "academic_year_id",
            "program_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ProgramEnrollment id={self.id} company_id={self.company_id} "
            f"code={self.enrollment_code!r} student_id={self.student_id} "
            f"program_id={self.program_id} status={self.enrollment_status.value} "
            f"result={self.result_status.value}>"
        )


# ==============================================
# CourseEnrollment
# ==============================================

class CourseEnrollment(BaseModel, TenantMixin):
    """
    Enrollment of a Student in a specific Course.

    - Works as "Enrolled Courses" child rows under ProgramEnrollment
      when program_enrollment_id is set.
    - Can also work as standalone course enrollment when program_enrollment_id is NULL,
      but in all cases we require branch + year (+ optional term).

    Branch-scoped + Company-scoped uniqueness prevents duplicates.
    """
    __tablename__ = "edu_course_enrollments"

    # ---- Human-readable code ----
    enrollment_code: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
        comment="Human-readable reference for this course enrollment record.",
    )

    # ---- Core links ----
    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    course_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional parent: if set, this enrollment is part of a ProgramEnrollment
    program_enrollment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_program_enrollments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="If set, this course enrollment belongs to that ProgramEnrollment.",
    )

    academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Term can be optional if your school is annual-only.
    academic_term_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # You asked: enforce branch-based uniqueness and no duplicates
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    enrollment_status: Mapped[EnrollmentStatusEnum] = mapped_column(
        db.Enum(EnrollmentStatusEnum, name="course_enrollment_status_enum"),
        nullable=False,
        default=EnrollmentStatusEnum.ENROLLED,
        index=True,
    )

    enrollment_date: Mapped[Optional[date]] = mapped_column(db.Date)
    completion_date: Mapped[Optional[date]] = mapped_column(db.Date)
    cancellation_date: Mapped[Optional[date]] = mapped_column(db.Date)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # ---- Relationships ----
    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="course_enrollments",
        lazy="joined",
    )
    student: Mapped["Student"] = db.relationship(
        "Student",
        back_populates="course_enrollments",
        lazy="joined",
    )
    course: Mapped["Course"] = db.relationship(
        "Course",
        back_populates="course_enrollments",
        lazy="joined",
    )
    program_enrollment: Mapped[Optional["ProgramEnrollment"]] = db.relationship(
        "ProgramEnrollment",
        back_populates="course_enrollments",
        lazy="joined",
    )
    academic_year: Mapped["AcademicYear"] = db.relationship(
        "AcademicYear",
        lazy="joined",
    )
    academic_term: Mapped[Optional["AcademicTerm"]] = db.relationship(
        "AcademicTerm",
        lazy="joined",
    )
    branch: Mapped["Branch"] = db.relationship(
        "Branch",
        lazy="joined",
    )

    __table_args__ = (
        # Enrollment code unique per company (same pattern as ProgramEnrollment)
        UniqueConstraint(
            "company_id",
            "enrollment_code",
            name="uq_course_enrollment_code_per_company",
        ),

        # Prevent duplicates per branch + year + term (company-scoped)
        UniqueConstraint(
            "company_id",
            "branch_id",
            "student_id",
            "course_id",
            "academic_year_id",
            "academic_term_id",
            name="uq_ce_company_branch_student_course_year_term",
        ),

        # Date sanity
        CheckConstraint(
            "(completion_date IS NULL) OR (enrollment_date IS NULL) OR (enrollment_date <= completion_date)",
            name="ck_ce_completion_after_enrollment",
        ),
        CheckConstraint(
            "(cancellation_date IS NULL) OR (enrollment_date IS NULL) OR (enrollment_date <= cancellation_date)",
            name="ck_ce_cancel_after_enrollment",
        ),
        CheckConstraint(
            "(completion_date IS NULL) OR (cancellation_date IS NULL) OR (cancellation_date <= completion_date)",
            name="ck_ce_cancel_before_completion",
        ),

        # If you want to strictly require a year/branch always (already NOT NULL)
        # but also ensure standalone enrollments still have year/branch even without program_enrollment_id:
        CheckConstraint(
            "(program_enrollment_id IS NOT NULL) OR (academic_year_id IS NOT NULL AND branch_id IS NOT NULL)",
            name="ck_ce_program_or_context_required",
        ),

        # Helpful composite indexes for common queries
        Index("ix_edu_course_enrollments_company_id", "company_id"),
        Index("ix_edu_course_enrollments_company_student", "company_id", "student_id"),
        Index("ix_edu_course_enrollments_company_branch_year_term", "company_id", "branch_id", "academic_year_id", "academic_term_id"),
        Index("ix_edu_course_enrollments_company_status", "company_id", "enrollment_status"),
        Index("ix_edu_course_enrollments_program_enrollment", "company_id", "program_enrollment_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CourseEnrollment id={self.id} company_id={self.company_id} "
            f"code={self.enrollment_code!r} student_id={self.student_id} "
            f"course_id={self.course_id} status={self.enrollment_status.value}>"
        )

class PromotionJobItem(BaseModel, TenantMixin):
    """
    One student processed inside a PromotionJob.
    Stores per-student outcome for partial success/failure tracking.
    """
    __tablename__ = "edu_promotion_job_items"

    job_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_promotion_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The enrollment we promoted FROM (source)
    from_program_enrollment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_program_enrollments.id", ondelete="SET NULL"),
        index=True,
    )

    # The enrollment we created TO (target)
    to_program_enrollment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_program_enrollments.id", ondelete="SET NULL"),
        index=True,
    )

    status: Mapped["PromotionItemStatusEnum"] = mapped_column(
        db.Enum(PromotionItemStatusEnum, name="edu_promotion_item_status_enum"),
        nullable=False,
        default=PromotionItemStatusEnum.SKIPPED,
        index=True,
    )

    message: Mapped[Optional[str]] = mapped_column(db.String(255))
    error_detail: Mapped[Optional[str]] = mapped_column(db.Text)

    job: Mapped["PromotionJob"] = relationship("PromotionJob", back_populates="items", lazy="joined")

    __table_args__ = (
        UniqueConstraint("job_id", "student_id", name="uq_pjobitem_job_student"),
        Index("ix_edu_promotion_job_items_company_id", "company_id"),
        Index("ix_edu_promotion_job_items_company_job", "company_id", "job_id"),
    )






class PromotionJob(BaseModel, TenantMixin):
    """
    Frappe-like bulk 'Program Enrollment Tool' run.

    This does NOT replace ProgramEnrollment.
    It only records one batch operation:
      - from_program + from_year/term (+ branch)
      - to_program + to_year/term (+ branch)
      - who ran it
      - job status + counts
    """
    __tablename__ = "edu_promotion_jobs"

    # Filters / source
    from_program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_academic_term_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Target
    to_program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_academic_term_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Branch context (Frappe-like: admin runs per branch if desired)
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        index=True,
        comment="If set, tool run is scoped to this branch.",
    )

    status: Mapped["PromotionJobStatusEnum"] = mapped_column(
        db.Enum(PromotionJobStatusEnum, name="edu_promotion_job_status_enum"),
        nullable=False,
        default=PromotionJobStatusEnum.DRAFT,
        index=True,
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))

    total_found: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    total_success: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    total_skipped: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)

    error_message: Mapped[Optional[str]] = mapped_column(db.Text)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    # Relationships (optional, but helpful)
    items: Mapped[List["PromotionJobItem"]] = relationship(
        "PromotionJobItem",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("total_found >= 0", name="ck_pjob_found_nonneg"),
        CheckConstraint("total_success >= 0", name="ck_pjob_success_nonneg"),
        CheckConstraint("total_failed >= 0", name="ck_pjob_failed_nonneg"),
        CheckConstraint("total_skipped >= 0", name="ck_pjob_skipped_nonneg"),
        Index("ix_edu_promotion_jobs_company_id", "company_id"),
        Index("ix_edu_promotion_jobs_company_branch", "company_id", "branch_id"),
        Index("ix_edu_promotion_jobs_company_status", "company_id", "status"),
    )

# ==============================================
# ProgramProgressionRule
# ==============================================

class ProgramProgressionRule(BaseModel, TenantMixin):
    """
    Defines how students progress from one Program to another.

    Examples (K-12):
        Grade 1 -> Grade 2
        Grade 2 -> Grade 3
        ...
        Grade 11 -> Grade 12
        Grade 12 -> (no rule) => GRADUATED

    Examples (Institute):
        English Level 1 -> English Level 2
        English Level 2 -> English Level 3

    Examples (Quran):
        Quran Hifz (Beginner) -> Quran Hifz (Intermediate)
        Or you can use track_label or curriculum design (ProgramCourse)
        to express Juz ranges.

    This is a generic rule (for all students of a company):
        - NO student_id here (per-student result is on ProgramEnrollment).
        - Optional effective_from_ay_id / effective_to_ay_id control
          for which academic years this rule is valid.
        - Optional branch_id to scope the rule to one branch; NULL means
          it applies to all branches of that company.
    """
    __tablename__ = "edu_program_progression_rules"

    # ----- Core: from Program -> to Program -----

    from_program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional label for different tracks (Science / Arts / Quran stream / etc.)
    track_label: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        comment="Optional: 'Science Stream', 'Arts Stream', 'Quran Hifz', etc.",
    )

    # Optional branch context
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="If set, this rule applies only in that branch; NULL = all branches.",
    )

    # Is this rule active?
    is_active: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    # Only one default per from_program (and optional branch) is recommended.
    is_default: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Default progression if multiple rules exist for same from_program.",
    )

    # ----- Optional validity by academic year -----

    effective_from_ay_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Rule is valid starting from this AcademicYear (inclusive).",
    )
    effective_to_ay_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Rule is valid until this AcademicYear (inclusive).",
    )

    # ----- Relationships -----

    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="program_progression_rules",
        lazy="joined",
    )

    from_program: Mapped["Program"] = db.relationship(
        "Program",
        foreign_keys=[from_program_id],
        back_populates="progression_from_rules",
        lazy="joined",
    )
    to_program: Mapped["Program"] = db.relationship(
        "Program",
        foreign_keys=[to_program_id],
        back_populates="progression_to_rules",
        lazy="joined",
    )

    effective_from_ay: Mapped[Optional["AcademicYear"]] = db.relationship(
        "AcademicYear",
        foreign_keys=[effective_from_ay_id],
        lazy="joined",
    )
    effective_to_ay: Mapped[Optional["AcademicYear"]] = db.relationship(
        "AcademicYear",
        foreign_keys=[effective_to_ay_id],
        lazy="joined",
    )

    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )

    __table_args__ = (
        # Date sanity for academic year bounds (by id ordering – soft check)
        CheckConstraint(
            "(effective_from_ay_id IS NULL) OR "
            "(effective_to_ay_id IS NULL) OR "
            "(effective_from_ay_id <= effective_to_ay_id)",
            name="ck_progprog_ay_range_ok",
        ),

        # Uniqueness: one rule with this combination per company
        UniqueConstraint(
            "company_id",
            "branch_id",
            "from_program_id",
            "to_program_id",
            "track_label",
            "effective_from_ay_id",
            "effective_to_ay_id",
            name="uq_program_progression_rule",
        ),

        Index("ix_edu_progprog_company_from", "company_id", "from_program_id"),
        Index("ix_edu_progprog_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProgramProgressionRule id={self.id} company_id={self.company_id} "
            f"from_program_id={self.from_program_id} to_program_id={self.to_program_id} "
            f"branch_id={self.branch_id} default={self.is_default} active={self.is_active}>"
        )
