from __future__ import annotations

import enum
from datetime import date, time, datetime
from typing import Optional, List

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


# ----------------------------------------------------------------------
# Enums (same pattern as your old file)
# ----------------------------------------------------------------------

class AssessmentEventStatusEnum(str, enum.Enum):
    """
    Lifecycle of a scheduled assessment event.
    """
    DRAFT = "Draft"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class AssessmentAttendanceStatusEnum(str, enum.Enum):
    """
    Attendance state for a student on a specific assessment event.
    """
    PRESENT = "Present"
    ABSENT = "Absent"
    EXCUSED = "Excused"
    NOT_EVALUATED = "Not Evaluated"


class ResultHoldTypeEnum(str, enum.Enum):
    """
    Blocks student result visibility in portal.
    """
    FEES = "Fees"
    DISCIPLINE = "Discipline"
    OTHER = "Other"


class GradeRecalcJobStatusEnum(str, enum.Enum):
    """
    Status for background recalculation job.
    """
    QUEUED = "Queued"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    FAILED = "Failed"


# ----------------------------------------------------------------------
# Grading scale (company-level)
# ----------------------------------------------------------------------

class GradingScale(BaseModel, TenantMixin):
    """
    Per-company grading scheme.

    Example:
      - 'K12 0–100 Scale'
      - 'Institute GPA 4.0 Scale'
    """
    __tablename__ = "edu_grading_scales"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    is_default: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Default grading scale for company when no other scale is specified.",
    )

    company: Mapped["Company"] = relationship("Company", back_populates="grading_scales", lazy="joined")

    breakpoints: Mapped[List["GradingScaleBreakpoint"]] = relationship(
        "GradingScaleBreakpoint",
        back_populates="grading_scale",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_grading_scale_name_per_company"),
        Index("ix_edu_grading_scales_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<GradingScale id={self.id} company_id={self.company_id} name={self.name!r}>"


class GradingScaleBreakpoint(BaseModel, TenantMixin):
    """
    One grade band inside a grading scale.

    Example:
      - A+: 90–100, 4.0
      - A : 80–89 , 3.7
    """
    __tablename__ = "edu_grading_scale_breakpoints"

    grading_scale_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_grading_scales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    grade_code: Mapped[str] = mapped_column(
        db.String(10),
        nullable=False,
        comment="Label like 'A+', 'A', 'B', etc.",
    )

    min_percentage: Mapped[float] = mapped_column(
        db.Float,
        nullable=False,
        comment="Inclusive lower bound, e.g. 80.0",
    )
    max_percentage: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="Optional upper bound; NULL means up to 100.",
    )

    grade_point: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="Optional GPA / grade points, e.g. 4.0.",
    )

    description: Mapped[Optional[str]] = mapped_column(db.String(255))
    sequence_no: Mapped[Optional[int]] = mapped_column(db.Integer, comment="Sort order in UI.")

    grading_scale: Mapped["GradingScale"] = relationship("GradingScale", back_populates="breakpoints", lazy="joined")

    __table_args__ = (
        UniqueConstraint("grading_scale_id", "grade_code", name="uq_grade_code_per_scale"),
        CheckConstraint(
            "min_percentage >= 0 AND (max_percentage IS NULL OR max_percentage <= 100)",
            name="ck_grade_bp_percentage_range",
        ),
        CheckConstraint(
            "(max_percentage IS NULL) OR (min_percentage <= max_percentage)",
            name="ck_grade_bp_min_le_max",
        ),
        Index("ix_edu_grading_scale_breakpoints_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<GradingScaleBreakpoint id={self.id} company_id={self.company_id} "
            f"scale_id={self.grading_scale_id} grade={self.grade_code!r}>"
        )


# ----------------------------------------------------------------------
# Assessment template: Scheme + Components + Rules
# ----------------------------------------------------------------------

class AssessmentScheme(BaseModel, TenantMixin):
    """
    ERP standard: scheme is for a concrete Program + AcademicYear + AcademicTerm.

    IMPORTANT:
      - For yearly-only schools, create a term record like code='ANNUAL'
        and always store academic_term_id (NOT NULL).
    """
    __tablename__ = "edu_assessment_schemes"

    name: Mapped[str] = mapped_column(
        db.String(120),
        nullable=False,
        comment="Friendly name e.g. 'Grade 1 - Term 1 - 2025 Scheme'.",
    )

    program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    grading_scale_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_grading_scales.id", ondelete="SET NULL"),
        index=True,
        comment="Default grading scale for this scheme; if NULL use company default.",
    )

    is_default: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="If True, this scheme is the default for this program/year/term.",
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        comment="User who created this scheme template.",
    )

    company: Mapped["Company"] = relationship("Company", lazy="joined")
    program: Mapped["Program"] = relationship("Program", lazy="joined")
    academic_year: Mapped["AcademicYear"] = relationship("AcademicYear", lazy="joined")
    academic_term: Mapped["AcademicTerm"] = relationship("AcademicTerm", lazy="joined")
    grading_scale: Mapped[Optional["GradingScale"]] = relationship("GradingScale", lazy="joined")

    components: Mapped[List["AssessmentComponent"]] = relationship(
        "AssessmentComponent",
        back_populates="scheme",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    rules: Mapped[List["AssessmentComponentRule"]] = relationship(
        "AssessmentComponentRule",
        back_populates="scheme",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "program_id", "academic_year_id", "academic_term_id", "name",
                         name="uq_scheme_program_year_term_name"),
        Index("ix_edu_assessment_schemes_company_id", "company_id"),
        Index("ix_edu_assessment_schemes_company_program_year_term", "company_id", "program_id", "academic_year_id", "academic_term_id"),
    )

    def __repr__(self) -> str:
        return f"<AssessmentScheme id={self.id} company_id={self.company_id} program_id={self.program_id} name={self.name!r}>"


class AssessmentComponent(BaseModel, TenantMixin):
    """
    Components inside a scheme: M1 / MID / FIN, etc.

    Supports tree grouping via parent_id + is_group.
    """
    __tablename__ = "edu_assessment_components"

    scheme_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_schemes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        comment="Short code e.g. 'M1', 'MID', 'FIN'. Must be unique per scheme.",
    )
    sequence_no: Mapped[Optional[int]] = mapped_column(db.Integer, comment="Sort order in UI.")

    parent_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_components.id", ondelete="SET NULL"),
        index=True,
    )
    is_group: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        comment="True if grouping node only (not a real exam).",
    )

    scheme: Mapped["AssessmentScheme"] = relationship("AssessmentScheme", back_populates="components", lazy="joined")
    parent: Mapped[Optional["AssessmentComponent"]] = relationship(
        "AssessmentComponent",
        remote_side="AssessmentComponent.id",
        back_populates="children",
        lazy="joined",
    )
    children: Mapped[List["AssessmentComponent"]] = relationship(
        "AssessmentComponent",
        back_populates="parent",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("scheme_id", "name", name="uq_component_name_per_scheme"),
        UniqueConstraint("scheme_id", "code", name="uq_component_code_per_scheme"),
        Index("ix_edu_assessment_components_company_id", "company_id"),
        Index("ix_edu_assessment_components_company_scheme", "company_id", "scheme_id"),
    )

    def __repr__(self) -> str:
        return f"<AssessmentComponent id={self.id} company_id={self.company_id} scheme_id={self.scheme_id} code={self.code!r}>"


class AssessmentComponentRule(BaseModel, TenantMixin):
    """
    Per course per component rules.

    Teachers enter points out of max_points.
    System converts to percent and applies weight_percent.
    """
    __tablename__ = "edu_assessment_component_rules"

    scheme_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_schemes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    component_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_components.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    max_points: Mapped[float] = mapped_column(
        db.Float,
        nullable=False,
        comment="Max raw points for this course in this component.",
    )
    weight_percent: Mapped[float] = mapped_column(
        db.Float,
        nullable=False,
        comment="Contribution (%) of this component to final course grade.",
    )

    passing_percent: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="Optional pass threshold for this component (0..100).",
    )

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Disable rule without deleting it.",
    )

    scheme: Mapped["AssessmentScheme"] = relationship("AssessmentScheme", back_populates="rules", lazy="joined")
    component: Mapped["AssessmentComponent"] = relationship("AssessmentComponent", lazy="joined")
    course: Mapped["Course"] = relationship("Course", lazy="joined")

    __table_args__ = (
        UniqueConstraint("scheme_id", "component_id", "course_id", name="uq_rule_scheme_component_course"),
        CheckConstraint("max_points > 0", name="ck_rule_max_points_positive"),
        CheckConstraint("(weight_percent > 0) AND (weight_percent <= 100)", name="ck_rule_weight_range"),
        CheckConstraint("(passing_percent IS NULL) OR (passing_percent >= 0 AND passing_percent <= 100)",
                        name="ck_rule_pass_percent_range"),
        Index("ix_edu_assessment_component_rules_company_id", "company_id"),
        Index("ix_edu_assessment_component_rules_company_scheme_course", "company_id", "scheme_id", "course_id"),
    )
    # SERVICE-LAYER VALIDATION REQUIRED:
    # For each (scheme_id, course_id) sum(weight_percent of enabled rules) must equal 100.


# ----------------------------------------------------------------------
# AssessmentEvent + AssessmentMark (actual scheduling + teacher entry)
# ----------------------------------------------------------------------

class AssessmentEvent(BaseModel, TenantMixin):
    """
    Real scheduled assessment for one StudentGroup + Course + Component.

    Stores snapshots:
      - max_points and weight_percent copied from the rule at creation time.
    """
    __tablename__ = "edu_assessment_events"

    scheme_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_schemes.id", ondelete="SET NULL"),
        index=True,
        comment="Scheme used when creating this event (optional but recommended).",
    )
    component_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_components.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    program_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_group_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_student_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_year_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_term_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_academic_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="NOT NULL ERP standard. Use ANNUAL term for yearly-only schools.",
    )

    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        index=True,
    )

    name: Mapped[Optional[str]] = mapped_column(db.String(255))
    schedule_date: Mapped[Optional[date]] = mapped_column(db.Date)
    from_time: Mapped[Optional[time]] = mapped_column(db.Time)
    to_time: Mapped[Optional[time]] = mapped_column(db.Time)

    max_points: Mapped[float] = mapped_column(db.Float, nullable=False, comment="Snapshot from rule.")
    weight_percent: Mapped[float] = mapped_column(db.Float, nullable=False, comment="Snapshot from rule.")

    grading_scale_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_grading_scales.id", ondelete="SET NULL"),
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    status: Mapped[AssessmentEventStatusEnum] = mapped_column(
        db.Enum(AssessmentEventStatusEnum, name="edu_assessment_event_status_enum"),
        nullable=False,
        default=AssessmentEventStatusEnum.DRAFT,
        index=True,
    )

    is_entry_open: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    is_result_published: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    allow_student_view: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    attempt_no: Mapped[int] = mapped_column(
        db.Integer,
        nullable=False,
        default=1,
        comment="Retakes support. 1 = first attempt.",
    )

    company: Mapped["Company"] = relationship("Company", lazy="joined")
    scheme: Mapped[Optional["AssessmentScheme"]] = relationship("AssessmentScheme", lazy="joined")
    component: Mapped["AssessmentComponent"] = relationship("AssessmentComponent", lazy="joined")
    program: Mapped["Program"] = relationship("Program", lazy="joined")
    student_group: Mapped["StudentGroup"] = relationship("StudentGroup", lazy="joined")
    course: Mapped["Course"] = relationship("Course", lazy="joined")
    branch: Mapped[Optional["Branch"]] = relationship("Branch", lazy="joined")
    grading_scale: Mapped[Optional["GradingScale"]] = relationship("GradingScale", lazy="joined")

    marks: Mapped[List["AssessmentMark"]] = relationship(
        "AssessmentMark",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="ck_event_attempt_min_1"),
        CheckConstraint("max_points > 0", name="ck_event_max_points_positive"),
        CheckConstraint("weight_percent > 0 AND weight_percent <= 100", name="ck_event_weight_range"),
        UniqueConstraint(
            "company_id",
            "student_group_id",
            "course_id",
            "component_id",
            "academic_year_id",
            "academic_term_id",
            "attempt_no",
            name="uq_event_group_course_component_year_term_attempt",
        ),
        Index("ix_edu_assessment_events_company_id", "company_id"),
        Index("ix_edu_assessment_events_company_branch", "company_id", "branch_id"),
        Index("ix_edu_assessment_events_company_program", "company_id", "program_id"),
        Index("ix_edu_assessment_events_company_year_term", "company_id", "academic_year_id", "academic_term_id"),
    )

    def __repr__(self) -> str:
        return f"<AssessmentEvent id={self.id} company_id={self.company_id} course_id={self.course_id} component_id={self.component_id}>"


class AssessmentMark(BaseModel, TenantMixin):
    """
    Teacher entry for ONE student in ONE AssessmentEvent.

    Stores student obtained marks:
      - score_points (raw out of event.max_points)
      - component_percent (optional stored)
      - weighted_percent (optional stored)
    """
    __tablename__ = "edu_assessment_marks"

    event_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        index=True,
        comment="Copied from event for reporting.",
    )

    attendance_status: Mapped[AssessmentAttendanceStatusEnum] = mapped_column(
        db.Enum(AssessmentAttendanceStatusEnum, name="edu_assessment_attendance_enum"),
        nullable=False,
        default=AssessmentAttendanceStatusEnum.PRESENT,
        index=True,
    )

    score_points: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="Raw points obtained (0..event.max_points). NULL if not entered yet.",
    )

    entered_by_employee_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="SET NULL"),
        index=True,
    )
    last_updated_by_employee_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="SET NULL"),
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    component_percent: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="(score_points / event.max_points) * 100",
    )
    weighted_percent: Mapped[Optional[float]] = mapped_column(
        db.Float,
        comment="component_percent * (event.weight_percent / 100)",
    )

    event: Mapped["AssessmentEvent"] = relationship("AssessmentEvent", back_populates="marks", lazy="joined")
    student: Mapped["Student"] = relationship("Student", lazy="joined")
    branch: Mapped[Optional["Branch"]] = relationship("Branch", lazy="joined")

    entered_by_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[entered_by_employee_id], lazy="joined"
    )
    last_updated_by_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", foreign_keys=[last_updated_by_employee_id], lazy="joined"
    )

    items: Mapped[List["AssessmentMarkItem"]] = relationship(
        "AssessmentMarkItem",
        back_populates="mark",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("event_id", "student_id", name="uq_mark_event_student"),
        CheckConstraint("(score_points IS NULL) OR (score_points >= 0)", name="ck_mark_score_nonneg"),
        CheckConstraint("(component_percent IS NULL) OR (component_percent >= 0 AND component_percent <= 100)",
                        name="ck_mark_component_percent_range"),
        CheckConstraint("(weighted_percent IS NULL) OR (weighted_percent >= 0 AND weighted_percent <= 100)",
                        name="ck_mark_weighted_percent_range"),
        Index("ix_edu_assessment_marks_company_id", "company_id"),
        Index("ix_edu_assessment_marks_company_branch", "company_id", "branch_id"),
        Index("ix_edu_assessment_marks_company_student", "company_id", "student_id"),
    )

    def __repr__(self) -> str:
        return f"<AssessmentMark id={self.id} company_id={self.company_id} event_id={self.event_id} student_id={self.student_id}>"


# ----------------------------------------------------------------------
# Optional: detailed criteria breakdown (Written / Oral / Practical...)
# ----------------------------------------------------------------------

class AssessmentCriterion(BaseModel, TenantMixin):
    """
    Company-level criterion dimension used only if you want breakdown lines.
    """
    __tablename__ = "edu_assessment_criteria"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    company: Mapped["Company"] = relationship("Company", back_populates="assessment_criteria", lazy="joined")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_criterion_name_per_company"),
        Index("ix_edu_assessment_criteria_company_id", "company_id"),
    )


class AssessmentMarkItem(BaseModel, TenantMixin):
    """
    Criterion-level marks for a given AssessmentMark.
    """
    __tablename__ = "edu_assessment_mark_items"

    mark_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_marks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_assessment_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    max_points: Mapped[Optional[float]] = mapped_column(db.Float)
    score_points: Mapped[Optional[float]] = mapped_column(db.Float)

    mark: Mapped["AssessmentMark"] = relationship("AssessmentMark", back_populates="items", lazy="joined")
    criterion: Mapped["AssessmentCriterion"] = relationship("AssessmentCriterion", lazy="joined")

    __table_args__ = (
        UniqueConstraint("mark_id", "criterion_id", name="uq_markitem_mark_criterion"),
        CheckConstraint("(score_points IS NULL) OR (score_points >= 0)", name="ck_markitem_score_nonneg"),
        Index("ix_edu_assessment_mark_items_company_id", "company_id"),
    )


# ----------------------------------------------------------------------
# Aggregation tables
# ----------------------------------------------------------------------

class StudentCourseGrade(BaseModel, TenantMixin):
    """
    Final weighted grade per student per course per year/term.
    """
    __tablename__ = "edu_student_course_grades"

    student_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("students.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    course_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_courses.id", ondelete="CASCADE"),
                                          nullable=False, index=True)

    program_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    academic_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    academic_term_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_academic_terms.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)

    branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="SET NULL"),
                                                    index=True)

    final_percent: Mapped[Optional[float]] = mapped_column(db.Float, comment="Final weighted % (0..100).")
    final_grade_code: Mapped[Optional[str]] = mapped_column(db.String(10))
    final_grade_point: Mapped[Optional[float]] = mapped_column(db.Float)
    is_passed: Mapped[Optional[bool]] = mapped_column(db.Boolean)

    __table_args__ = (
        UniqueConstraint("company_id", "student_id", "course_id", "academic_year_id", "academic_term_id",
                         name="uq_scg_student_course_year_term"),
        CheckConstraint("(final_percent IS NULL) OR (final_percent >= 0 AND final_percent <= 100)",
                        name="ck_scg_final_percent_range"),
        Index("ix_edu_student_course_grades_company_id", "company_id"),
        Index("ix_edu_student_course_grades_company_branch", "company_id", "branch_id"),
    )


class StudentAnnualResult(BaseModel, TenantMixin):
    """
    Aggregated annual result per student per academic year.
    """
    __tablename__ = "edu_student_annual_results"

    student_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("students.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    program_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    academic_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="SET NULL"),
                                                    index=True)

    average_percent: Mapped[Optional[float]] = mapped_column(db.Float, comment="Average across subjects (0..100).")
    position_in_section: Mapped[Optional[int]] = mapped_column(db.Integer)
    position_overall: Mapped[Optional[int]] = mapped_column(db.Integer)
    is_passed: Mapped[Optional[bool]] = mapped_column(db.Boolean)

    __table_args__ = (
        UniqueConstraint("company_id", "student_id", "academic_year_id", name="uq_sar_student_year"),
        Index("ix_edu_student_annual_results_company_id", "company_id"),
        Index("ix_edu_student_annual_results_company_branch", "company_id", "branch_id"),
    )


# ----------------------------------------------------------------------
# Holds + Jobs
# ----------------------------------------------------------------------

class StudentResultHold(BaseModel, TenantMixin):
    """
    Per-student per-year hold on viewing results.
    """
    __tablename__ = "edu_student_result_holds"

    student_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("students.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    academic_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)

    hold_type: Mapped[ResultHoldTypeEnum] = mapped_column(
        db.Enum(ResultHoldTypeEnum, name="edu_result_hold_type_enum"),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    note: Mapped[Optional[str]] = mapped_column(db.Text)

    __table_args__ = (
        UniqueConstraint("company_id", "student_id", "academic_year_id", "hold_type", name="uq_srh_student_year_type"),
        Index("ix_edu_student_result_holds_company_id", "company_id"),
    )


class GradeRecalcJob(BaseModel, TenantMixin):
    """
    Tracks recalculation jobs.
    """
    __tablename__ = "edu_grade_recalc_jobs"

    academic_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("edu_academic_years.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    program_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="SET NULL"),
                                                     index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="SET NULL"),
                                                    index=True)

    triggered_by_employee_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[GradeRecalcJobStatusEnum] = mapped_column(
        db.Enum(GradeRecalcJobStatusEnum, name="edu_grade_recalc_status_enum"),
        nullable=False,
        default=GradeRecalcJobStatusEnum.QUEUED,
        index=True,
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(db.Text)

    __table_args__ = (
        Index("ix_edu_grade_recalc_jobs_company_id", "company_id"),
        Index("ix_edu_grade_recalc_jobs_company_branch", "company_id", "branch_id"),
    )
