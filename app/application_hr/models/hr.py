# app/hr/hr.py
from __future__ import annotations
from typing import Optional
from datetime import date

from sqlalchemy import UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from config.database import db
from app.common.models.base import BaseModel, StatusEnum, GenderEnum, PersonRelationshipEnum


# -------------------------
# Employee (no branch here)
# -------------------------
class Employee(BaseModel):
    __tablename__ = "employees"

    # tenant
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # identity / contact
    code: Mapped[str] = mapped_column(db.String(100), nullable=False)  # unique per company
    full_name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    personal_email: Mapped[Optional[str]] = mapped_column(db.String(255))
    phone_number: Mapped[Optional[str]] = mapped_column(db.String(50))
    img_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        nullable=True,
        comment="Object-storage key/path for the encrypted image",
        index=True,
    )

    # basic HR fields
    dob: Mapped[Optional[date]] = mapped_column(db.Date)
    date_of_joining: Mapped[Optional[date]] = mapped_column(db.Date)
    sex: Mapped[Optional[GenderEnum]] = mapped_column(
        db.Enum(GenderEnum, name="gender_enum"),
        nullable=True,
    )

    # optional login user
    user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # lifecycle
    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="employee_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    __table_args__ = (
        # Prevent duplicate codes inside the same company
        UniqueConstraint("company_id", "code", name="uq_employee_code_per_company"),
        Index("ix_employees_company", "company_id"),
    )

    # relationships
    company = db.relationship("Company", lazy="joined")
    user = db.relationship("User", backref=db.backref("employee", uselist=False), lazy="selectin")

    # convenient access to assignments (most-recent first)
    assignments = db.relationship(
        "EmployeeAssignment",
        back_populates="employee",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="desc(EmployeeAssignment.from_date)",
    )

    @property
    def primary_assignment(self) -> Optional["EmployeeAssignment"]:
        # prefer an active primary; else fallback to the most recent row
        for a in self.assignments:
            if a.is_primary and a.to_date is None:
                return a
        return self.assignments[0] if self.assignments else None

    @property
    def primary_branch_id(self) -> Optional[int]:
        pa = self.primary_assignment
        return pa.branch_id if pa else None

    def __repr__(self) -> str:
        return f"<Employee id={self.id} code={self.code!r} name={self.full_name!r}>"


# ------------------------------------
# EmployeeEmergencyContact (unchanged)
# ------------------------------------
class EmployeeEmergencyContact(BaseModel):
    __tablename__ = "employee_emergency_contacts"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    relationship_type: Mapped[PersonRelationshipEnum] = mapped_column(
        db.Enum(PersonRelationshipEnum, name="person_relationship_enum"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(db.String(50), nullable=False)

    __table_args__ = (
        Index("ix_emp_ec_employee_rel", "employee_id", "relationship_type"),
    )

    employee = db.relationship(
        "Employee",
        backref=db.backref("emergency_contacts", cascade="all, delete-orphan", lazy="selectin"),
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<EmployeeEmergencyContact id={self.id} employee_id={self.employee_id} name={self.full_name!r}>"


# -------------------------------------------------
# EmployeeAssignment (branch/department + history)
# -------------------------------------------------
class EmployeeAssignment(BaseModel):
    """
    Branch/Department placement with history.
    Keep Employee.company_id as the canonical tenant; we mirror it here for fast filters.
    """
    __tablename__ = "employee_assignments"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(  # mirror for quick queries
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    job_title: Mapped[Optional[str]] = mapped_column(db.String(120))

    from_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    to_date:   Mapped[Optional[date]] = mapped_column(db.Date)

    is_primary: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="emp_assignment_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    # any per-posting extras (printer id, cost center note, extension, etc.)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # no duplicates for same (employee, branch, from_date)
        UniqueConstraint("employee_id", "branch_id", "from_date", name="uq_emp_branch_from"),
        Index("ix_emp_assign_company_branch", "company_id", "branch_id"),
        # Postgres-only: only one active primary assignment at a time
        Index(
            "uq_emp_primary_assignment",
            "employee_id",
            unique=True,
            postgresql_where=text("is_primary = true AND to_date IS NULL"),
        ),
    )

    employee   = db.relationship("Employee", lazy="joined", back_populates="assignments")
    company    = db.relationship("Company",  lazy="joined")
    branch     = db.relationship("Branch",   lazy="joined")
    department = db.relationship("Department", lazy="joined")

    def __repr__(self) -> str:
        return f"<EmployeeAssignment emp={self.employee_id} branch={self.branch_id} primary={self.is_primary}>"
