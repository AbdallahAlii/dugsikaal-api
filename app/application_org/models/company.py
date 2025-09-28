# app/apps/application_org/models.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from config.database import db
from app.common.models.base import BaseModel, StatusEnum


class City(BaseModel):
    __tablename__ = "cities"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    region: Mapped[Optional[str]] = mapped_column(db.String(100), index=True)

    # relationships
    companies: Mapped[list["Company"]] = db.relationship("Company", back_populates="city")

    def __repr__(self) -> str:
        return f"<City id={self.id} name={self.name!r}>"


class Company(BaseModel):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(db.String(255), nullable=False, unique=True, index=True)
    headquarters_address: Mapped[Optional[str]] = mapped_column(db.Text)
    contact_email: Mapped[Optional[str]] = mapped_column(db.String(255), unique=True, index=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(db.String(50), unique=True)
    city_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("cities.id", ondelete="SET NULL"),
        index=True,
    )
    prefix: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=True, index=True)

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="company_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
    )
    img_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        nullable=True,
        comment="Object-storage key/path for the encrypted image",
        index=True,
    )
    # relationships
    city: Mapped["City"] = db.relationship("City", back_populates="companies", lazy="selectin")
    branches: Mapped[list["Branch"]] = db.relationship(
        "Branch",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    departments: Mapped[list["Department"]] = db.relationship(
        "Department",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Company id={self.id} name={self.name!r}>"


class Branch(BaseModel):
    __tablename__ = "branches"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(db.String(50), unique=True)
    location: Mapped[Optional[str]] = mapped_column(db.Text)
    is_hq: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="branch_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
    )
    img_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        nullable=True,
        comment="Object-storage key/path for the encrypted image",
        index=True,
    )
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_branch_name_per_company"),
        db.Index("ix_branches_company_id", "company_id"),
    )

    # relationships
    company: Mapped["Company"] = db.relationship("Company", back_populates="branches")


    def __repr__(self) -> str:
        return f"<Branch id={self.id} name={self.name!r} company_id={self.company_id}>"


class Department(BaseModel):
    __tablename__ = "departments"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(db.String(50))
    description: Mapped[Optional[str]] = mapped_column(db.String(255))

    # mark canonical, pre-seeded rows
    is_system_defined: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, index=True
    )

    # optional audit
    created_by: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="dept_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_dept_name_per_company"),
        UniqueConstraint("company_id", "code", name="uq_dept_code_per_company"),
        db.Index("ix_departments_company_id", "company_id"),
    )

    company: Mapped["Company"] = db.relationship("Company")

    def __repr__(self) -> str:
        return f"<Department id={self.id} name={self.name!r} company_id={self.company_id}>"










# class BranchDepartment(BaseModel):
#     __tablename__ = "branch_departments"
#
#     # Convenience copy for fast filtering (optional but useful)
#     company_id: Mapped[int] = mapped_column(
#         db.BigInteger,
#         db.ForeignKey("companies.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True,
#     )
#
#     branch_id: Mapped[int] = mapped_column(
#         db.BigInteger,
#         db.ForeignKey("branches.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True,
#     )
#
#     department_id: Mapped[int] = mapped_column(
#         db.BigInteger,
#         db.ForeignKey("departments.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True,
#     )
#
#     # Contact / operational overrides at the branch
#     contact_phone: Mapped[Optional[str]] = mapped_column(db.String(50))
#     contact_email: Mapped[Optional[str]] = mapped_column(db.String(255))
#     location_note: Mapped[Optional[str]] = mapped_column(db.String(255))
#
#     # Finance defaults (adjust FK table names to your actual models)
#     default_income_account_id:  Mapped[Optional[int]] = mapped_column(
#         db.BigInteger, db.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
#     )
#     default_expense_account_id: Mapped[Optional[int]] = mapped_column(
#         db.BigInteger, db.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
#     )
#     default_cost_center_id:     Mapped[Optional[int]] = mapped_column(
#         db.BigInteger, db.ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True, index=True
#     )
#
#     # Status / toggles
#     is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
#
#     # Future-proof bucket for misc settings (printer name, numbering, etc.)
#     extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
#
#     __table_args__ = (
#         # One row per (branch, department)
#         db.UniqueConstraint("branch_id", "department_id", name="uq_branch_department"),
#         db.Index("ix_branch_departments_branch", "branch_id"),
#         db.Index("ix_branch_departments_department", "department_id"),
#     )
#
#     # Relationships (optional; helps with joinedload)
#     branch:     Mapped["Branch"]     = db.relationship("Branch")
#     department: Mapped["Department"] = db.relationship("Department")
#     company:    Mapped["Company"]    = db.relationship("Company")
#
#     def __repr__(self) -> str:
#         return f"<BranchDepartment branch_id={self.branch_id} dept_id={self.department_id} active={self.is_active}>"