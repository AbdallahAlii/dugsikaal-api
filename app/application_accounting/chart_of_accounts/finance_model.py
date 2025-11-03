# app/application_accounting/cashbank_models.py
from __future__ import annotations
from typing import Optional, List
from datetime import date
from decimal import Decimal
import enum

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    UniqueConstraint, Index, CheckConstraint, ForeignKey, String, Text, Numeric
)

from config.database import db
from app.common.models.base import BaseModel
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class PaymentTypeEnum(str, enum.Enum):
    PAY = "PAY"                   # We pay money OUT (to supplier, employee, shareholder, etc.)
    RECEIVE = "RECEIVE"           # We receive money IN (from customer, supplier refund, etc.)
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"  # Cash/bank → cash/bank


# ──────────────────────────────────────────────────────────────────────────────
# Payment Entry (Header) – ERPNext semantics
# ──────────────────────────────────────────────────────────────────────────────
class PaymentEntry(BaseModel):
    """
    ERPNext-compatible payment header.

    Semantics:
      * RECEIVE:
          - paid_from_account_id = Party ledger (e.g., 1131 Debtors for Customer, 2111 Creditors for Supplier refund)
          - paid_to_account_id   = Company's Cash/Bank (e.g., 1111/112x)
      * PAY:
          - paid_from_account_id = Company's Cash/Bank
          - paid_to_account_id   = Party ledger (e.g., 2111 Creditors for Supplier, 1131 Debtors for Customer refund)
      * INTERNAL_TRANSFER:
          - paid_from_account_id = Company's Cash/Bank (source)
          - paid_to_account_id   = Company's Cash/Bank (target)
          - party_type/party_id  MUST be NULL

    Allocation:
      * Use PaymentItem rows (like ERPNext "References") to apply amounts to Sales/ Purchase Invoices, JEs, etc.
      * `allocated_amount` on header should equal SUM(child.allocated_amount). Keep enforced in service layer.
    """
    __tablename__ = "payment_entries"

    # Identity
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    )

    # Core
    payment_type: Mapped[PaymentTypeEnum] = mapped_column(db.Enum(PaymentTypeEnum), nullable=False, index=True)
    posting_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)

    # Mode of payment
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True
    )

    # Party (optional for PAY/RECEIVE, forbidden for INTERNAL_TRANSFER)
    party_type: Mapped[Optional[PartyTypeEnum]] = mapped_column(db.Enum(PartyTypeEnum), nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)

    # Accounts (ERPNext semantics as described above)
    paid_from_account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=False,
                                                      index=True)
    paid_to_account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=False,
                                                    index=True)

    # Amounts
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0"),
        comment="Sum of child allocations (service layer must keep in sync)"
    )
    unallocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0"), index=True,
        comment="paid_amount - allocated_amount (service layer keeps in sync)"
    )

    # Instrument details
    reference_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    reference_date: Mapped[Optional[date]] = mapped_column(db.Date, nullable=True, index=True)

    # Misc
    remarks: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id"), nullable=True, index=True
    )

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="payment_entries")
    branch: Mapped["Branch"] = relationship(back_populates="payment_entries")
    created_by: Mapped["User"] = relationship(back_populates="created_payment_entries", foreign_keys=[created_by_id])
    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship()
    paid_from_account: Mapped["Account"] = relationship(foreign_keys=[paid_from_account_id])
    paid_to_account: Mapped["Account"] = relationship(foreign_keys=[paid_to_account_id])
    journal_entry: Mapped[Optional["JournalEntry"]] = relationship(back_populates="payments")

    items: Mapped[List["PaymentItem"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_payment_entry_branch_code"),
        Index("ix_payment_entry_party", "party_type", "party_id"),
        Index("ix_payment_entry_type_date", "payment_type", "posting_date"),
        Index("ix_payment_entry_company_posting", "company_id", "posting_date"),
        Index("ix_payment_entry_paid_from", "paid_from_account_id"),
        Index("ix_payment_entry_paid_to", "paid_to_account_id"),
        CheckConstraint("paid_amount >= 0", name="ck_payment_paid_amount_non_negative"),
        CheckConstraint("allocated_amount >= 0", name="ck_payment_alloc_non_negative"),
        CheckConstraint("unallocated_amount >= 0", name="ck_payment_unalloc_non_negative"),
        CheckConstraint("paid_amount >= allocated_amount", name="ck_payment_paid_ge_alloc"),
        CheckConstraint(
            # Internal transfer cannot involve party, and paid_from != paid_to.
            "("
            " (payment_type <> 'INTERNAL_TRANSFER') "
            " OR (party_type IS NULL AND party_id IS NULL)"
            ") AND (paid_from_account_id <> paid_to_account_id)",
            name="ck_payment_internal_transfer_rules"
        ),
        CheckConstraint("code <> ''", name="ck_payment_code_non_empty"),
    )

    def __repr__(self) -> str:
        return f"<PaymentEntry {self.code} {self.payment_type} paid={self.paid_amount}>"



# ──────────────────────────────────────────────────────────────────────────────
# PaymentItem (Allocations / References) – like ERPNext "References"
# ──────────────────────────────────────────────────────────────────────────────
class PaymentItem(BaseModel):
    """
    Allocation row. Mirrors ERPNext "Payment Entry Reference" concept.
    Each row applies part (or all) of this payment to a specific document (SI/PI/JE/etc.).
    """
    __tablename__ = "payment_items"

    payment_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("payment_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Referenced document (fast integer ids; your service layer knows doctype codes)
    source_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("document_types.id"), nullable=True, index=True
    )
    source_doc_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, nullable=True, index=True
    )

    # Amount allocated to that document
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))

    # Relationships
    payment: Mapped["PaymentEntry"] = relationship(back_populates="items")
    source_doctype: Mapped[Optional["DocumentType"]] = relationship()

    __table_args__ = (
        Index("idx_payment_item_source", "source_doctype_id", "source_doc_id"),
        Index("ix_payment_item_payment", "payment_id"),
        CheckConstraint("allocated_amount >= 0", name="ck_payment_item_amount_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<PaymentItem ref={self.source_doctype_id}:{self.source_doc_id} alloc={self.allocated_amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# Expense (Header)
# ──────────────────────────────────────────────────────────────────────────────
class Expense(BaseModel):
    """
    Direct expense document (non-AP route).
    ERPNext-style structure; JE generated on submit by service layer.
    """
    __tablename__ = "expenses"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    )

    posting_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)

    # Totals (service layer should keep in sync with child lines)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))

    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("cost_centers.id"), nullable=True, index=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)

    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id"), nullable=True, index=True
    )

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="expenses")
    branch: Mapped["Branch"] = relationship(back_populates="expenses")
    created_by: Mapped["User"] = relationship(back_populates="created_expenses", foreign_keys=[created_by_id])
    cost_center: Mapped[Optional["CostCenter"]] = relationship(back_populates="expenses")
    journal_entry: Mapped[Optional["JournalEntry"]] = relationship(back_populates="expenses")

    items: Mapped[List["ExpenseItem"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_expense_branch_code"),
        Index("ix_expense_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_expense_date", "posting_date"),
        Index("ix_expense_company_posting", "company_id", "posting_date"),
        CheckConstraint("total_amount >= 0", name="ck_expense_amount_non_negative"),
        CheckConstraint("code <> ''", name="ck_expense_code_non_empty"),
    )

    def __repr__(self) -> str:
        return f"<Expense {self.code} total={self.total_amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# ExpenseItem (Line)
# ──────────────────────────────────────────────────────────────────────────────
class ExpenseItem(BaseModel):
    """
    Individual expense lines:
      DR expense account, CR paid-from cash/bank (header-less JE style).
    """
    __tablename__ = "expense_items"

    expense_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Optional type master (can carry default account)
    expense_type_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("expense_types.id"), nullable=True, index=True
    )

    # Accounts per line (explicit, like ERPNext)
    account_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True,
        comment="Expense account (e.g., Travel, Office Supplies)"
    )
    paid_from_account_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True,
        comment="Cash/Bank account paying this line"
    )

    description: Mapped[Optional[str]] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0"))

    # Optional override for CC on the line
    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("cost_centers.id"), nullable=True, index=True
    )

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="items")
    expense_type: Mapped[Optional["ExpenseType"]] = relationship(back_populates="expense_items")
    account: Mapped["Account"] = relationship(foreign_keys=[account_id])
    paid_from_account: Mapped["Account"] = relationship(foreign_keys=[paid_from_account_id])
    cost_center: Mapped[Optional["CostCenter"]] = relationship()

    __table_args__ = (
        Index("idx_expense_item_expense", "expense_id"),
        Index("idx_expense_item_accounts", "account_id", "paid_from_account_id"),
        Index("idx_expense_item_type", "expense_type_id"),
        CheckConstraint("amount > 0", name="ck_expense_item_amount_positive"),
    )

    def __repr__(self) -> str:
        return f"<ExpenseItem amt={self.amount} acct={self.account_id}>"


# ──────────────────────────────────────────────────────────────────────────────
# ExpenseType (Master)
# ──────────────────────────────────────────────────────────────────────────────
class ExpenseType(BaseModel):
    """
    Master for expense categorization (can carry default account).
    """
    __tablename__ = "expense_types"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    default_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("accounts.id"), nullable=True, index=True
    )

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="expense_types")
    default_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[default_account_id])
    expense_items: Mapped[List["ExpenseItem"]] = relationship(back_populates="expense_type")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_expense_type_company_name"),
        Index("ix_expense_type_enabled", "enabled"),
        CheckConstraint("name <> ''", name="ck_expense_type_name_non_empty"),
    )

    def __repr__(self) -> str:
        return f"<ExpenseType {self.name}>"
