# app/application_accounting/account_policies.py
from __future__ import annotations

import enum
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Index, UniqueConstraint, CheckConstraint, text

from config.database import db
from app.common.models.base import BaseModel


class AccountUseRoleEnum(str, enum.Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    TRANSFER_SOURCE = "TRANSFER_SOURCE"
    TRANSFER_TARGET = "TRANSFER_TARGET"
    EXPENSE = "EXPENSE"


class AccountRuleTypeEnum(str, enum.Enum):
    DEFAULT = "DEFAULT"   # prefill
    ALLOW   = "ALLOW"     # whitelist
    BLOCK   = "BLOCK"     # (optional) blacklist to subtract from allow


class ModeOfPaymentTypeEnum(str, enum.Enum):
    CASH = "CASH"
    BANK = "BANK"
    MOBILE_MONEY = "MOBILE_MONEY"
    CREDIT_CARD = "CREDIT_CARD"
    OTHER = "OTHER"


class ModeOfPayment(BaseModel):
    """
    Defines a payment method and its relationship to multiple accounts and associated company/branch.
    """
    __tablename__ = "modes_of_payment"

    # ---- Company and Branch Association ----
    company_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"), nullable=True, index=True)

    # Mode of Payment Name, must be unique per company or branch
    name: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    # Mode of Payment type (CASH, BANK, MOBILE_MONEY, etc.)
    type: Mapped[ModeOfPaymentTypeEnum] = mapped_column(db.Enum(ModeOfPaymentTypeEnum), nullable=False)

    # Default account for this mode of payment (optional)
    default_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=True)

    # Flag to mark whether this mode of payment is active
    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    # ---- Relationships ----
    company = relationship("Company", back_populates="modes_of_payment")
    branch = relationship("Branch", back_populates="modes_of_payment")
    purchase_invoices: Mapped[List["PurchaseInvoice"]] = relationship(
        "PurchaseInvoice", back_populates="mode_of_payment"
    )
    sales_invoices: Mapped[List["SalesInvoice"]] = relationship(
        "SalesInvoice", back_populates="mode_of_payment"
    )
    # ---- Unique Constraint ----
    __table_args__ = (
        # UniqueConstraint ensures that the combination of company and branch with name is unique
        UniqueConstraint("name", "company_id", "branch_id", name="uq_mode_of_payment_name_company_branch"),

        # Index for performance optimization
        Index("idx_mop_type", "type"),
        Index("idx_mop_default_account", "default_account_id"),
        Index("idx_mop_company_id", "company_id"),
        Index("idx_mop_branch_id", "branch_id"),
    )

    def __repr__(self) -> str:
        return f"<ModeOfPayment {self.name} ({self.type.value}) for company_id={self.company_id} and branch_id={self.branch_id}>"

class AccountSelectionRule(BaseModel):
    """
    Unified rules for account selection:
      - DEFAULT: single prefilled account per scope/role/(optional MoP)
      - ALLOW:   one or many rows to define the allowed set
      - BLOCK:   optional rows to subtract from the allowed set
    Scope precedence at runtime: user > department > branch > company.
    """
    __tablename__ = "account_selection_rules"

    # ---- Scope
    company_id:  Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                             nullable=False, index=True)
    branch_id:   Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                                       nullable=True, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("departments.id"),
                                                         nullable=True, index=True)
    user_id:     Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                                       nullable=True, index=True)

    role:        Mapped["AccountUseRoleEnum"] = mapped_column(db.Enum(AccountUseRoleEnum),
                                                              nullable=False, index=True)
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True
    )

    # ---- Rule
    rule_type:   Mapped["AccountRuleTypeEnum"] = mapped_column(db.Enum(AccountRuleTypeEnum),
                                                               nullable=False, index=True)

    # Choose one of:
    account_id:       Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True
    )  # specific leaf account
    parent_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True
    )  # group; expands to its leaf accounts
    include_children: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    is_active:   Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    # (optional) eager relationships
    account = relationship("Account", foreign_keys=[account_id])
    parent_account = relationship("Account", foreign_keys=[parent_account_id])

    __table_args__ = (
        # Exactly ONE default per exact scope+role when MoP IS NULL
        Index(
            "uq_accrule_default_nomop",
            "company_id","branch_id","department_id","user_id","role",
            unique=True,
            postgresql_where=text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NULL")
        ),
        # Exactly ONE default per exact scope+role+MoP when MoP IS NOT NULL
        Index(
            "uq_accrule_default_mop",
            "company_id","branch_id","department_id","user_id","role","mode_of_payment_id",
            unique=True,
            postgresql_where=text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NOT NULL")
        ),
        # Prevent duplicate ALLOW rows (same scope/role/mop/account)
        Index(
            "uq_accrule_allow_account",
            "company_id","branch_id","department_id","user_id","role","mode_of_payment_id","account_id",
            unique=True,
            postgresql_where=text("rule_type = 'ALLOW' AND account_id IS NOT NULL")
        ),
        # Prevent duplicate ALLOW group-rows (same scope/role/mop/parent)
        Index(
            "uq_accrule_allow_parent",
            "company_id","branch_id","department_id","user_id","role","mode_of_payment_id","parent_account_id","include_children",
            unique=True,
            postgresql_where=text("rule_type = 'ALLOW' AND parent_account_id IS NOT NULL")
        ),
        # Similar uniques for BLOCK (optional) …
        CheckConstraint(
            # DEFAULT must reference a specific account (no parent/group)
            "(rule_type <> 'DEFAULT') OR (account_id IS NOT NULL AND parent_account_id IS NULL AND include_children = false)",
            name="ck_accrule_default_has_account_only"
        ),
        CheckConstraint(
            # For ALLOW/BLOCK you must choose either specific account or a parent group
            "(rule_type = 'DEFAULT') OR (account_id IS NOT NULL) OR (parent_account_id IS NOT NULL)",
            name="ck_accrule_allowblock_has_target"
        ),
    )

    def __repr__(self) -> str:
        scope = (self.company_id, self.branch_id, self.department_id, self.user_id)
        target = self.account_id or f"group:{self.parent_account_id}"
        return f"<AccountSelectionRule {self.rule_type} scope={scope} role={self.role} mop={self.mode_of_payment_id} -> {target}>"