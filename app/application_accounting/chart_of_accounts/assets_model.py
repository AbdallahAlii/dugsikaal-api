# app/application_accounting/assets/model.py
from __future__ import annotations

import enum
from typing import Optional, List
from datetime import date

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    UniqueConstraint, Index, ForeignKey, String, Text, Boolean, Numeric, Date, Integer,
    CheckConstraint
)

from app.common.models.base import BaseModel
from config.database import db
from app.application_stock.stock_models import DocStatusEnum


# ──────────────────────────────────────────────────────────────────────────────
# ENUMS (ERPNext-like labels)
# ──────────────────────────────────────────────────────────────────────────────
class AssetStatusEnum(str, enum.Enum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    PARTIALLY_DEPRECIATED = "Partially Depreciated"
    FULLY_DEPRECIATED = "Fully Depreciated"
    SCRAPPED = "Scrapped"
    SOLD = "Sold"
    CAPITALIZED = "Capitalized"
    ISSUED = "Issued"


class DepreciationMethodEnum(str, enum.Enum):
    STRAIGHT_LINE = "Straight Line"
    DOUBLE_DECLINING_BALANCE = "Double Declining Balance"
    WRITTEN_DOWN_VALUE = "Written Down Value"
    MANUAL = "Manual"


# ──────────────────────────────────────────────────────────────────────────────
# 1) FINANCE BOOK (minimal: just a name per company)
# ──────────────────────────────────────────────────────────────────────────────
class FinanceBook(BaseModel):
    __tablename__ = "finance_books"

    company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Relationships
    company = relationship("Company")
    asset_finance_books: Mapped[List["AssetFinanceBook"]] = relationship(back_populates="finance_book")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_finance_book_company_name"),
    )

    def __repr__(self) -> str:
        return f"<FinanceBook {self.name}>"


# ──────────────────────────────────────────────────────────────────────────────
# 2) ASSET CATEGORY
# ──────────────────────────────────────────────────────────────────────────────
class AssetCategory(BaseModel):
    __tablename__ = "asset_categories"

    company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    asset_category_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # GL accounts
    fixed_asset_account: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True)
    accumulated_depreciation_account: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True)
    depreciation_expense_account: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("accounts.id"), nullable=False, index=True)
    capital_work_in_progress_account: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("accounts.id"), nullable=True, index=True)

    # Default depreciation settings (used as defaults when creating AssetFinanceBook)
    depreciation_method: Mapped[DepreciationMethodEnum] = mapped_column(
        db.Enum(DepreciationMethodEnum), nullable=False, default=DepreciationMethodEnum.STRAIGHT_LINE
    )
    total_number_of_depreciations: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    frequency_of_depreciation: Mapped[int] = mapped_column(Integer, nullable=False, default=12)  # months
    enable_cwip_accounting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    company = relationship("Company")
    fixed_asset_account_rel = relationship("Account", foreign_keys=[fixed_asset_account])
    accumulated_depreciation_account_rel = relationship("Account", foreign_keys=[accumulated_depreciation_account])
    depreciation_expense_account_rel = relationship("Account", foreign_keys=[depreciation_expense_account])
    capital_work_in_progress_account_rel = relationship("Account", foreign_keys=[capital_work_in_progress_account])
    items: Mapped[List["Item"]] = relationship(back_populates="asset_category")
    assets: Mapped[List["Asset"]] = relationship(back_populates="asset_category_rel", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "asset_category_name", name="uq_asset_category_company_name"),
        CheckConstraint("total_number_of_depreciations > 0", name="ck_cat_total_depr_pos"),
        CheckConstraint("frequency_of_depreciation > 0", name="ck_cat_freq_pos"),
    )

    def __repr__(self) -> str:
        return f"<AssetCategory {self.asset_category_name}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) ASSET (keeps only item_id; purchase fields nullable; calc flags included)
# ──────────────────────────────────────────────────────────────────────────────
class Asset(BaseModel):
    __tablename__ = "assets"

    # Identification / status
    company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True)
    asset_status: Mapped[AssetStatusEnum] = mapped_column(db.Enum(AssetStatusEnum), nullable=False, default=AssetStatusEnum.DRAFT, index=True)

    # Master/detail links
    asset_category: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("asset_categories.id"), nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("items.id"), nullable=True, index=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Purchase details (nullable; enforced in service layer if needed)
    purchase_receipt: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("purchase_receipts.id"), nullable=True, index=True)
    purchase_invoice: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("purchase_invoices.id"), nullable=True, index=True)
    supplier: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("parties.id"), nullable=True, index=True
    )
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    available_for_use_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    # Financials (nullable by design; service layer enforces when needed)
    gross_purchase_amount: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True, default=0.0000)
    opening_accumulated_depreciation: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True, default=0.0000)
    expected_salvage_value: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True, default=0.0000)

    # Depreciation control
    calculate_depreciation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_existing_asset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    depreciation_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)

    # Current values (calculated)
    value_after_depreciation: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=0.0000)

    # Quantity / cost center
    asset_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_center: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("cost_centers.id"), nullable=True, index=True)

    # Relationships
    company = relationship("Company")
    asset_category_rel = relationship("AssetCategory", back_populates="assets")
    item = relationship("Item", back_populates="assets")
    purchase_invoice_rel = relationship(
        "PurchaseInvoice",
        back_populates="assets"
    )
    purchase_receipt_rel = relationship("PurchaseReceipt")
    cost_center_rel = relationship("CostCenter")
    supplier_rel = relationship("Party")

    finance_books: Mapped[List["AssetFinanceBook"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    depreciation_entries: Mapped[List["AssetDepreciationEntry"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="AssetDepreciationEntry.schedule_date"
    )
    movement_entries: Mapped[List["AssetMovementItem"]] = relationship(back_populates="asset", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "asset_name", name="uq_asset_company_name"),
        Index("ix_asset_company_status", "company_id", "asset_status"),
        Index("ix_asset_category", "asset_category"),
        Index("ix_asset_purchase_date", "purchase_date"),
        CheckConstraint("asset_quantity > 0", name="ck_asset_quantity_pos"),
    )

    def __repr__(self) -> str:
        return f"<Asset {self.asset_name} ({self.asset_status})>"


# ──────────────────────────────────────────────────────────────────────────────
# 4) ASSET FINANCE BOOK (shown only if Calculate Depreciation = true)
# ──────────────────────────────────────────────────────────────────────────────
class AssetFinanceBook(BaseModel):
    __tablename__ = "asset_finance_books"

    asset_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    finance_book_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("finance_books.id"), nullable=False, index=True)

    # Finance-book level depreciation config for this asset
    depreciation_method: Mapped[DepreciationMethodEnum] = mapped_column(db.Enum(DepreciationMethodEnum), nullable=False)
    total_number_of_depreciations: Mapped[int] = mapped_column(Integer, nullable=False)
    frequency_of_depreciation: Mapped[int] = mapped_column(Integer, nullable=False, comment="Months between depreciations")
    depreciation_posting_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    expected_value_after_useful_life: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=0.0000)
    value_after_depreciation: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=0.0000)
    rate_of_depreciation: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=0.0000)

    # Relationships
    asset = relationship("Asset", back_populates="finance_books")
    finance_book = relationship("FinanceBook", back_populates="asset_finance_books")

    __table_args__ = (
        UniqueConstraint("asset_id", "finance_book_id", name="uq_afb_asset_book"),
        CheckConstraint("total_number_of_depreciations > 0", name="ck_afb_total_pos"),
        CheckConstraint("frequency_of_depreciation > 0", name="ck_afb_freq_pos"),
        CheckConstraint("expected_value_after_useful_life >= 0", name="ck_afb_salvage_nonneg"),
        CheckConstraint("value_after_depreciation >= 0", name="ck_afb_vad_nonneg"),
        CheckConstraint("rate_of_depreciation >= 0", name="ck_afb_rate_nonneg"),
    )

    def __repr__(self) -> str:
        return f"<AssetFinanceBook asset={self.asset_id} book={self.finance_book_id}>"


# ──────────────────────────────────────────────────────────────────────────────
# 5) DEPRECIATION SCHEDULE ENTRY
# ──────────────────────────────────────────────────────────────────────────────
class AssetDepreciationEntry(BaseModel):
    __tablename__ = "asset_depreciation_entries"

    asset_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    finance_book_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("finance_books.id"), nullable=False, index=True)
    journal_entry_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("journal_entries.id"), nullable=True, index=True)

    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    depreciation_amount: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=0.0000)
    accumulated_depreciation_amount: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=0.0000)

    # Relationships
    asset = relationship("Asset", back_populates="depreciation_entries")
    finance_book = relationship("FinanceBook")
    journal_entry = relationship("JournalEntry")

    __table_args__ = (
        UniqueConstraint("asset_id", "finance_book_id", "schedule_date", name="uq_ade_asset_book_date"),
        Index("ix_ade_asset_date", "asset_id", "schedule_date"),
        CheckConstraint("depreciation_amount >= 0", name="ck_ade_amt_nonneg"),
        CheckConstraint("accumulated_depreciation_amount >= 0", name="ck_ade_accum_nonneg"),
    )

    def __repr__(self) -> str:
        return f"<ADE asset={self.asset_id} date={self.schedule_date} amt={self.depreciation_amount}>"


# ──────────────────────────────────────────────────────────────────────────────
# 6) ASSET MOVEMENT (header) + 7) MOVEMENT ITEM (rows)
# ──────────────────────────────────────────────────────────────────────────────
class AssetMovement(BaseModel):
    __tablename__ = "asset_movements"

    company_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="Issue/Receipt/Transfer")

    company = relationship("Company")
    items: Mapped[List["AssetMovementItem"]] = relationship(back_populates="asset_movement", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_asset_movement_company_name"),
        Index("ix_am_posting_date", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<AssetMovement {self.name} ({self.purpose})>"


class AssetMovementItem(BaseModel):
    __tablename__ = "asset_movement_items"

    asset_movement_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("asset_movements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(db.BigInteger, ForeignKey("assets.id"), nullable=False, index=True)

    from_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    from_employee: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("employees.id"), nullable=True)
    to_employee: Mapped[Optional[int]] = mapped_column(db.BigInteger, ForeignKey("employees.id"), nullable=True)

    asset_movement = relationship("AssetMovement", back_populates="items")
    asset = relationship("Asset", back_populates="movement_entries")
    from_employee_rel = relationship("Employee", foreign_keys=[from_employee])
    to_employee_rel = relationship("Employee", foreign_keys=[to_employee])

    __table_args__ = (
        Index("ix_ami_asset", "asset_id"),
    )

    def __repr__(self) -> str:
        return f"<AssetMovementItem asset={self.asset_id} movement={self.asset_movement_id}>"
