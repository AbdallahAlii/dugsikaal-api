# app/application_education/fees/models.py
from __future__ import annotations

import enum
from decimal import Decimal
from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin


# ──────────────────────────────────────────────────────────────────────────────
# ENUMS
# ──────────────────────────────────────────────────────────────────────────────
class FeeScheduleStatusEnum(str, enum.Enum):
    DRAFT = "Draft"
    INVOICE_PENDING = "Invoice Pending"
    INVOICE_CREATED = "Invoice Created"
    CANCELLED = "Cancelled"


# ──────────────────────────────────────────────────────────────────────────────
# 1) FEE CATEGORY  (Tuition, Transport, Exam, Admission...)
# ──────────────────────────────────────────────────────────────────────────────
class FeeCategory(BaseModel, TenantMixin):
    __tablename__ = "edu_fee_categories"

    name: Mapped[str] = mapped_column(db.String(140), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    # Optional mapping to a SERVICE Item (recommended)
    item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    item: Mapped[Optional["Item"]] = relationship("Item", lazy="joined")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_fee_category_company_name"),
        # Helpful filter/index for list pages: enabled categories per company
        Index("ix_fee_categories_company_enabled", "company_id", "is_enabled"),
    )

    def __repr__(self) -> str:
        return f"<FeeCategory id={self.id} company_id={self.company_id} name={self.name!r}>"


# ──────────────────────────────────────────────────────────────────────────────
# 2) FEE STRUCTURE (Versioned)
# ──────────────────────────────────────────────────────────────────────────────
class FeeStructure(BaseModel, TenantMixin):
    __tablename__ = "edu_fee_structures"

    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)

    program_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Optional grouping (use only when you need it)
    # ✅ FIX: correct table name is "student_categories"
    student_category_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("student_categories.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Versioning
    version_no: Mapped[int] = mapped_column(
        db.Integer,
        nullable=False,
        default=1,
        index=True,
        comment="1,2,3... increment when fees change.",
    )
    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    # Optional: fetch invoice rates from ItemPrice using this selling price list
    selling_price_list_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("price_lists.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    program: Mapped["Program"] = relationship("Program", lazy="joined")

    components: Mapped[List["FeeStructureComponent"]] = relationship(
        "FeeStructureComponent",
        back_populates="fee_structure",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Needed because FeeSchedule.fee_structure uses back_populates="schedules"
    schedules: Mapped[List["FeeSchedule"]] = relationship(
        "FeeSchedule",
        back_populates="fee_structure",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "program_id", "student_category_id", "branch_id", "version_no",
            name="uq_fee_structure_context_version"
        ),
        CheckConstraint("version_no >= 1", name="ck_fee_structure_version_min_1"),
        Index("ix_fee_structures_company_program", "company_id", "program_id"),
        Index("ix_fee_structures_company_program_enabled", "company_id", "program_id", "is_enabled"),
    )

    def __repr__(self) -> str:
        return (
            f"<FeeStructure id={self.id} company_id={self.company_id} "
            f"program_id={self.program_id} v={self.version_no} enabled={self.is_enabled}>"
        )


class FeeStructureComponent(BaseModel, TenantMixin):
    """
    FeeStructure child rows: (Fee Category + Amount)
    """
    __tablename__ = "edu_fee_structure_components"

    fee_structure_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_structures.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    fee_category_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_categories.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Optional override item; otherwise use FeeCategory.item_id
    item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    amount: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    is_optional: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    sequence_no: Mapped[Optional[int]] = mapped_column(db.Integer)
    description: Mapped[Optional[str]] = mapped_column(db.String(255))

    fee_structure: Mapped["FeeStructure"] = relationship("FeeStructure", back_populates="components", lazy="joined")
    fee_category: Mapped["FeeCategory"] = relationship("FeeCategory", lazy="joined")
    item: Mapped[Optional["Item"]] = relationship("Item", lazy="joined")

    __table_args__ = (
        UniqueConstraint("fee_structure_id", "fee_category_id", name="uq_fee_structure_one_row_per_category"),
        CheckConstraint("amount >= 0", name="ck_fee_struct_comp_amount_nonneg"),
        CheckConstraint("(sequence_no IS NULL) OR (sequence_no >= 0)", name="ck_fee_struct_comp_seq_nonneg"),
        Index("ix_fee_structure_components_structure_seq", "fee_structure_id", "sequence_no"),
    )

    def __repr__(self) -> str:
        return (
            f"<FeeStructureComponent id={self.id} company_id={self.company_id} "
            f"structure_id={self.fee_structure_id} category_id={self.fee_category_id} amount={self.amount}>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 3) FEE SCHEDULE (Bulk generation document)
# ──────────────────────────────────────────────────────────────────────────────
class FeeSchedule(BaseModel, TenantMixin):
    """
    Fee Schedule = group + due date + fee breakup.
    Running the schedule (service layer) generates Sales Invoices for all students in the group.
    """
    __tablename__ = "edu_fee_schedules"

    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)

    fee_structure_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_structures.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    student_group_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_student_groups.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Optional context (service layer can fill from group/enrollment)
    academic_year_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_academic_years.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    academic_term_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_academic_terms.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.utcnow(),
        index=True,
    )

    due_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)

    # UI helper fields (service may refresh)
    total_amount: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="UI helper; service can refresh from components.",
    )
    total_students: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    total_invoices: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)

    status: Mapped[FeeScheduleStatusEnum] = mapped_column(
        db.Enum(FeeScheduleStatusEnum, name="fee_schedule_status_enum"),
        nullable=False,
        default=FeeScheduleStatusEnum.DRAFT,
        index=True,
    )

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    fee_structure: Mapped["FeeStructure"] = relationship("FeeStructure", back_populates="schedules", lazy="joined")
    student_group: Mapped["StudentGroup"] = relationship("StudentGroup", lazy="joined")
    academic_year: Mapped[Optional["AcademicYear"]] = relationship("AcademicYear", lazy="joined")
    academic_term: Mapped[Optional["AcademicTerm"]] = relationship("AcademicTerm", lazy="joined")
    branch: Mapped[Optional["Branch"]] = relationship("Branch", lazy="joined")

    components: Mapped[List["FeeScheduleComponent"]] = relationship(
        "FeeScheduleComponent",
        back_populates="fee_schedule",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "fee_structure_id", "student_group_id", "due_date",
            name="uq_fee_schedule_one_per_due_date"
        ),
        CheckConstraint("total_amount >= 0", name="ck_fee_schedule_total_amount_nonneg"),
        CheckConstraint("total_students >= 0", name="ck_fee_schedule_total_students_nonneg"),
        CheckConstraint("total_invoices >= 0", name="ck_fee_schedule_total_invoices_nonneg"),
        Index("ix_fee_schedules_company_status", "company_id", "status"),
        Index("ix_fee_schedules_company_due", "company_id", "due_date"),
        Index("ix_fee_schedules_company_group_due", "company_id", "student_group_id", "due_date"),
        Index("ix_fee_schedules_company_enabled", "company_id", "is_enabled"),
    )

    def __repr__(self) -> str:
        return (
            f"<FeeSchedule id={self.id} company_id={self.company_id} "
            f"group_id={self.student_group_id} due={self.due_date} status={self.status.value}>"
        )


class FeeScheduleComponent(BaseModel, TenantMixin):
    """
    Snapshot/editable components for THIS schedule.
    Create by copying FeeStructureComponent when schedule is created.
    """
    __tablename__ = "edu_fee_schedule_components"

    fee_schedule_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_schedules.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    fee_category_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_categories.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    amount: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    is_optional: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    sequence_no: Mapped[Optional[int]] = mapped_column(db.Integer)
    description: Mapped[Optional[str]] = mapped_column(db.String(255))

    fee_schedule: Mapped["FeeSchedule"] = relationship("FeeSchedule", back_populates="components", lazy="joined")
    fee_category: Mapped["FeeCategory"] = relationship("FeeCategory", lazy="joined")
    item: Mapped[Optional["Item"]] = relationship("Item", lazy="joined")

    __table_args__ = (
        UniqueConstraint("fee_schedule_id", "fee_category_id", name="uq_fee_schedule_one_row_per_category"),
        CheckConstraint("amount >= 0", name="ck_fee_sched_comp_amount_nonneg"),
        CheckConstraint("(sequence_no IS NULL) OR (sequence_no >= 0)", name="ck_fee_sched_comp_seq_nonneg"),
        Index("ix_fee_schedule_components_schedule_seq", "fee_schedule_id", "sequence_no"),
    )

    def __repr__(self) -> str:
        return (
            f"<FeeScheduleComponent id={self.id} company_id={self.company_id} "
            f"schedule_id={self.fee_schedule_id} category_id={self.fee_category_id} amount={self.amount}>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4) STUDENT FEE ADJUSTMENT
# ──────────────────────────────────────────────────────────────────────────────
class StudentFeeAdjustmentTypeEnum(str, enum.Enum):
    DISCOUNT = "Discount"
    SCHOLARSHIP = "Scholarship"
    WAIVER = "Waiver"          # e.g., orphan/free program
    OVERRIDE = "Override"      # custom amount (special case)
    OTHER = "Other"


class StudentFeeAdjustment(BaseModel, TenantMixin):
    """
    Per-student overrides/discounts used during invoice generation.
    """
    __tablename__ = "edu_student_fee_adjustments"

    student_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    program_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    fee_category_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_categories.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    adjustment_type: Mapped[StudentFeeAdjustmentTypeEnum] = mapped_column(
        db.Enum(StudentFeeAdjustmentTypeEnum, name="student_fee_adjustment_type_enum"),
        nullable=False,
        default=StudentFeeAdjustmentTypeEnum.DISCOUNT,
        index=True,
        comment="Why this adjustment exists (Scholarship/Waiver/Discount/Override)."
    )

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    discount_percent: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(6, 3))
    discount_amount: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(12, 2))
    override_amount: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(12, 2))

    valid_from: Mapped[Optional[date]] = mapped_column(db.Date)
    valid_upto: Mapped[Optional[date]] = mapped_column(db.Date)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    student: Mapped["Student"] = relationship("Student", lazy="joined")
    program: Mapped["Program"] = relationship("Program", lazy="joined")
    fee_category: Mapped["FeeCategory"] = relationship("FeeCategory", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "company_id", "student_id", "program_id", "fee_category_id",
            name="uq_student_fee_adjustment_once"
        ),
        CheckConstraint(
            "(discount_percent IS NULL) OR (discount_percent >= 0 AND discount_percent <= 100)",
            name="ck_sfa_disc_pct_0_100"
        ),
        CheckConstraint("(discount_amount IS NULL) OR (discount_amount >= 0)", name="ck_sfa_disc_amt_nonneg"),
        CheckConstraint("(override_amount IS NULL) OR (override_amount >= 0)", name="ck_sfa_override_amt_nonneg"),
        CheckConstraint(
            "(valid_upto IS NULL) OR (valid_from IS NULL) OR (valid_upto >= valid_from)",
            name="ck_sfa_valid_range"
        ),
        Index("ix_sfa_lookup", "company_id", "student_id", "program_id", "fee_category_id"),
        Index("ix_sfa_company_enabled", "company_id", "is_enabled"),
        Index("ix_sfa_company_type", "company_id", "adjustment_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentFeeAdjustment id={self.id} company_id={self.company_id} "
            f"student_id={self.student_id} program_id={self.program_id} "
            f"category_id={self.fee_category_id} type={self.adjustment_type.value}>"
        )
