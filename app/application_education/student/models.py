# app/application_education/student/models.py
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
from app.common.models.base import (
    BaseModel,
    TenantMixin,
    GenderEnum,
    PersonRelationshipEnum,
)

# =====================================================================================
# Extra enums for student-specific data
# =====================================================================================

class BloodGroupEnum(str, enum.Enum):
    A_POSITIVE = "A+"
    A_NEGATIVE = "A-"
    B_POSITIVE = "B+"
    B_NEGATIVE = "B-"
    O_POSITIVE = "O+"
    O_NEGATIVE = "O-"
    AB_POSITIVE = "AB+"
    AB_NEGATIVE = "AB-"


class OrphanStatusEnum(str, enum.Enum):
    NOT_ORPHAN = "Not Orphan"
    NO_FATHER = "No Father"
    NO_MOTHER = "No Mother"
    BOTH = "Both"


# =====================================================================================
# GUARDIAN (Master)
# =====================================================================================

class Guardian(BaseModel, TenantMixin):
    """
    Master record for a Guardian (parent / relative / sponsor).

    - Belongs to a Company (TenantMixin: company_id).
    - Scoped to a Branch (campus).
    - Can be linked to many Students via StudentGuardian.
    """
    __tablename__ = "edu_guardians"

    # --- Branch Context ---
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Code + Core Details ---
    guardian_code: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
        comment="Human-readable guardian ID, unique per branch.",
    )

    guardian_name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        comment="Full name of guardian.",
    )

    # --- Contact ---
    email_address: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        index=True,
    )
    mobile_number: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        index=True,
    )
    alternate_number: Mapped[Optional[str]] = mapped_column(
        db.String(50),
    )

    # --- Personal & Professional ---
    date_of_birth: Mapped[Optional[date]] = mapped_column(db.Date)
    education: Mapped[Optional[str]] = mapped_column(db.String(255))
    occupation: Mapped[Optional[str]] = mapped_column(db.String(255))
    work_address: Mapped[Optional[str]] = mapped_column(db.Text)

    # --- System Link (optional user record) ---
    user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Relationships ---
    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="guardians",
        lazy="joined",
    )
    branch: Mapped["Branch"] = relationship(
        "Branch",
        lazy="joined",
    )
    user: Mapped[Optional["User"]] = relationship(
        "User",
        lazy="joined",
        foreign_keys=[user_id],
    )

    students: Mapped[List["StudentGuardian"]] = relationship(
        "StudentGuardian",
        back_populates="guardian",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Guardian code unique within same company & branch
        UniqueConstraint(
            "company_id", "branch_id", "guardian_code",
            name="uq_guardian_code_per_branch",
        ),
        # Guardian email unique within same branch & company (when set)
        UniqueConstraint(
            "company_id", "branch_id", "email_address",
            name="uq_guardian_email_per_branch",
        ),
        # Guardian mobile unique within same branch & company (when set)
        UniqueConstraint(
            "company_id", "branch_id", "mobile_number",
            name="uq_guardian_mobile_per_branch",
        ),

        Index("ix_edu_guardians_company_branch", "company_id", "branch_id"),
        Index("ix_edu_guardians_branch_id", "branch_id"),
        Index("ix_edu_guardians_name", "guardian_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<Guardian id={self.id} company_id={self.company_id} "
            f"code={self.guardian_code!r} name={self.guardian_name!r}>"
        )


# =====================================================================================
# STUDENT
# =====================================================================================

class Student(BaseModel, TenantMixin):
    """
    Core Student record.

    - TenantMixin gives company_id.
    - branch_id points to campus/branch.
    - Links to Guardian via StudentGuardian.
    - Linked to classes via ProgramEnrollment / CourseEnrollment.
    """
    __tablename__ = "students"

    # --- Branch Context ---
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Status & Key Code ---
    is_enabled: Mapped[bool] = mapped_column(
        db.Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Disable when student leaves school or is archived.",
    )

    student_code: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
        comment="Unique student reference / admission number within branch.",
    )

    # --- Core Identity (single full name) ---
    full_name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        index=True,
        comment="Student full name.",
    )

    joining_date: Mapped[Optional[date]] = mapped_column(
        db.Date,
        index=True,
        comment="Date the student joined the institution.",
    )

    # --- System Link (optional user account) ---
    user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Personal Details ---
    student_email: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        index=True,
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(db.Date)
    blood_group: Mapped[Optional[BloodGroupEnum]] = mapped_column(
        db.Enum(BloodGroupEnum, name="blood_group_enum"),
        index=True,
    )
    student_mobile_number: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        index=True,
    )
    gender: Mapped[Optional[GenderEnum]] = mapped_column(
        db.Enum(GenderEnum, name="hr_gender_enum"),
        index=True,
    )
    nationality: Mapped[Optional[str]] = mapped_column(db.String(100))
    orphan_status: Mapped[Optional[OrphanStatusEnum]] = mapped_column(
        db.Enum(OrphanStatusEnum, name="orphan_status_enum"),
        index=True,
        nullable=True,
    )

    # --- Exit Details ---
    date_of_leaving: Mapped[Optional[date]] = mapped_column(db.Date)
    leaving_certificate_number: Mapped[Optional[str]] = mapped_column(
        db.String(100),
    )
    reason_for_leaving: Mapped[Optional[str]] = mapped_column(db.Text)

    # --- Relationships ---
    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="students",
        lazy="joined",
    )
    branch: Mapped["Branch"] = db.relationship(
        "Branch",
        lazy="joined",
    )
    user: Mapped[Optional["User"]] = db.relationship(
        "User",
        lazy="joined",
        foreign_keys=[user_id],
    )

    guardians: Mapped[List["StudentGuardian"]] = db.relationship(
        "StudentGuardian",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    program_enrollments: Mapped[List["ProgramEnrollment"]] = db.relationship(
        "ProgramEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    course_enrollments: Mapped[List["CourseEnrollment"]] = db.relationship(
        "CourseEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Unique code per branch+company
        UniqueConstraint(
            "company_id", "branch_id", "student_code",
            name="uq_student_code_per_branch",
        ),
        # Unique email per branch+company (optional)
        UniqueConstraint(
            "company_id", "branch_id", "student_email",
            name="uq_student_email_per_branch",
        ),

        # Composite indexes for lookups
        Index("ix_students_company_branch", "company_id", "branch_id"),
        Index("ix_students_branch_id", "branch_id"),
        Index("ix_students_full_name", "full_name"),
        Index("ix_students_status_branch", "is_enabled", "branch_id"),

        # Logical date constraint
        CheckConstraint(
            "date_of_leaving IS NULL OR date_of_leaving >= joining_date",
            name="chk_student_leaving_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Student id={self.id} company_id={self.company_id} "
            f"code={self.student_code!r} name={self.full_name!r}>"
        )


# =====================================================================================
# STUDENT <-> GUARDIAN LINK
# =====================================================================================

class StudentGuardian(BaseModel, TenantMixin):
    """
    Many-to-many association between Student and Guardian.

    - Defines relationship (Father, Mother, Guardian, etc.).
    - One student can have many guardians.
    - One guardian can be linked to many students.
    - Only one guardian can be marked 'is_primary' for a student.
    """
    __tablename__ = "edu_student_guardians"

    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Branch context where this link is managed.",
    )

    student_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    guardian_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("edu_guardians.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    relationship: Mapped[PersonRelationshipEnum] = mapped_column(
        db.Enum(PersonRelationshipEnum, name="hr_person_relationship_enum"),
        index=True,
        nullable=False,
        comment="Relation to student (Father, Mother, Guardian, etc.).",
    )

    is_primary: Mapped[bool] = mapped_column(
        db.Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="At most one primary guardian per student.",
    )

    # --- Relationships ---
    student: Mapped["Student"] = db.relationship(
        "Student",
        back_populates="guardians",
        lazy="joined",
    )
    guardian: Mapped["Guardian"] = db.relationship(
        "Guardian",
        back_populates="students",
        lazy="joined",
    )
    branch: Mapped["Branch"] = db.relationship(
        "Branch",
        lazy="joined",
    )

    __table_args__ = (
        # Prevent duplicate link of same student+guardian+branch
        UniqueConstraint(
            "student_id", "guardian_id", "branch_id",
            name="uq_student_guardian_link_per_branch",
        ),

        # Only one primary guardian per student (conditional unique index)
        Index(
            "uq_student_primary_guardian",
            "student_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),

        Index("ix_edu_student_guardians_company_branch", "company_id", "branch_id"),
        Index("ix_edu_student_guardians_branch_id", "branch_id"),
        Index(
            "ix_edu_student_guardians_student_relationship",
            "student_id",
            "relationship",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentGuardian id={self.id} company_id={self.company_id} "
            f"student_id={self.student_id} guardian_id={self.guardian_id} "
            f"relationship={self.relationship.value} primary={self.is_primary}>"
        )
