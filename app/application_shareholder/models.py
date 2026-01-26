# app/application_shareholder/models.py
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    UniqueConstraint,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, StatusEnum
# NOTE: Company / JournalEntry / DocumentType are referenced by string
# in relationship() to avoid circular imports.


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class ShareholderCategoryEnum(str, enum.Enum):
    """
    Basic classification of shareholder nature.
    Keep it small – similar to ERPNext's simple categorization.
    """
    INDIVIDUAL = "Individual"
    COMPANY = "Company"
    GOVERNMENT = "Government"
    OTHER = "Other"


class ShareTransactionTypeEnum(str, enum.Enum):
    """
    Reason/type for a share movement.
    This is enough to model all real business cases:
      - ISSUE       → Company issues new shares to shareholder
      - TRANSFER_IN → Transfer coming into this shareholder
      - TRANSFER_OUT→ Transfer going out from this shareholder
      - REDEMPTION  → Company buys back / cancels shares
      - BONUS       → Bonus shares (no money but quantity increases)
      - ADJUSTMENT  → Manual corrections
    """
    ISSUE = "Issue"
    TRANSFER_IN = "Transfer In"
    TRANSFER_OUT = "Transfer Out"
    REDEMPTION = "Redemption"
    BONUS = "Bonus"
    ADJUSTMENT = "Adjustment"


# ──────────────────────────────────────────────────────────────────────────────
# 1) SHAREHOLDER MASTER
# ──────────────────────────────────────────────────────────────────────────────

class Shareholder(BaseModel):
    """
    Master record for a shareholder.
    This is the PARTY used when PartyTypeEnum == 'Shareholder'.

    Use this id (shareholder.id) as party_id in:
      - PartyAccountBalance
      - JournalEntryItem.party_id when party_type = 'Shareholder'
    """
    __tablename__ = "shareholders"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Like ERPNext's "Shareholder ID" (ACC-SH-0001 etc.)
    code: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        index=True,
        comment="Programmatic Shareholder ID (e.g. 'ACC-SH-0001').",
    )

    full_name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        index=True,
        comment="Legal/display name of the shareholder (person or entity).",
    )

    category: Mapped[ShareholderCategoryEnum] = mapped_column(
        db.Enum(ShareholderCategoryEnum),
        nullable=False,
        default=ShareholderCategoryEnum.INDIVIDUAL,
        index=True,
    )

    # Optional identifiers
    national_id: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        comment="National ID / passport for individuals.",
    )
    registration_no: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        comment="Registration number if shareholder is a company.",
    )

    # Contact info (keep minimal; later you can normalize via Contact/Address doctypes)
    contact_email: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        nullable=True,
        index=True,
    )
    contact_phone: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        nullable=True,
        index=True,
    )
    address: Mapped[Optional[str]] = mapped_column(
        db.Text,
        nullable=True,
        comment="Free-text mailing address.",
    )

    img_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        nullable=True,
        comment="Object-storage key/path for profile image or document scan.",
        index=True,
    )

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="shareholder_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="shareholders")
    share_ledger_entries: Mapped[List["ShareLedgerEntry"]] = relationship(
        back_populates="shareholder",
        cascade="all, delete-orphan",
    )
    # Emergency / next-of-kin contacts for this shareholder
    emergency_contacts: Mapped[List["ShareholderEmergencyContact"]] = relationship(
        "ShareholderEmergencyContact",
        back_populates="shareholder",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_shareholder_company_code",
        ),
        Index(
            "ix_shareholder_company_name",
            "company_id",
            "full_name",
        ),
        Index(
            "ix_shareholder_company_status",
            "company_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return f"<Shareholder id={self.id} code={self.code!r} name={self.full_name!r}>"

# ──────────────────────────────────────────────────────────────────────────────
# 1b) SHAREHOLDER EMERGENCY CONTACT
# ──────────────────────────────────────────────────────────────────────────────

class ShareholderEmergencyContact(BaseModel):
    """
    Emergency / next-of-kin contact for a shareholder.
    Namespaced to avoid clashing with employee emergency contacts.
    """
    __tablename__ = "shareholder_emergency_contacts"

    shareholder_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("shareholders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        comment="Name of the emergency contact person.",
    )

    phone: Mapped[Optional[str]] = mapped_column(
        db.String(50),
        nullable=False,
        comment="Phone number of the emergency contact.",
    )

    email: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        nullable=True,
        comment="Email of the emergency contact.",
    )

    relationship_to_shareholder: Mapped[Optional[str]] = mapped_column(
        db.String(100),
        nullable=True,
        comment="Relationship (e.g., spouse, family, lawyer).",
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    shareholder: Mapped["Shareholder"] = relationship(
        back_populates="emergency_contacts"
    )

    __table_args__ = (
        Index(
            "ix_sh_emergency_contact_shareholder",
            "shareholder_id",
            "name",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ShareholderEmergencyContact id={self.id} "
            f"shareholder_id={self.shareholder_id} name={self.name!r}>"
        )



# ──────────────────────────────────────────────────────────────────────────────
# 2) SHARE TYPE / CLASS
# ──────────────────────────────────────────────────────────────────────────────

class ShareType(BaseModel):
    """
    Definition of a share class for a company.

    Examples:
      - code: 'ORD', name: 'Ordinary Shares'
      - code: 'PREF-A', name: 'Preference Shares A'

    This is intentionally small: just enough to know what we're issuing
    and the nominal value per share.
    """
    __tablename__ = "share_types"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        db.String(50),
        nullable=False,
        index=True,
        comment="Short code (e.g. 'ORD', 'PREF-A').",
    )
    name: Mapped[str] = mapped_column(
        db.String(255),
        nullable=False,
        comment="Full name of the share class.",
    )

    nominal_value: Mapped[float] = mapped_column(
        db.Numeric(18, 4),
        nullable=False,
        default=0.0000,
        comment="Face value per share in company base currency.",
    )

    is_default: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="Marks the primary share class for the company.",
    )

    total_authorised_shares: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        nullable=True,
        comment="Authorised share capital (number of shares) for this class (optional).",
    )

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="share_type_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="share_types")
    share_ledger_entries: Mapped[List["ShareLedgerEntry"]] = relationship(
        back_populates="share_type",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "code",
            name="uq_share_type_company_code",
        ),
        Index(
            "ix_share_type_company_name",
            "company_id",
            "name",
        ),
        Index(
            "ix_share_type_company_status",
            "company_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return f"<ShareType id={self.id} code={self.code!r} name={self.name!r}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) SHARE LEDGER ENTRY (MOVEMENT OF SHARES)
# ──────────────────────────────────────────────────────────────────────────────

class ShareLedgerEntry(BaseModel):
    """
    Movement of shares for a shareholder.
    Think of this like the General Ledger for *share quantities*.

    - Positive quantity  = shares moving TO the shareholder.
    - Negative quantity  = shares moving OUT OF the shareholder.

    The *amount* field is the MONEY put in / taken out *for that share movement*
    (qty * rate). This is how you know how much capital the shareholder
    actually contributed or received for each transaction.
    """
    __tablename__ = "share_ledger_entries"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shareholder_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("shareholders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    share_type_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("share_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Effective date of this share movement.",
    )

    transaction_type: Mapped[ShareTransactionTypeEnum] = mapped_column(
        db.Enum(ShareTransactionTypeEnum),
        nullable=False,
        index=True,
        comment="Why this movement happened (Issue, Transfer, Redemption, etc.).",
    )

    quantity: Mapped[float] = mapped_column(
        db.Numeric(18, 6),
        nullable=False,
        comment="Positive for in; negative for out.",
    )
    rate: Mapped[float] = mapped_column(
        db.Numeric(18, 6),
        nullable=False,
        default=0,
        comment="Price per share in company base currency.",
    )
    amount: Mapped[float] = mapped_column(
        db.Numeric(18, 4),
        nullable=False,
        default=0,
        comment="Total value = quantity * rate. Capital added/removed for this movement.",
    )

    # Optional linkage back to accounting / business document
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("journal_entries.id"),
        nullable=True,
        index=True,
        comment="Related Journal Entry for capital injection, redemption, etc.",
    )
    source_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("document_types.id"),
        nullable=True,
        index=True,
    )
    source_doc_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        nullable=True,
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="share_ledger_entries")
    shareholder: Mapped["Shareholder"] = relationship(back_populates="share_ledger_entries")
    share_type: Mapped["ShareType"] = relationship(back_populates="share_ledger_entries")

    journal_entry: Mapped[Optional["JournalEntry"]] = relationship()
    source_doctype: Mapped[Optional["DocumentType"]] = relationship()

    __table_args__ = (
        CheckConstraint(
            "quantity <> 0",
            name="ck_sle_quantity_non_zero",
        ),
        Index(
            "ix_sle_company_shareholder",
            "company_id",
            "shareholder_id",
        ),
        Index(
            "ix_sle_company_sharetype",
            "company_id",
            "share_type_id",
        ),
        Index(
            "ix_sle_company_date",
            "company_id",
            "posting_date",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ShareLedgerEntry id={self.id} sh={self.shareholder_id} "
            f"type={self.transaction_type.value} qty={self.quantity}>"
        )
