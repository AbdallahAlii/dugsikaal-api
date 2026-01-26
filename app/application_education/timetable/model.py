from __future__ import annotations

import enum
from datetime import date, time, datetime
from typing import Optional, List

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from config.database import db
from app.common.models.base import BaseModel, TenantMixin
from app.application_stock.stock_models import DocStatusEnum


# ============================================================
# ENUMS
# ============================================================

class WeekdayEnum(str, enum.Enum):
    SUN = "SUN"
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"


class StudentAttendanceSourceEnum(str, enum.Enum):
    """
    How this attendance sheet was taken.
    """
    COURSE_SCHEDULE = "Course Schedule"   # normal subject/period-based attendance
    STUDENT_GROUP = "Student Group"       # one daily roll-call per class (no specific subject)
    QURAN_SESSION = "Quran Session"       # Quran block/session attendance
    OTHER = "Other"


class StudentAttendanceStatusEnum(str, enum.Enum):
    """
    Student attendance status.

    NOTE: DB enum name is different from HR AttendanceStatusEnum to avoid conflicts.
    """
    PRESENT = "Present"
    ABSENT = "Absent"
    LATE = "Late"
    EXCUSED = "Excused"
    HALF_DAY = "Half Day"


# ============================================================
# SchoolSession
# ============================================================

class SchoolSession(BaseModel, TenantMixin):
    """
    Session within the day:

    Examples:
      - 'Morning'
      - 'Afternoon'
      - 'Evening'
      - For Quran you can define 'Quran Morning', 'Quran Afternoon', etc.
    """
    __tablename__ = "school_sessions"

    name: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        comment="Name: 'Morning', 'Afternoon', 'Evening', 'Quran Morning', etc.",
    )

    start_time: Mapped[Optional[time]] = mapped_column(db.Time)
    end_time: Mapped[Optional[time]] = mapped_column(db.Time)

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    # Who created this session (user/ref)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    time_slots: Mapped[List["TimeSlot"]] = db.relationship(
        "TimeSlot",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "name",
            name="uq_session_name_per_company",
        ),
        Index("ix_sessions_company_id", "company_id"),
    )

    def __repr__(self):
        return f"<SchoolSession id={self.id} company_id={self.company_id} name={self.name!r}>"


# ============================================================
# TimeSlot (periods)
# ============================================================

class TimeSlot(BaseModel, TenantMixin):
    """
    One period within a session, e.g.:

      - Morning, Period 1: 06:00–07:00 (Quran)
      - Morning, Period 2: 07:00–07:45
      - Afternoon, Period 3: 14:00–14:45

    Works for:
      - K-12
      - Institutes
      - Quran (short or long blocks).
    """
    __tablename__ = "time_slots"

    session_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("school_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    period_number: Mapped[int] = mapped_column(
        db.Integer,
        nullable=False,
        comment="1, 2, 3... order of period within the session.",
    )

    start_time: Mapped[time] = mapped_column(db.Time, nullable=False)
    end_time: Mapped[time] = mapped_column(db.Time, nullable=False)

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    session: Mapped["SchoolSession"] = db.relationship(
        "SchoolSession",
        back_populates="time_slots",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    schedule_slots: Mapped[List["CourseScheduleSlot"]] = db.relationship(
        "CourseScheduleSlot",
        back_populates="time_slot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "session_id", "period_number",
            name="uq_timeslot_per_session_period",
        ),
        CheckConstraint(
            "start_time < end_time",
            name="ck_timeslot_time_range",
        ),
        Index("ix_time_slots_company_id", "company_id"),
    )

    def __repr__(self):
        return (
            f"<TimeSlot id={self.id} company_id={self.company_id} "
            f"session_id={self.session_id} period={self.period_number}>"
        )


# ============================================================
# CourseAssignment
# ============================================================

class CourseAssignment(BaseModel, TenantMixin):
    """
    Assigns one teacher (employee) to teach a Course for a StudentGroup
    in a given academic year/term.

    Think:
      - K-12:  'Teacher A' teaches 'Grade 1 A' -> 'Arabic' (AY 2025-26)
      - Institute: 'Teacher B' teaches 'English Level 1' for Batch 2025
      - Quran: 'Sheikh C' teaches 'Quran Hifz (Juz 1–5)' to group 'Hifz-1'

    This does NOT contain weekday / period; it is the parent.
    The weekly timetable cells are stored in CourseScheduleSlot.
    """
    __tablename__ = "course_assignments"

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

    teacher_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Teacher = Employee record.",
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

    # Which branch/campus owns this assignment
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    expected_periods_per_week: Mapped[Optional[int]] = mapped_column(
        db.Integer,
        comment="For workload planning, e.g. 5 periods/week.",
    )

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    valid_from: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Optional: teacher starts mid-year.",
    )
    valid_to: Mapped[Optional[date]] = mapped_column(
        db.Date,
        comment="Optional: teacher stops mid-year.",
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    student_group: Mapped["StudentGroup"] = db.relationship(
        "StudentGroup",
        lazy="joined",
    )
    course: Mapped["Course"] = db.relationship(
        "Course",
        lazy="joined",
    )
    teacher: Mapped["Employee"] = db.relationship(
        "Employee",
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
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    schedule_slots: Mapped[List["CourseScheduleSlot"]] = db.relationship(
        "CourseScheduleSlot",
        back_populates="course_assignment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Same teacher can teach same group+course in different years/terms.
        UniqueConstraint(
            "company_id",
            "student_group_id",
            "course_id",
            "academic_year_id",
            "academic_term_id",
            "teacher_id",
            name="uq_ca_group_course_year_term_teacher",
        ),
        CheckConstraint(
            "(expected_periods_per_week IS NULL) OR (expected_periods_per_week >= 0)",
            name="ck_ca_expected_periods_nonneg",
        ),
        CheckConstraint(
            "(valid_from IS NULL) OR (valid_to IS NULL) OR (valid_from <= valid_to)",
            name="ck_ca_valid_dates_ok",
        ),

        Index("ix_course_assignments_company_id", "company_id"),
        Index("ix_course_assignments_teacher", "teacher_id"),
        Index("ix_course_assignments_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self):
        return (
            f"<CourseAssignment id={self.id} company_id={self.company_id} "
            f"group_id={self.student_group_id} course_id={self.course_id} teacher_id={self.teacher_id}>"
        )


# ============================================================
# Classroom
# ============================================================

class Classroom(BaseModel, TenantMixin):
    """
    Physical or virtual room.

    Examples:
      - 'Room 101'
      - 'Lab A'
      - 'Online Room 1'
    """
    __tablename__ = "classrooms"

    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Branch/campus where this room exists.",
    )

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(db.String(255))
    capacity: Mapped[Optional[int]] = mapped_column(db.Integer)

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    branch: Mapped["Branch"] = db.relationship(
        "Branch",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    schedule_slots: Mapped[List["CourseScheduleSlot"]] = db.relationship(
        "CourseScheduleSlot",
        back_populates="classroom",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "branch_id", "name",
            name="uq_classroom_name_per_branch",
        ),
        CheckConstraint(
            "capacity IS NULL OR capacity >= 0",
            name="ck_classroom_capacity_nonneg",
        ),
        Index("ix_classrooms_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self):
        return (
            f"<Classroom id={self.id} company_id={self.company_id} "
            f"branch_id={self.branch_id} name={self.name!r}>"
        )


# ============================================================
# CourseScheduleSlot  (the actual timetable cells)
# ============================================================

class CourseScheduleSlot(BaseModel, TenantMixin):
    """
    One cell in the weekly timetable grid.

    Example:
      - Sunday, TimeSlot #1, Grade 5 A, Mathematics, Teacher Ali, Room 101.

    This is recurring every week (unless overridden by holidays or exceptions).

    Supports all programs:
      - K-12 (many subjects)
      - Institute (few subjects, different blocks)
      - Quran (long morning/afternoon blocks or period-based).
    """
    __tablename__ = "course_schedule_slots"

    course_assignment_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("course_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalized for fast queries
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
    teacher_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
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

    weekday: Mapped[WeekdayEnum] = mapped_column(
        db.Enum(WeekdayEnum, name="schedule_weekday_enum"),
        nullable=False,
        index=True,
    )

    time_slot_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("time_slots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    classroom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("classrooms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Which branch/campus this slot belongs to
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    schedule_color: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        comment="UI color tag, e.g. 'blue', '#00AEEF'.",
    )

    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    course_assignment: Mapped["CourseAssignment"] = db.relationship(
        "CourseAssignment",
        back_populates="schedule_slots",
        lazy="joined",
    )

    student_group: Mapped["StudentGroup"] = db.relationship("StudentGroup", lazy="joined")
    course: Mapped["Course"] = db.relationship("Course", lazy="joined")
    teacher: Mapped["Employee"] = db.relationship("Employee", lazy="joined")
    academic_year: Mapped[Optional["AcademicYear"]] = db.relationship("AcademicYear", lazy="joined")
    academic_term: Mapped[Optional["AcademicTerm"]] = db.relationship("AcademicTerm", lazy="joined")
    time_slot: Mapped["TimeSlot"] = db.relationship(
        "TimeSlot",
        back_populates="schedule_slots",
        lazy="joined",
    )
    classroom: Mapped[Optional["Classroom"]] = db.relationship(
        "Classroom",
        back_populates="schedule_slots",
        lazy="joined",
    )
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    attendance_sheets: Mapped[List["StudentAttendance"]] = db.relationship(
        "StudentAttendance",
        back_populates="schedule_slot",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Conflict rules (simple UNIQUE; NULL cases handled in service layer)
        # 1) A group cannot have two different lessons same weekday+slot per year+term
        UniqueConstraint(
            "company_id",
            "student_group_id",
            "weekday",
            "time_slot_id",
            "academic_year_id",
            "academic_term_id",
            name="uq_css_group_timeslot_per_year_term",
        ),
        # 2) A teacher cannot be in two groups same weekday+slot per year+term
        UniqueConstraint(
            "company_id",
            "teacher_id",
            "weekday",
            "time_slot_id",
            "academic_year_id",
            "academic_term_id",
            name="uq_css_teacher_timeslot_per_year_term",
        ),
        # 3) A classroom cannot be double-booked (when classroom is set)
        UniqueConstraint(
            "company_id",
            "classroom_id",
            "weekday",
            "time_slot_id",
            "academic_year_id",
            "academic_term_id",
            name="uq_css_classroom_timeslot_per_year_term",
        ),

        Index("ix_course_schedule_slots_company_id", "company_id"),
        Index(
            "ix_css_group_weekday",
            "student_group_id",
            "weekday",
            "time_slot_id",
        ),
        Index(
            "ix_css_teacher_weekday",
            "teacher_id",
            "weekday",
            "time_slot_id",
        ),
        Index("ix_css_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self):
        return (
            f"<CourseScheduleSlot id={self.id} company_id={self.company_id} "
            f"group={self.student_group_id} course={self.course_id} "
            f"weekday={self.weekday.value} timeslot={self.time_slot_id}>"
        )


# ============================================================
# Student Attendance (header)
# ============================================================

class StudentAttendance(BaseModel, TenantMixin):
    """
    Header for a set of student attendance records.

    How it works with EducationSettings.attendance_based_on_course_schedule:

    - If True:
        * One StudentAttendance per CourseScheduleSlot + date
          (source = COURSE_SCHEDULE, schedule_slot_id filled).
        * Teacher opens the timetable cell and marks all students.

    - If False:
        * One StudentAttendance per StudentGroup + date
          (source = STUDENT_GROUP, only group+session/time_slot optional).

    - For Quran:
        * Use COURSE_SCHEDULE if you build a detailed timetable,
          or use QURAN_SESSION with session_id/time_slot_id only (no course).
    """
    __tablename__ = "student_attendance"

    # Human-readable code (e.g. EDU-ATT-2025-00001)
    attendance_code: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
        comment="Human-readable attendance reference like 'EDU-ATT-2025-00001'.",
    )

    attendance_date: Mapped[date] = mapped_column(
        db.Date,
        nullable=False,
        index=True,
    )

    source: Mapped[StudentAttendanceSourceEnum] = mapped_column(
        db.Enum(StudentAttendanceSourceEnum, name="attendance_source_enum"),
        nullable=False,
        default=StudentAttendanceSourceEnum.COURSE_SCHEDULE,
        index=True,
    )

    # Context links (optional depending on mode)
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
    program_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_programs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    student_group_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_student_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    course_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_courses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    course_assignment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("course_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schedule_slot_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("course_schedule_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Useful for Quran or simple session-based attendance (no full timetable)
    session_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("school_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Useful for Quran or simple session-based attendance.",
    )
    time_slot_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("time_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Which branch took this attendance
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Who took the attendance (user)
    taken_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who submitted this attendance sheet.",
    )
    taken_at: Mapped[Optional[datetime]] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum),
        nullable=False,
        default=DocStatusEnum.DRAFT,
        index=True,
        comment="Use SUBMITTED when attendance is final/locked.",
    )

    is_locked: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="If true, prevent further edits.",
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
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
    program: Mapped[Optional["Program"]] = db.relationship(
        "Program",
        lazy="joined",
    )
    student_group: Mapped[Optional["StudentGroup"]] = db.relationship(
        "StudentGroup",
        lazy="joined",
    )
    course: Mapped[Optional["Course"]] = db.relationship(
        "Course",
        lazy="joined",
    )
    course_assignment: Mapped[Optional["CourseAssignment"]] = db.relationship(
        "CourseAssignment",
        lazy="joined",
    )
    schedule_slot: Mapped[Optional["CourseScheduleSlot"]] = db.relationship(
        "CourseScheduleSlot",
        back_populates="attendance_sheets",
        lazy="joined",
    )
    session: Mapped[Optional["SchoolSession"]] = db.relationship(
        "SchoolSession",
        lazy="joined",
    )
    time_slot: Mapped[Optional["TimeSlot"]] = db.relationship(
        "TimeSlot",
        lazy="joined",
    )
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )

    taken_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[taken_by_user_id],
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    details: Mapped[List["StudentAttendanceRow"]] = db.relationship(
        "StudentAttendanceRow",
        back_populates="attendance",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Attendance code unique per company
        UniqueConstraint(
            "company_id", "attendance_code",
            name="uq_attendance_code_per_company",
        ),
        # Simple context uniqueness (DB will not cover all-NULL cases; service layer should)
        UniqueConstraint(
            "company_id",
            "attendance_date",
            "source",
            "student_group_id",
            "course_id",
            "time_slot_id",
            "schedule_slot_id",
            name="uq_attendance_sheet_context",
        ),
        Index("ix_student_attendance_company_date", "company_id", "attendance_date"),
        Index(
            "ix_student_attendance_company_group_date",
            "company_id",
            "student_group_id",
            "attendance_date",
        ),
        Index("ix_student_attendance_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self):
        return (
            f"<StudentAttendance id={self.id} company_id={self.company_id} "
            f"code={self.attendance_code!r} date={self.attendance_date} "
            f"source={self.source.value}>"
        )


# ============================================================
# Student Attendance Row (line)
# ============================================================

class StudentAttendanceRow(BaseModel, TenantMixin):
    """
    One student's status inside an attendance sheet.

    Works for all program types (K-12 / Institute / Quran).
    """
    __tablename__ = "student_attendance_rows"

    attendance_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("student_attendance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    program_enrollment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_program_enrollments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # copy branch for faster reporting (optional)
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[StudentAttendanceStatusEnum] = mapped_column(
        db.Enum(StudentAttendanceStatusEnum, name="student_attendance_status_enum"),
        nullable=False,
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        lazy="joined",
    )
    attendance: Mapped["StudentAttendance"] = db.relationship(
        "StudentAttendance",
        back_populates="details",
        lazy="joined",
    )
    student: Mapped["Student"] = db.relationship(
        "Student",
        lazy="joined",
    )
    program_enrollment: Mapped[Optional["ProgramEnrollment"]] = db.relationship(
        "ProgramEnrollment",
        lazy="joined",
    )
    branch: Mapped[Optional["Branch"]] = db.relationship(
        "Branch",
        lazy="joined",
    )
    created_by_user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[created_by_user_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "attendance_id", "student_id",
            name="uq_attendance_student_once",
        ),
        Index(
            "ix_student_attendance_rows_company_student",
            "company_id",
            "student_id",
        ),
    )

    def __repr__(self):
        return (
            f"<StudentAttendanceRow id={self.id} company_id={self.company_id} "
            f"attendance_id={self.attendance_id} student_id={self.student_id} "
            f"status={self.status.value}>"
        )
