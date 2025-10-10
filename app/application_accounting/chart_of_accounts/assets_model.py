# app/application_accounting/assets/model.py

from __future__ import annotations

from typing import Optional, List
from datetime import datetime, date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, Enum, ForeignKey
from app.common.models.base import BaseModel
from config.database import db


# Assuming these imports exist or are defined elsewhere:
# from app.application_buying.models import PurchaseInvoice
# from app.master_data.models import Item
# from app.application_accounting.chart_of_accounts.model import Account, CostCenter


# ──────────────────────────────────────────────────────────────────────────────
# 1) ASSET CATEGORY MODEL (The Rulebook)
# ──────────────────────────────────────────────────────────────────────────────
class AssetCategory(BaseModel):
    """
    Categorizes fixed assets for proper accounting, depreciation, and management.
    Defines the default GL accounts and depreciation rules for a class of assets.
    """
    __tablename__ = "asset_categories"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)

    # Core Fields
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(db.String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    # ------------------ Accounting Links (MANDATORY) ------------------
    fixed_asset_account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True,
        comment='The GL account (Asset) to Debit upon acquisition (e.g., 1212 Office Equipment).'
    )
    accumulated_depreciation_account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True,
        comment='The GL account (Contra-Asset) to Credit for depreciation (e.g., 1230 Acc. Depr.).'
    )
    depreciation_expense_account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True,
        comment='The GL account (Expense) to Debit for depreciation (e.g., 5119 Depr. Expense).'
    )
    # ------------------------------------------------------------------

    # Depreciation Settings (Minimal necessary fields)
    depreciation_method: Mapped[str] = mapped_column(db.String(50), nullable=False, default="Straight Line",
                                                     comment='e.g., Straight Line, Double Declining Balance.')
    # Total number of periods (e.g., 60 for 5 years @ monthly)
    total_number_of_depreciations: Mapped[int] = mapped_column(db.Integer, nullable=False, default=60)
    # Frequency in months (e.g., 1 for monthly, 12 for yearly)
    frequency_of_depreciation: Mapped[int] = mapped_column(db.Integer, nullable=False, default=1)

    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    # Relationships (Assumed models: Company, Account, Item)
    # accounts: relationships are defined on the Account model for clarity/backrefs
    assets: Mapped[List["Asset"]] = relationship(back_populates="asset_category", cascade="all, delete-orphan")
    items: Mapped[List["Item"]] = relationship(back_populates="asset_category")

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_asset_category_company_code"),
        UniqueConstraint("company_id", "name", name="uq_asset_category_company_name"),
    )

    def __repr__(self) -> str:
        return f"<AssetCategory {self.code} - {self.name}>"


# ──────────────────────────────────────────────────────────────────────────────
# 2) ASSET MODEL (The Physical Item Tracker)
# ──────────────────────────────────────────────────────────────────────────────
class Asset(BaseModel):
    """
    Represents a fixed asset item, tracking its purchase, value, and depreciation.
    This is created automatically when a purchase invoice item links to an AssetCategory.
    """
    __tablename__ = "assets"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    asset_category_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("asset_categories.id"), nullable=False, index=True
    )
    purchase_invoice_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id"), nullable=True, index=True,
        comment='The source document that acquired this asset.'
    )
    item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id"), nullable=True, index=True,
        comment='The Item master from which this asset was purchased.'
    )
    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("cost_centers.id"), nullable=True, index=True,
        comment='The department responsible for this asset.'
    )

    # Core Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False)

    # Financial Fields
    gross_purchase_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False,
                                                         comment='Original cost of the asset.')
    expected_salvage_value: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000,
                                                          comment='Residual value at the end of useful life.')
    depreciation_start_date: Mapped[date] = mapped_column(db.Date, nullable=False,
                                                          comment='The date depreciation calculation begins.')

    # Current Status (Updated by the depreciation process)
    current_value: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False,
                                                 comment='Book value = Gross Purchase - Accumulated Depreciation.')
    accumulated_depreciation: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    status: Mapped[str] = mapped_column(db.String(50), nullable=False, default="Draft",
                                        comment='e.g., Draft, Submitted, Capitalized, Fully Depreciated, Sold.')

    # Relationships
    asset_category: Mapped["AssetCategory"] = relationship(back_populates="assets")
    purchase_invoice: Mapped[Optional["PurchaseInvoice"]] = relationship(back_populates="assets")
    # Child table to store depreciation history
    item: Mapped[Optional["Item"]] = relationship("Item", back_populates="assets")  # Use string "Item"
    depreciation_entries: Mapped[List["AssetDepreciationEntry"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_asset_company_code"),
        Index("ix_asset_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Asset {self.code} - {self.name} (Value: {self.current_value})>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) ASSET DEPRECIATION ENTRY MODEL (The History Log)
# ──────────────────────────────────────────────────────────────────────────────
class AssetDepreciationEntry(BaseModel):
    """
    Records each depreciation transaction for an asset.
    One record is created per period (e.g., monthly).
    """
    __tablename__ = "asset_depreciation_entries"

    # Foreign Keys
    asset_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    journal_entry_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("journal_entries.id"),
        nullable=True, index=True,
        comment='The link to the actual GL Journal Entry created by this record.'
    )

    # Core Fields
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    depreciation_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False)

    # Snapshot of the Asset's state AFTER this entry
    accumulated_depreciation_after: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False)
    current_value_after: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False)

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    asset: Mapped["Asset"] = relationship(back_populates="depreciation_entries")

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("asset_id", "posting_date", name="uq_ade_asset_posting_date"),
    )

    def __repr__(self) -> str:
        return f"<AssetDepreciationEntry asset={self.asset_id} amount={self.depreciation_amount}>"