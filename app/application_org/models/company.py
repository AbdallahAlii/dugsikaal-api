

# app/apps/application_org/models.py
from __future__ import annotations

from datetime import date
from typing import Optional, List

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
    # Abbreviation / prefix used in naming series, account numbers, etc.
    # (Equivalent to ERPNext 'Abbr')
    prefix: Mapped[Optional[str]] = mapped_column(
        db.String(20),
        unique=True,
        nullable=True,
        index=True,
        comment="Short code/abbreviation used in naming series (e.g. 'D').",
    )
    # Country & currency are global properties used by all modules
    country: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        index=True,
        comment="Country where this legal entity is based.",
    )

    default_currency: Mapped[Optional[str]] = mapped_column(
        db.String(10),
        nullable=True,
        index=True,
        comment="Default currency code (e.g. 'USD', 'SOS').",
    )
    date_of_establishment: Mapped[Optional[date]] = mapped_column(
        db.Date,
        nullable=True,
        comment="Date the company was legally established.",
    )

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
    timezone: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        nullable=True,
        default=None,  # Or set a sensible default if required, e.g., 'UTC'
        comment="IANA Timezone string (e.g., 'America/New_York') for company operations",
    )
    # relationships
    data_imports: Mapped[list["DataImport"]] = db.relationship(
        "DataImport",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    city: Mapped["City"] = db.relationship("City", back_populates="companies",  lazy="select")
    branches: Mapped[list["Branch"]] = db.relationship(
        "Branch",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    departments: Mapped[list["Department"]] = db.relationship(
        "Department",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    # Accounting relationships
    accounts: Mapped[list["Account"]] = db.relationship(
        "Account",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    fiscal_years: Mapped[list["FiscalYear"]] = db.relationship(
        "FiscalYear",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    period_closing_vouchers: Mapped[list["PeriodClosingVoucher"]] = db.relationship(
        "PeriodClosingVoucher",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    cost_centers: Mapped[list["CostCenter"]] = db.relationship(
        "CostCenter",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    journal_entries: Mapped[list["JournalEntry"]] = db.relationship(
        "JournalEntry",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    general_ledger_entries: Mapped[list["GeneralLedgerEntry"]] = db.relationship(
        "GeneralLedgerEntry",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    gl_entry_templates: Mapped[list["GLEntryTemplate"]] = db.relationship(
        "GLEntryTemplate",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    # Payment and Expense relationships
    payment_entries: Mapped[list["PaymentEntry"]] = db.relationship(
        "PaymentEntry",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    expenses: Mapped[list["Expense"]] = db.relationship(
        "Expense",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    expense_types: Mapped[list["ExpenseType"]] = db.relationship(
        "ExpenseType",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    # Other existing relationships
    purchase_receipts: Mapped[list["PurchaseReceipt"]] = db.relationship(
        "PurchaseReceipt",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    purchase_quotations: Mapped[list["PurchaseQuotation"]] = db.relationship(
        "PurchaseQuotation",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    purchase_invoices: Mapped[list["PurchaseInvoice"]] = db.relationship(
        "PurchaseInvoice",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    modes_of_payment: Mapped[list["ModeOfPayment"]] = db.relationship(
        "ModeOfPayment",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    brands: Mapped[list["Brand"]] = db.relationship(
        "Brand",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    units_of_measure: Mapped[list["UnitOfMeasure"]] = db.relationship(
        "UnitOfMeasure",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    item_groups: Mapped[list["ItemGroup"]] = db.relationship(
        "ItemGroup",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    items: Mapped[list["Item"]] = db.relationship(
        "Item",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    price_lists: Mapped[list["PriceList"]] = db.relationship(
        "PriceList",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    # ADD THIS MISSING RELATIONSHIP
    item_prices: Mapped[list["ItemPrice"]] = db.relationship(
        "ItemPrice",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    # ------------------------------------------------------------------
    # Shareholders / equity (simple ERPNext-style setup)
    # ------------------------------------------------------------------
    shareholders: Mapped[list["Shareholder"]] = db.relationship(
        "Shareholder",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    share_types: Mapped[list["ShareType"]] = db.relationship(
        "ShareType",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    share_ledger_entries: Mapped[list["ShareLedgerEntry"]] = db.relationship(
        "ShareLedgerEntry",
        back_populates="company",
        cascade="all, delete-orphan",
    )
    # ------------------------------------------------------------------
    # 🔹 NEW: Print / Letterhead relationships (to match app/application_print/models.py)
    # ------------------------------------------------------------------
    print_letterheads: Mapped[list["PrintLetterhead"]] = db.relationship(
        "PrintLetterhead",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    print_styles: Mapped[list["PrintStyle"]] = db.relationship(
        "PrintStyle",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    # One row per company (UniqueConstraint), so use uselist=False
    print_settings: Mapped[Optional["PrintSettings"]] = db.relationship(
        "PrintSettings",
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select"
    )

    print_formats: Mapped[list["PrintFormat"]] = db.relationship(
        "PrintFormat",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    # ---- Education ----
    education_settings: Mapped[Optional["EducationSettings"]] = db.relationship(
        "EducationSettings",
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan",
    )
    academic_years: Mapped[list["AcademicYear"]] = db.relationship(
        "AcademicYear",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    academic_terms: Mapped[list["AcademicTerm"]] = db.relationship(
        "AcademicTerm",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    accounting_settings: Mapped[Optional["AccountingSettings"]] = db.relationship(
        "AccountingSettings",
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # ---- Education: Guardians / Students ----
    guardians: Mapped[list["Guardian"]] = db.relationship(
        "Guardian",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    students: Mapped[list["Student"]] = db.relationship(
        "Student",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    programs: Mapped[list["Program"]] = db.relationship(
        "Program",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    courses: Mapped[list["Course"]] = db.relationship(
        "Course",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    # ------------------------------------------------------------------
    # Education: enrollments & progression
    # ------------------------------------------------------------------

    program_enrollments: Mapped[list["ProgramEnrollment"]] = db.relationship(
        "ProgramEnrollment",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    course_enrollments: Mapped[list["CourseEnrollment"]] = db.relationship(
        "CourseEnrollment",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    program_progression_rules: Mapped[list["ProgramProgressionRule"]] = db.relationship(
        "ProgramProgressionRule",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    # ------------------------------------------------------------------
    # Education: batches, groups, categories
    # ------------------------------------------------------------------

    batches: Mapped[list["Batch"]] = db.relationship(
        "Batch",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    student_categories: Mapped[list["StudentCategory"]] = db.relationship(
        "StudentCategory",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    student_groups: Mapped[list["StudentGroup"]] = db.relationship(
        "StudentGroup",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )
    grading_scales: Mapped[list["GradingScale"]] = db.relationship(
        "GradingScale",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
    )

    assessment_criteria: Mapped[list["AssessmentCriterion"]] = db.relationship(
        "AssessmentCriterion",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select"
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
    data_imports: Mapped[list["DataImport"]] = db.relationship(
        "DataImport",
        back_populates="branch",
        cascade="all, delete-orphan",
        lazy="select"
    )

    company: Mapped["Company"] = db.relationship("Company", back_populates="branches")

    # Accounting relationships
    cost_centers: Mapped[list["CostCenter"]] = db.relationship(
        "CostCenter",
        back_populates="branch",
        cascade="all, delete-orphan",
    )

    journal_entries: Mapped[list["JournalEntry"]] = db.relationship(
        "JournalEntry",
        back_populates="branch",
        cascade="all, delete-orphan",
    )
    general_ledger_entries: Mapped[list["GeneralLedgerEntry"]] = db.relationship(
        "GeneralLedgerEntry",
        back_populates="branch",
        cascade="all, delete-orphan",
    )

    # Payment and Expense relationships
    payment_entries: Mapped[list["PaymentEntry"]] = db.relationship(
        "PaymentEntry",
        back_populates="branch"
    )
    expenses: Mapped[list["Expense"]] = db.relationship(
        "Expense",
        back_populates="branch"
    )

    # Other existing relationships
    purchase_receipts: Mapped[list["PurchaseReceipt"]] = db.relationship(
        "PurchaseReceipt",
        back_populates="branch"
    )
    purchase_invoices: Mapped[list["PurchaseInvoice"]] = db.relationship(
        "PurchaseInvoice",
        back_populates="branch"
    )
    purchase_quotations: Mapped[list["PurchaseQuotation"]] = db.relationship(
        "PurchaseQuotation",
        back_populates="branch"
    )

    item_prices: Mapped[List["ItemPrice"]] = db.relationship(
        "ItemPrice", back_populates="branch", cascade="all, delete-orphan"
    )
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





