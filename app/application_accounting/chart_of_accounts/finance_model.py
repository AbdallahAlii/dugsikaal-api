from __future__ import annotations
from typing import Optional, List
from datetime import datetime, date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, text, Numeric, String, Text, Boolean
import enum
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.application_stock.stock_models import DocStatusEnum
from config.database import db
from app.common.models.base import BaseModel


# ──────────────────────────────────────────────────────────────────────────────
# COMMON ENUMS
# ──────────────────────────────────────────────────────────────────────────────
class PaymentTypeEnum(str, enum.Enum):
    PAY = "PAY"
    RECEIVE = "RECEIVE"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"




# ──────────────────────────────────────────────────────────────────────────────
# Payment (Header) - Clean Frappe/ERPNext Style
# ──────────────────────────────────────────────────────────────────────────────
class PaymentEntry(BaseModel):
    """
    Stores the header information for a payment transaction.
    This corresponds to ERPNext's "Payment Entry" DocType.
    """
    __tablename__ = "payment_entries"

    # === Document Identification ===
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment="Unique document code (e.g., PE-2025-00001)")
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True)

    # === Core Payment Details ===
    payment_type: Mapped[PaymentTypeEnum] = mapped_column(db.Enum(PaymentTypeEnum), nullable=False, index=True, comment="Indicates if this is a payment, receipt, or internal transfer")
    posting_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True, comment="The date the transaction will be posted to the ledger")
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True)

    # === Party Details (Customer, Supplier, etc.) ===
    party_type: Mapped[Optional[PartyTypeEnum]] = mapped_column(db.Enum(PartyTypeEnum), nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True, comment="The specific customer, supplier, etc.")

    # === Core Accounting Accounts ===
    # For PAY/RECEIVE, this is the company's Bank or Cash account.
    # For INTERNAL_TRANSFER, this is the source account.
    paid_from_account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True, comment="Company's Bank/Cash account (Source)")
    # For PAY/RECEIVE, this is the Party's ledger account (e.g., Debtors, Creditors).
    # For INTERNAL_TRANSFER, this is the target account.
    paid_to_account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True, comment="Party's ledger or Target Bank/Cash account")

    # === Amounts & Allocation ===
    paid_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0.0)
    allocated_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0.0, comment="Sum of allocated amounts from child table")
    unallocated_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0.0, index=True, comment="Difference between paid and allocated amounts")

    # === Payment Instrument Details (e.g., Check, Bank Transfer) ===
    reference_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True, comment="E.g., Check number, bank transaction ID")
    reference_date: Mapped[Optional[date]] = mapped_column(db.Date, nullable=True, index=True)

    # === Additional Info ===
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    journal_entry_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("journal_entries.id"), nullable=True, index=True)

    # === Relationships ===
    company: Mapped["Company"] = relationship(back_populates="payment_entries")
    branch: Mapped["Branch"] = relationship(back_populates="payment_entries")
    created_by: Mapped["User"] = relationship(back_populates="created_payment_entries", foreign_keys=[created_by_id])
    paid_from_account: Mapped["Account"] = relationship(foreign_keys=[paid_from_account_id])
    paid_to_account: Mapped["Account"] = relationship(foreign_keys=[paid_to_account_id])

    mode_of_payment = relationship("ModeOfPayment")
    journal_entry: Mapped[Optional["JournalEntry"]] = relationship(back_populates="payments")
    # child allocation rows
    items: Mapped[List["PaymentItem"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )

    # === Constraints & Indices ===
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_payment_entry_company_code"),
        Index("ix_payment_entry_party", "party_type", "party_id"),
        Index("ix_payment_entry_type_date", "payment_type", "posting_date"),
        Index("ix_payment_entry_company_posting", "company_id", "posting_date"),
        Index("ix_payment_entry_paid_from", "paid_from_account_id"),
        CheckConstraint("paid_amount >= 0", name="ck_payment_paid_amount_non_negative"),
        # Internal transfer cannot have same source/target
        CheckConstraint(
            "(payment_type <> 'INTERNAL_TRANSFER') OR (paid_from_account_id <> paid_to_account_id)",
            name="ck_payment_internal_transfer_accounts"
        ),
        # Party integrity: either both NULL or both NOT NULL
        CheckConstraint(
            "(party_type IS NULL AND party_id IS NULL) OR (party_type IS NOT NULL AND party_id IS NOT NULL)",
            name="ck_payment_party_pair_integrity"
        ),
    )

    def __repr__(self) -> str:
        return f"<PaymentEntry {self.code} {self.payment_type} Amount: {self.paid_amount}>"



# ──────────────────────────────────────────────────────────────────────────────
# PaymentItem (Allocations) - Clean Frappe Style
# ──────────────────────────────────────────────────────────────────────────────

class PaymentItem(BaseModel):
    __tablename__ = "payment_items"

    # parent FK
    payment_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("payment_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Reference to a document
    source_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("document_types.id"), nullable=True, index=True
    )
    source_doc_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, nullable=True, index=True, comment="PK of referenced doc (fast integer lookup)"
    )

    # amount actually allocated to this reference (keep this)
    allocated_amount: Mapped[float] = mapped_column(
        Numeric(18, 6), nullable=False, default=0.0, comment="Amount applied to this reference"
    )


    # relationships (optional convenience)
    payment: Mapped["PaymentEntry"] = relationship(back_populates="items")
    source_doctype: Mapped["DocumentType"] = relationship()

    __table_args__ = (
        Index("idx_payment_item_source", "source_doctype_id", "source_doc_id"),  # fast lookup by (doctype, id)
        Index("ix_payment_item_payment", "payment_id"),
        CheckConstraint("allocated_amount >= 0", name="ck_payment_item_amount_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<PaymentItem {self.source_doctype_id}:{self.source_doc_id} {self.allocated_amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# Expense (Header)
# ──────────────────────────────────────────────────────────────────────────────
class Expense(BaseModel):
    """
    Expense claim or direct expense document.
    Following Frappe/ERPNext pattern with proper accounting.
    """
    __tablename__ = "expenses"

    # === Document Identification ===
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True,
                                      comment="Unique document code (e.g., EXP-2025-00001)")
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False,
                                                      default=DocStatusEnum.DRAFT, index=True)

    # === Core Expense Details ===
    posting_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True,
                                               comment="The date the expense was incurred")

    # === Amount ===
    total_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0.0)

    # === Cost Center ===
    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("cost_centers.id"), nullable=True, index=True
    )

    # === Additional Info ===
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)

    # === Journal Entry Link ===
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id"), nullable=True, index=True
    )

    # === Relationships ===
    company: Mapped["Company"] = relationship(back_populates="expenses")
    branch: Mapped["Branch"] = relationship(back_populates="expenses")
    created_by: Mapped["User"] = relationship(back_populates="created_expenses", foreign_keys=[created_by_id])
    cost_center: Mapped[Optional["CostCenter"]] = relationship(back_populates="expenses")
    journal_entry: Mapped[Optional["JournalEntry"]] = relationship(back_populates="expenses")

    # child expense items
    items: Mapped[List["ExpenseItem"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )

    # === Constraints & Indices ===
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_expense_branch_code"),
        Index("ix_expense_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_expense_date", "posting_date"),
        Index("ix_expense_company_posting", "company_id", "posting_date"),
        CheckConstraint("total_amount >= 0", name="ck_expense_amount_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Expense {self.code} Amount: {self.total_amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# ExpenseItem (Line Items) - Same Pattern as PaymentItem
# ──────────────────────────────────────────────────────────────────────────────
class ExpenseItem(BaseModel):
    """
    Individual expense line items following Frappe/ERPNext pattern.
    Each line represents a specific expense with proper accounting.
    """
    __tablename__ = "expense_items"

    # parent FK
    expense_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # === Expense Type and Accounts ===
    expense_type_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("expense_types.id"), nullable=True, index=True
    )
    account_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True,
        comment="Expense account (e.g., Travel Expenses, Office Supplies)"
    )
    paid_from_account_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True,
        comment="Cash/Bank account from which expense is paid"
    )

    # === Item Details ===
    description: Mapped[Optional[str]] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(
        Numeric(18, 6), nullable=False, default=0.0, comment="Amount for this expense line"
    )

    # === Cost Center (can override header) ===
    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("cost_centers.id"), nullable=True, index=True
    )

    # === Relationships ===
    expense: Mapped["Expense"] = relationship(back_populates="items")
    expense_type: Mapped[Optional["ExpenseType"]] = relationship(back_populates="expense_items")
    account: Mapped["Account"] = relationship(foreign_keys=[account_id])
    paid_from_account: Mapped["Account"] = relationship(foreign_keys=[paid_from_account_id])
    cost_center: Mapped[Optional["CostCenter"]] = relationship()

    # === Constraints & Indices ===
    __table_args__ = (
        Index("idx_expense_item_expense", "expense_id"),
        Index("idx_expense_item_accounts", "account_id", "paid_from_account_id"),
        Index("idx_expense_item_type", "expense_type_id"),
        CheckConstraint("amount > 0", name="ck_expense_item_amount_positive"),
    )

    def __repr__(self) -> str:
        return f"<ExpenseItem {self.expense_type_id} Amount: {self.amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# ExpenseType - Clean Frappe Style
# ──────────────────────────────────────────────────────────────────────────────
class ExpenseType(BaseModel):
    """
    Expense type categorization with default account mapping.
    Following Frappe/ERPNext pattern for master data.
    """
    __tablename__ = "expense_types"

    # === Company Context ===
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)

    # === Type Information ===
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True,
                                      comment="Expense type name (e.g., Travel, Office Supplies)")
    description: Mapped[Optional[str]] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # === Default Account ===
    default_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=True, index=True,
        comment="Default expense account for this type"
    )

    # === Relationships ===
    company: Mapped["Company"] = relationship(back_populates="expense_types")
    default_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[default_account_id])
    expense_items: Mapped[List["ExpenseItem"]] = relationship(back_populates="expense_type")

    # === Constraints & Indices ===
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_expense_type_company_name"),
        Index("ix_expense_type_enabled", "enabled"),
        CheckConstraint("name <> ''", name="ck_expense_type_name_non_empty"),
    )

    def __repr__(self) -> str:
        return f"<ExpenseType {self.name}>"