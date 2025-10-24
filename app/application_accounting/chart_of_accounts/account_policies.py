# app/application_accounting/mode_of_payment.py
from __future__ import annotations

import enum
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    Index, UniqueConstraint, CheckConstraint, ForeignKey,
    String, Boolean, text
)
from config.database import db
from app.common.models.base import BaseModel


# ───────────────────────── Enums ─────────────────────────
class ModeOfPaymentTypeEnum(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    MOBILE_MONEY = "MOBILE_MONEY"
    CREDIT_CARD = "CREDIT_CARD"
    OTHER = "OTHER"


class AccountUseRoleEnum(str, enum.Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    TRANSFER_SOURCE = "TRANSFER_SOURCE"
    TRANSFER_TARGET = "TRANSFER_TARGET"
    EXPENSE = "EXPENSE"


# ───────────────────── Mode of Payment (ERPNext-style) ────────────────────
class ModeOfPayment(BaseModel):
    """Company-scoped payment method. Keep it simple like ERPNext."""
    __tablename__ = "modes_of_payment"

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    type: Mapped[ModeOfPaymentTypeEnum] = mapped_column(db.Enum(ModeOfPaymentTypeEnum), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Relationships
    company = relationship("Company", back_populates="modes_of_payment")
    accounts: Mapped[List["ModeOfPaymentAccount"]] = relationship(
        back_populates="mode_of_payment", cascade="all, delete-orphan"
    )
    access_policies: Mapped[List["AccountAccessPolicy"]] = relationship(
        back_populates="mode_of_payment", cascade="all, delete-orphan"
    )
    purchase_invoices: Mapped[List["PurchaseInvoice"]] = relationship(
        "PurchaseInvoice",
        back_populates="mode_of_payment"
    )
    sales_invoices: Mapped[List["SalesInvoice"]] = relationship(
        "SalesInvoice", back_populates="mode_of_payment"
    )


    payment_entries: Mapped[List["PaymentEntry"]] = relationship(
        "PaymentEntry", back_populates="mode_of_payment"
    )
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_mop_company_name"),
        Index("ix_mop_company_enabled", "company_id", "enabled"),
        Index("ix_mop_company_type", "company_id", "type"),
    )

    def __repr__(self) -> str:
        return f"<MoP {self.name} ({self.type.value}) co={self.company_id}>"


# ───────────────────── Mode of Payment Account (company-scope only) ────────────────────
class ModeOfPaymentAccount(BaseModel):
    """
    Company-scoped MoP→Account links (+ one company default).
    No user/branch/department here — visibility lives in AccountAccessPolicy.
    """
    __tablename__ = "mode_of_payment_accounts"

    mode_of_payment_id: Mapped[int] = mapped_column(
        ForeignKey("modes_of_payment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # company_id is implicit via ModeOfPayment; fetch it by join when needed

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    mode_of_payment = relationship("ModeOfPayment", back_populates="accounts")
    account = relationship("Account")

    __table_args__ = (
        # One default per MoP (only on enabled rows)
        Index(
            "uq_mopa_default_per_mop",
            "mode_of_payment_id",
            unique=True,
            postgresql_where=text("is_default = true AND enabled = true")
        ),
        # Prevent duplicate links
        UniqueConstraint("mode_of_payment_id", "account_id", name="uq_mopa_mop_account"),
        Index("ix_mopa_enabled_probe", "mode_of_payment_id", "enabled"),
    )

    def __repr__(self) -> str:
        flag = " default" if self.is_default else ""
        return f"<MoPAccount mop={self.mode_of_payment_id} acct={self.account_id}{flag}>"


# ───────────────────── Account Access Policy (ALLOW-only) ────────────────────
class AccountAccessPolicy(BaseModel):
    """
    ALLOW-only whitelist per MoP + Role with scope precedence:
      user > department > branch > company (all NULL scope = company-wide).

    Resolver summary:
      1) candidate = enabled ModeOfPaymentAccount rows for the MoP
      2) if any policy exists for (company, mop, role):
            allowed = union of policy.account_id at the HIGHEST matching scope
            allowed = allowed ∩ candidate
         else:
            allowed = candidate
      3) default = the MoP’s company default if it is in allowed (else None)
    """
    __tablename__ = "account_access_policies"

    mode_of_payment_id: Mapped[int] = mapped_column(
        ForeignKey("modes_of_payment.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    role: Mapped[AccountUseRoleEnum] = mapped_column(db.Enum(AccountUseRoleEnum), nullable=False, index=True)

    # choose at most one scope (all NULL = company-wide)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)

    # Whitelisted account
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)

    # Toggle
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Relationships
    mode_of_payment = relationship("ModeOfPayment", back_populates="access_policies")
    company = relationship("Company")
    account = relationship("Account")
    user = relationship("User")
    department = relationship("Department")
    branch = relationship("Branch")

    __table_args__ = (
        # Partial unique while enabled (lets you keep disabled history rows)
        Index(
            "uq_aap_unique_policy_enabled",
            "mode_of_payment_id", "company_id", "role",
            "user_id", "department_id", "branch_id", "account_id",
            unique=True,
            postgresql_where=text("enabled = true")
        ),
        # Fast “is this MoP restricted for this role?” probe
        Index("ix_aap_probe", "company_id", "mode_of_payment_id", "role", "enabled"),
        # Portable “only one scope” guard (works beyond Postgres)
        CheckConstraint(
            "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN department_id IS NULL THEN 0 ELSE 1 END)"
            " + (CASE WHEN branch_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_aap_one_scope"
        ),
    )

    def __repr__(self) -> str:
        scope = (
            f"user={self.user_id}" if self.user_id else
            f"dept={self.department_id}" if self.department_id else
            f"branch={self.branch_id}" if self.branch_id else
            "company"
        )
        return f"<AccessPolicy {scope} mop={self.mode_of_payment_id} role={self.role} -> acct={self.account_id}>"
