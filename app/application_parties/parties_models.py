from __future__ import annotations
from typing import Optional
import enum

from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


# --- Enums (No changes) ---
class PartyNatureEnum(str, enum.Enum):
    ORGANIZATION = "Organization"
    INDIVIDUAL = "Individual"


class PartyRoleEnum(str, enum.Enum):
    CUSTOMER = "Customer"
    SUPPLIER = "Supplier"


# --- Core Party Model ---
class Party(BaseModel):
    __tablename__ = "parties"

    # REFACTORED: Made company_id non-nullable. A party MUST belong to a company.
    company_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    nature: Mapped[PartyNatureEnum] = mapped_column(db.Enum(PartyNatureEnum), nullable=False, index=True)
    role: Mapped[PartyRoleEnum] = mapped_column(db.Enum(PartyRoleEnum), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(db.String(255))
    phone: Mapped[Optional[str]] = mapped_column(db.String(50))
    address_line1: Mapped[Optional[str]] = mapped_column(db.String(255))
    city_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("cities.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    is_cash_party: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(db.Text)
    img_key: Mapped[Optional[str]] = mapped_column(db.String(512), index=True)
    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE, index=True
    )

    org_details: Mapped[Optional["PartyOrganizationDetail"]] = relationship(
        back_populates="party", uselist=False, cascade="all, delete-orphan"
    )
    commercial_policy: Mapped[Optional["PartyCommercialPolicy"]] = relationship(
        back_populates="party", uselist=False, cascade="all, delete-orphan"
    )
    city: Mapped[Optional["City"]] = relationship(backref="parties", lazy="select")

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_party_company_code"),
        # NOTE: All indexes are good. No changes needed here.
        Index("ix_parties_company_id", "company_id"),
        Index("ix_parties_code", "code"),
        Index("ix_parties_role_type", "role"),
        Index("ix_party_company_role_name_ci", "company_id", "role", func.lower(name)),
        Index("ix_party_company_role_phone", "company_id", "role", "phone"),
        Index("ix_party_company_branch_role", "company_id", "branch_id", "role"),
        Index("ix_parties_company_role_name", "company_id", "role", "name"),
        # REFACTORED: Removed invalid CheckConstraint that referenced a relationship.
        # This logic is now correctly handled in the service layer.
    )

    def __repr__(self) -> str:
        return f"<Party id={self.id} company={self.company_id} role={self.role} code={self.code!r}>"


# --- Detail Models ---
class PartyOrganizationDetail(BaseModel):
    __tablename__ = "party_organization_details"

    party_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    org_company_name: Mapped[Optional[str]] = mapped_column(db.String(255), index=True)
    org_branch_name: Mapped[Optional[str]] = mapped_column(db.String(255), index=True)
    org_contact_name: Mapped[Optional[str]] = mapped_column(db.String(255), index=True)
    org_contact_phone: Mapped[Optional[str]] = mapped_column(db.String(50))
    org_contact_email: Mapped[Optional[str]] = mapped_column(db.String(255))

    # REFACTORED: Removed redundant city_id. The main Party model is the single source of truth for address.

    party: Mapped["Party"] = relationship(back_populates="org_details")

    __table_args__ = (
        Index("ix_party_org_details_party_id", "party_id"),
        Index("ix_party_org_details_orgco_ci", func.lower(org_company_name)),
        Index("ix_party_org_details_orgbr_ci", func.lower(org_branch_name)),
        Index("ix_party_org_details_contact_ci", func.lower(org_contact_name)),
    )

    def __repr__(self) -> str:
        return f"<PartyOrganizationDetail party_id={self.party_id}>"


class PartyCommercialPolicy(BaseModel):
    __tablename__ = "party_commercial_policies"

    company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    party_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("parties.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    allow_credit: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    credit_limit: Mapped[float] = mapped_column(db.Numeric(14, 2), nullable=False, default=0)

    party: Mapped["Party"] = relationship(back_populates="commercial_policy")

    __table_args__ = (
        Index("ix_party_commercial_policies_company_id", "company_id"),
        CheckConstraint("allow_credit = true OR credit_limit = 0", name="ck_allow_credit_or_zero_limit")
    )

    def __repr__(self) -> str:
        return f"<PartyCommercialPolicy party_id={self.party_id} credit_limit={self.credit_limit}>"