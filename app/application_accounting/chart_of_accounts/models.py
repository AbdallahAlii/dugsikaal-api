# application_accounting/chart_of_accounts/model.py
from __future__ import annotations

import enum
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, text, Enum, func

from app.application_stock.stock_models import DocStatusEnum
from app.common.models.base import BaseModel
from config.database import db



class FiscalYearStatusEnum(str, enum.Enum):
    OPEN = "Open"
    CLOSED = "Closed"

class AccountTypeEnum(str, enum.Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    INCOME = "Income"
    EXPENSE = "Expense"

class ReportTypeEnum(str, enum.Enum):
    BALANCE_SHEET = "Balance Sheet"
    PROFIT_AND_LOSS = "Profit & Loss"

class DebitOrCreditEnum(str, enum.Enum):
    DEBIT = "Debit"
    CREDIT = "Credit"

class PartyTypeEnum(str, enum.Enum):
    CUSTOMER = "Customer"
    SUPPLIER = "Supplier"
    EMPLOYEE = "Employee"
    SHAREHOLDER = "Shareholder"
    OTHER = "Other"

class JournalEntryTypeEnum(str, enum.Enum):
    GENERAL = "General"
    OPENING = "Opening"
    ADJUSTMENT = "Adjustment"
    AUTO = "Auto"
    AUTO_REVERSAL = "Auto Reversal"
    CLOSING = "Closing"  # Added for Period Closing Voucher

# ──────────────────────────────────────────────────────────────────────────────
# 1) FISCAL YEAR (Fixed with proper relationships)
# ──────────────────────────────────────────────────────────────────────────────
class FiscalYear(BaseModel):
    """
    Defines the time period container for financial reporting.
    All journal entries must belong to an open fiscal year.
    """
    __tablename__ = "fiscal_years"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)

    # Core Fields
    name: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True,
                                      comment="User-friendly name (e.g., 'FY 2024' or '2024-2025')")
    start_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    end_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[FiscalYearStatusEnum] = mapped_column(
        db.Enum(FiscalYearStatusEnum), nullable=False, default=FiscalYearStatusEnum.OPEN, index=True
    )
    is_short_year: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False,
                                               comment="True if period is less than 12 months.")

    # Relationships (FIXED: Added missing relationships)
    company: Mapped["Company"] = relationship(back_populates="fiscal_years")
    period_closing_vouchers: Mapped[List["PeriodClosingVoucher"]] = relationship(
        back_populates="closing_fiscal_year",
        cascade="all, delete-orphan"
    )
    journal_entries: Mapped[List["JournalEntry"]] = relationship(
        back_populates="fiscal_year",
        cascade="all, delete-orphan"
    )
    general_ledger_entries: Mapped[List["GeneralLedgerEntry"]] = relationship(
        back_populates="fiscal_year",
        cascade="all, delete-orphan"
    )


    # Table Constraints & Indices (ADDED performance indexes)
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_fiscal_year_company_name"),
        CheckConstraint("end_date > start_date", name="ck_fy_dates_valid"),
        # Performance indexes
        Index("ix_fy_company_status", "company_id", "status"),
        Index("ix_fy_dates_range", "start_date", "end_date"),
        Index("ix_fy_company_dates", "company_id", "start_date", "end_date"),
    )

    def __repr__(self) -> str:
        return f"<FiscalYear name={self.name} status={self.status}>"

# ──────────────────────────────────────────────────────────────────────────────
# 2) PERIOD CLOSING VOUCHER (Fixed with proper constraints)
# ──────────────────────────────────────────────────────────────────────────────
class PeriodClosingVoucher(BaseModel):
    """
    The management document that initiates the financial year closing.
    It triggers the final Journal Entry to transfer P/L to Retained Earnings.
    System can auto-prepare drafts, but MUST be submitted by a User.
    """
    __tablename__ = "period_closing_vouchers"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    closing_fiscal_year_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("fiscal_years.id"), nullable=False, index=True,
        comment="The Fiscal Year being closed."
    )
    closing_account_head_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True,
        comment="The Equity account (Retained Earnings) to book P&L."
    )
    generated_journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id"),
        nullable=True, unique=True, index=True,
        comment="The final Journal Entry for the closing process."
    )
    submitted_by_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("users.id"), nullable=True, index=True,
        comment="The User who submitted the voucher (required for SUBMITTED status)."
    )

    # Core Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True,
                                      comment="Unique document identifier.")
    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, index=True,
        comment="The effective date of the closing entry."
    )
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    auto_prepared: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, index=True,
        comment="True if system created this document as a DRAFT for human review."
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        db.DateTime(timezone=True), nullable=True, index=True
    )
    total_profit_loss: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000,
                                                    comment="Calculated Net P/L for the year.")

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="period_closing_vouchers")
    closing_fiscal_year: Mapped["FiscalYear"] = relationship(back_populates="period_closing_vouchers")
    closing_account_head: Mapped["Account"] = relationship(foreign_keys=[closing_account_head_id])
    generated_journal_entry: Mapped[Optional["JournalEntry"]] = relationship(
        "JournalEntry", foreign_keys=[generated_journal_entry_id]
    )
    submitted_by: Mapped[Optional["User"]] = relationship(foreign_keys=[submitted_by_id])

    # Table Constraints & Indices (ADDED performance indexes)
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_pcv_company_code"),
        # 🔴 removed uq_pcv_fiscal_year_company to allow multiple PCVs per FY
        CheckConstraint(
            "NOT (doc_status = 'SUBMITTED' AND submitted_by_id IS NULL)",
            name="ck_human_submission_required",
        ),
        Index("ix_pcv_company_status", "company_id", "doc_status"),
        Index("ix_pcv_posted_date", "posting_date", "doc_status"),
        Index("ix_pcv_auto_status", "auto_prepared", "doc_status"),
    )



    def __repr__(self) -> str:
        return f"<PeriodClosingVoucher code={self.code} year={self.closing_fiscal_year_id} status={self.doc_status}>"
# ──────────────────────────────────────────────────────────────────────────────
# 3) COST CENTER
# ──────────────────────────────────────────────────────────────────────────────
class CostCenter(BaseModel):
    """
    Frappe-style Cost Center: enable/disable instead of docstatus.
    """
    __tablename__ = "cost_centers"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id"), nullable=False, index=True
    )

    # Core fields
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)


    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    # Relationships
    journal_entry_items: Mapped[List["JournalEntryItem"]] = relationship(
        back_populates="cost_center", cascade="all, delete-orphan"
    )
    general_ledger_entries: Mapped[List["GeneralLedgerEntry"]] = relationship(
        back_populates="cost_center", cascade="all, delete-orphan"
    )
    company: Mapped["Company"] = relationship(back_populates="cost_centers")
    branch: Mapped["Branch"] = relationship(back_populates="cost_centers")

    expenses: Mapped[List["Expense"]] = relationship(back_populates="cost_center")
    expense_items: Mapped[List["ExpenseItem"]] = relationship(back_populates="cost_center")

    __table_args__ = (
        # keep your original uniqueness rule; consider tightening later if needed
        UniqueConstraint("company_id", "branch_id", "name", name="uq_cost_center_company_branch_name"),
        Index("ix_cost_center_company_branch", "company_id", "branch_id"),
    )

    def __repr__(self) -> str:
        return f"<CostCenter name={self.name!r} enabled={self.enabled}>"


# ──────────────────────────────────────────────────────────────────────────────
# 4) CHART OF ACCOUNTS (The General Ledger)
# ──────────────────────────────────────────────────────────────────────────────
class Account(BaseModel):
    """
    Represents a single account in the General Ledger.
    """
    __tablename__ = "accounts"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    parent_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"),
                                                             nullable=True, index=True)

    # Core Fields
    code: Mapped[str] = mapped_column(db.String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    account_type: Mapped[AccountTypeEnum] = mapped_column(db.Enum(AccountTypeEnum),
                                                          nullable=False, index=True)
    report_type: Mapped[ReportTypeEnum] = mapped_column(db.Enum(ReportTypeEnum),
                                                        nullable=False, index=True)
    is_group: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    debit_or_credit: Mapped[DebitOrCreditEnum] = mapped_column(db.Enum(DebitOrCreditEnum), nullable=False)
    # status: Mapped[DocStatusEnum] = mapped_column(
    #     db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    # )
    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)


    # Relationships
    company: Mapped["Company"] = db.relationship(
        "Company",
        back_populates="accounts",
        foreign_keys=[company_id]
    )
    parent_account: Mapped[Optional["Account"]] = relationship(
        remote_side="Account.id", back_populates="child_accounts"
    )
    child_accounts: Mapped[List["Account"]] = relationship(
        back_populates="parent_account", cascade="all, delete-orphan"
    )
    purchase_invoices_payable: Mapped[List["PurchaseInvoice"]] = relationship(
        "PurchaseInvoice", foreign_keys="[PurchaseInvoice.payable_account_id]", back_populates="payable_account"
    )
    purchase_invoices_cash_bank: Mapped[List["PurchaseInvoice"]] = relationship(
        "PurchaseInvoice", foreign_keys="[PurchaseInvoice.cash_bank_account_id]", back_populates="cash_bank_account"
    )
    stock_reconciliations: Mapped[List["StockReconciliation"]] = relationship(
        "StockReconciliation",
        foreign_keys="[StockReconciliation.difference_account_id]",
        back_populates="difference_account"
    )
    journal_entry_items: Mapped[List["JournalEntryItem"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    general_ledger_entries: Mapped[List["GeneralLedgerEntry"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    sales_invoices_vat: Mapped[List["SalesInvoice"]] = relationship(
        "SalesInvoice",
        foreign_keys="[SalesInvoice.vat_account_id]",
        back_populates="vat_account"
    )
    sales_invoices_cash_bank: Mapped[List["SalesInvoice"]] = relationship(
        "SalesInvoice",
        foreign_keys="[SalesInvoice.cash_bank_account_id]",
        back_populates="cash_bank_account"
    )
    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_account_company_code"),
        Index("ix_account_company_type", "company_id", "account_type"),
        Index("ix_account_enabled", "company_id", "enabled"),
    )

    def __repr__(self) -> str:
        return f"<Account code={self.code!r} name={self.name!r}>"


# ──────────────────────────────────────────────────────────────────────────────
# 5) ACCOUNT BALANCE
# ──────────────────────────────────────────────────────────────────────────────
class AccountBalance(BaseModel):
    """
    Stores the current aggregated balance for each detail account.
    This table is updated whenever a transaction affects an account,
    providing a cached balance for quick retrieval, especially for reports
    and tree views.
    """
    __tablename__ = "account_balances"

    # Foreign Keys
    account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Core Fields
    total_debit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    total_credit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    current_balance: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships
    account: Mapped["Account"] = relationship(backref="account_balance_entry", uselist=False)

    __table_args__ = (
        UniqueConstraint("account_id", name="uq_account_balance_account_id"),
    )

    def __repr__(self) -> str:
        return f"<AccountBalance AccountID={self.account_id} Balance={self.current_balance}>"


# ──────────────────────────────────────────────────────────────────────────────
# 6) PARTY ACCOUNT BALANCE
# ──────────────────────────────────────────────────────────────────────────────
class PartyAccountBalance(BaseModel):
    """
    Tracks the balance of a specific party (e.g., Customer, Supplier) against an account.
    Essential for Accounts Receivable and Accounts Payable.
    """
    __tablename__ = "party_account_balances"

    # Foreign Keys
    account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"),
                                            nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(db.BigInteger, nullable=False, index=True)
    party_type: Mapped[PartyTypeEnum] = mapped_column(db.Enum(PartyTypeEnum), nullable=False)

    # Core Fields
    total_debit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    total_credit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    current_balance: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships
    account: Mapped["Account"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("account_id", "party_id", "party_type", name="uq_pab_account_party"),
    )

    def __repr__(self) -> str:
        return f"<PartyAccountBalance id={self.id} party_id={self.party_id} balance={self.current_balance}>"


# ──────────────────────────────────────────────────────────────────────────────
# 7) JOURNAL ENTRY
# ──────────────────────────────────────────────────────────────────────────────
class JournalEntry(BaseModel):
    """
    A single financial document containing debits and credits.
    The total of all debits must equal the total of all credits.
    """
    __tablename__ = "journal_entries"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    fiscal_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("fiscal_years.id"),
                                                nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    source_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("document_types.id"),
        nullable=True, index=True
    )

    # Core Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_debit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    total_credit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    entry_type: Mapped[JournalEntryTypeEnum] = mapped_column(db.Enum(JournalEntryTypeEnum),
                                                             nullable=False, index=True)
    is_auto_generated: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    source_doc_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)

    # Relationships
    # Relationships
    items: Mapped[List["JournalEntryItem"]] = relationship(
        back_populates="journal_entry", cascade="all, delete-orphan"
    )
    general_ledger_entries: Mapped[List["GeneralLedgerEntry"]] = relationship(
        back_populates="journal_entry", cascade="all, delete-orphan"
    )
    company: Mapped["Company"] = relationship(back_populates="journal_entries")
    branch: Mapped["Branch"] = relationship(back_populates="journal_entries")
    fiscal_year: Mapped["FiscalYear"] = relationship(back_populates="journal_entries")
    created_by: Mapped["User"] = relationship(
        back_populates="created_journal_entries",
        foreign_keys=[created_by_id]
    )
    source_doctype: Mapped["DocumentType"] = relationship()
    payments: Mapped[List["PaymentEntry"]] = relationship(
        back_populates="journal_entry"
    )
    expenses: Mapped[List["Expense"]] = relationship(
        back_populates="journal_entry"
    )
    period_closing_vouchers: Mapped[List["PeriodClosingVoucher"]] = relationship(
        back_populates="generated_journal_entry",
        foreign_keys="PeriodClosingVoucher.generated_journal_entry_id"
    )


    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_je_company_branch_code"),
        CheckConstraint("total_debit = total_credit", name="ck_je_balance"),
        # Performance indexes
        Index("ix_je_company_date", "company_id", "posting_date"),
        Index("ix_je_fy_status", "fiscal_year_id", "doc_status"),
        Index("ix_je_entry_type", "entry_type", "posting_date"),
    )


    def __repr__(self) -> str:
        return f"<JournalEntry code={self.code} status={self.doc_status}>"


# ──────────────────────────────────────────────────────────────────────────────
# 8) JOURNAL ENTRY ITEM (The Line)
# ──────────────────────────────────────────────────────────────────────────────
class JournalEntryItem(BaseModel):
    """
    A single line item in a Journal Entry, representing a debit or a credit.
    """
    __tablename__ = "journal_entry_items"

    # Foreign Keys
    journal_entry_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"),
                                            nullable=False, index=True)
    cost_center_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("cost_centers.id"),
                                                          nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)
    party_type: Mapped[Optional[PartyTypeEnum]] = mapped_column(db.Enum(PartyTypeEnum), nullable=True)

    # Core Fields
    debit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    credit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    journal_entry: Mapped["JournalEntry"] = relationship(back_populates="items")
    account: Mapped["Account"] = relationship()
    cost_center: Mapped[Optional["CostCenter"]] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("debit = 0 OR credit = 0", name="ck_jei_is_debit_or_credit"),
        CheckConstraint("debit > 0 OR credit > 0", name="ck_jei_has_value"),
        Index("ix_jei_account_cc", "account_id", "cost_center_id"),
        Index("ix_jei_party", "party_id"),
    )

    def __repr__(self) -> str:
        return f"<JournalEntryItem id={self.id} account={self.account_id} debit={self.debit} credit={self.credit}>"


# ──────────────────────────────────────────────────────────────────────────────
# 9) GENERAL LEDGER ENTRY (The final, immutable record for reporting)
# ──────────────────────────────────────────────────────────────────────────────
class GeneralLedgerEntry(BaseModel):
    """
    This is the final, immutable ledger record for financial reporting.
    Every JournalEntryItem will create a corresponding GLE.
    """
    __tablename__ = "general_ledger_entries"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"),
                                            nullable=False, index=True)
    cost_center_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("cost_centers.id"),
                                                          nullable=True, index=True)
    fiscal_year_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("fiscal_years.id"),
                                                nullable=False, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)
    party_type: Mapped[Optional[PartyTypeEnum]] = mapped_column(db.Enum(PartyTypeEnum), nullable=True)
    journal_entry_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("journal_entries.id"),
                                                  nullable=False, index=True)
    source_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("document_types.id"),
        nullable=True, index=True
    )
    source_doc_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)

    # Core Fields
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    debit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    credit: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    is_auto_generated: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    entry_type: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    # Relationships
    account: Mapped["Account"] = relationship(back_populates="general_ledger_entries")
    cost_center: Mapped[Optional["CostCenter"]] = relationship(back_populates="general_ledger_entries")
    journal_entry: Mapped["JournalEntry"] = relationship(back_populates="general_ledger_entries")
    source_doctype: Mapped["DocumentType"] = relationship()
    fiscal_year: Mapped["FiscalYear"] = relationship(back_populates="general_ledger_entries")
    company: Mapped["Company"] = relationship(back_populates="general_ledger_entries")
    branch: Mapped["Branch"] = relationship(back_populates="general_ledger_entries")

    # Table Constraints & Indices
    __table_args__ = (
        Index("ix_gle_company_account", "company_id", "account_id"),
        Index("ix_gle_company_account_fy_date", "company_id", "account_id", "fiscal_year_id", "posting_date"),
        Index("ix_gle_company_cc", "company_id", "cost_center_id"),
        Index("ix_gle_company_party", "company_id", "party_id"),
        Index("ix_gle_company_posting_date", "company_id", "posting_date"),
        Index("ix_gle_fy_account", "fiscal_year_id", "account_id"),  # ADDED
        Index("ix_gle_debit_credit", "debit", "credit"),  # ADDED
    )

    def __repr__(self) -> str:
        return f"<GeneralLedgerEntry id={self.id} account={self.account_id} debit={self.debit}>"


# ──────────────────────────────────────────────────────────────────────────────
# 10) GENERAL LEDGER ENTRY TEMPLATE (The Accounting Rules)
# ──────────────────────────────────────────────────────────────────────────────
class GLEntryTemplate(BaseModel):
    """
    Defines the standard accounting rules for a specific DocumentType.
    This replaces the need for TransactionName and TransactionType.
    A single document type (e.g., 'Sales Invoice') can have a primary
    template and optional special templates (e.g., for returns).
    """
    __tablename__ = "gl_entry_templates"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True,
        comment='The company this template belongs to. Allows for company-specific rules.'
    )
    source_doctype_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("document_types.id"), nullable=False, index=True,
        comment='The specific business document type (e.g., Sales Invoice) this template applies to.'
    )

    # Core Fields
    code: Mapped[str] = mapped_column(
        db.String(100), nullable=False, index=True,
        comment='A unique, programmatic code for this template (e.g., "SALES_INV_DEFAULT").'
    )
    label: Mapped[str] = mapped_column(
        db.String(255), nullable=False,
        comment='A human-readable label for the template (e.g., "Standard Sales Invoice Template").'
    )
    description: Mapped[Optional[str]] = mapped_column(
        db.Text,
        comment='A detailed description of the template and its purpose.'
    )
    is_active: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=True,
        comment='Indicates if this template is currently active and can be used.'
    )
    is_primary: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, index=True,
        comment='Indicates if this is the default template for its source document type.'
    )

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="gl_entry_templates")
    source_doctype: Mapped["DocumentType"] = relationship()
    template_items: Mapped[List["GLTemplateItem"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # code uniqueness within (company, doctype)
        UniqueConstraint(
            "company_id", "source_doctype_id", "code",
            name="uq_glt_company_doctype_code"
        ),

        Index(
            "uq_glt_company_doctype_primary",
            "company_id", "source_doctype_id",
            unique=True,
            postgresql_where=text("is_primary = true")
        ),
    )

    def __repr__(self) -> str:
        return f"<GLEntryTemplate code={self.code!r} doctype={self.source_doctype_id}>"

# ──────────────────────────────────────────────────────────────────────────────
# 11) GL ENTRY TEMPLATE ITEM (The Rule Line)
# ──────────────────────────────────────────────────────────────────────────────
class  GLTemplateItem(BaseModel):
    """
    A single debit or credit rule within a GLEntryTemplate.
    This defines the account to debit/credit and the source of the amount.
    """
    __tablename__ = "gl_template_items"

    # Foreign Keys
    template_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("gl_entry_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment='The ID of the GLEntryTemplate this rule belongs to.'
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment='The static Chart of Account affected by this rule. Can be NULL if requires_dynamic_account is true.'
    )

    # Core Fields
    sequence: Mapped[int] = mapped_column(
        db.Integer, nullable=False,
        comment='The order in which this rule should be processed within the template.'
    )
    effect: Mapped[DebitOrCreditEnum] = mapped_column(
        db.Enum(DebitOrCreditEnum), nullable=False,
        comment='Indicates whether this rule is for a Debit or a Credit.'
    )
    amount_source: Mapped[str] = mapped_column(
        db.String(100), nullable=False,
        comment='A string key (e.g., "DOCUMENT_TOTAL", "TAX_AMOUNT") used to find the amount from the source document payload.'
    )
    is_required: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=True,
        comment='Whether this rule must be present for a transaction to be valid.'
    )
    requires_dynamic_account: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False,
        comment='If true, the account is not fixed and must be determined dynamically at runtime.'
    )
    context_key: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        comment='A key used to look up the dynamic account ID from the source document payload (e.g., "customer_ar_account").'
    )

    # Relationships
    template: Mapped["GLEntryTemplate"] = relationship(back_populates="template_items")
    account: Mapped[Optional["Account"]] = relationship()
    __table_args__ = (
        # For ordering
        Index("ix_glti_template_seq", "template_id", "sequence"),
        # ❗ Partial unique index to prevent duplicate static lines on a template.
        #    (Only enforced when requires_dynamic_account = false)
        Index(
            "uq_glti_rule_on_template",
            "template_id", "account_id", "effect",
            unique=True,
            postgresql_where=text("requires_dynamic_account = false")
        ),
        # Optional but helpful integrity checks:
        CheckConstraint("sequence > 0", name="ck_glti_sequence_pos"),
        CheckConstraint(
            "(requires_dynamic_account = false AND account_id IS NOT NULL) "
            "OR (requires_dynamic_account = true AND account_id IS NULL)",
            name="ck_glti_account_dynamic_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<GLTemplateItem id={self.id} effect={self.effect} source={self.amount_source}>"
class AccountingSettings(BaseModel):
    __tablename__ = "accounting_settings"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Example ERP-style defaults
    default_receivable_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True
    )
    default_payable_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True
    )
    allow_negative_stock: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False
    )

    company: Mapped["Company"] = relationship(
        back_populates="accounting_settings"
    )

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_accounting_settings_company"),
    )

    def __repr__(self) -> str:
        return f"<AccountingSettings company_id={self.company_id}>"