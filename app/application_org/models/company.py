# app/apps/application_org/models.py
from __future__ import annotations
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
    timezone: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        nullable=True,
        default=None,  # Or set a sensible default if required, e.g., 'UTC'
        comment="IANA Timezone string (e.g., 'America/New_York') for company operations",
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




