from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
import enum

from sqlalchemy import UniqueConstraint, Index, func, text, CheckConstraint, and_
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


# --- Enums for Item Types ---
class ItemTypeEnum(str, enum.Enum):
    STOCK_ITEM = "Stock"
    SERVICE = "Service"


# --- Core Inventory Models ---
class Brand(BaseModel):
    """
    A company-specific brand of an item.
    """
    __tablename__ = "brands"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(150), nullable=False)

    items: Mapped[list["Item"]] = relationship(back_populates="brand")
    status: Mapped[StatusEnum] = mapped_column(db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE)

    company: Mapped["Company"] = relationship("Company", back_populates="brands")
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_brand_company_name"),
        Index("ix_brands_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<Brand id={self.id} company_id={self.company_id} name={self.name!r}>"


class UnitOfMeasure(BaseModel):
    """
    A company-specific unit of measure.
    """
    __tablename__ = "units_of_measure"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(db.String(20), nullable=False)
    status: Mapped[StatusEnum] = mapped_column(db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE)


    # relationships
    items: Mapped[List["Item"]] = relationship(back_populates="base_uom")
    company: Mapped["Company"] = relationship("Company", back_populates="units_of_measure")

    uom_conversions: Mapped[List["UOMConversion"]] = relationship(
        back_populates="uom", cascade="all, delete-orphan"
    )

    # Transaction relationships
    purchase_receipt_items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        "PurchaseReceiptItem", back_populates="uom"
    )
    purchase_invoice_items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        "PurchaseInvoiceItem", back_populates="uom"
    )
    purchase_quotation_items: Mapped[List["PurchaseQuotationItem"]] = relationship(
        "PurchaseQuotationItem", back_populates="uom"
    )
    item_prices: Mapped[List["ItemPrice"]] = relationship(
        "ItemPrice", back_populates="uom"
    )
    stock_entry_items: Mapped[List["StockEntryItem"]] = relationship(
        "StockEntryItem", back_populates="uom"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_uom_company_name"),
        Index("ix_uoms_company_id", "company_id"),
        # ADDED: Performance index for UOM lookups
        Index("ix_uom_name_symbol", "name", "symbol"),
    )

    def __repr__(self) -> str:
        return f"<UnitOfMeasure id={self.id} company_id={self.company_id} name={self.name!r}>"




# ------------------------------------------------------------------------------
# ITEM GROUP MODEL - Final Best Practice
# ------------------------------------------------------------------------------

class ItemGroup(BaseModel):
    """
    Categorizes items and defines default accounting accounts for all child items.
    """
    __tablename__ = "item_groups"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    parent_item_group_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("item_groups.id"), nullable=True, index=True
    )

    # Core Fields
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    is_group: Mapped[bool] = mapped_column(db.Boolean, default=False, comment="True if this is a parent node, False if it holds items.")

    # 🔗 DEFAULT ACCOUNTING ACCOUNTS (Indices added for fast transaction lookup)
    default_expense_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment="Default account for expense/COGS when buying/selling items in this group."
    )
    default_income_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment="Default Income/Sales account."
    )
    default_inventory_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment="Default Inventory Asset (Stocks in Hand) account."
    )

    # Relationships
    items: Mapped[List["Item"]] = relationship(back_populates="item_group")
    default_expense_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[default_expense_account_id])
    default_income_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[default_income_account_id])
    default_inventory_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[default_inventory_account_id])
    company: Mapped["Company"] = relationship("Company", back_populates="item_groups")
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_item_group_company_code"),
        # Index on company_id and accounts for fast retrieval of company-specific defaults
        Index("ix_item_group_defaults", "company_id", "default_expense_account_id", "default_income_account_id", "default_inventory_account_id"),
    )

    def __repr__(self) -> str:
        return f"<ItemGroup {self.code} - {self.name}>"


class Item(BaseModel):
    """
    Represents a product, service, or fixed asset.
    Inherits primary accounting from ItemGroup.
    """
    __tablename__ = "items"

    # --- Foreign Keys ---
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    item_group_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("item_groups.id"), nullable=False, index=True,
        comment="Mandatory link for inheriting accounting and inventory rules."
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    base_uom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    # 🔗 Asset Category Link (CRITICAL: Required for Fixed Asset items)
    asset_category_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("asset_categories.id"), nullable=True, index=True
    )

    # --- Core Fields ---
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    # 🔑 SKU (Item Code) - Retained from your original model and made Unique
    sku: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    # Item Type (Use your original Enum style)
    item_type: Mapped[ItemTypeEnum] = mapped_column(
        db.Enum(ItemTypeEnum), nullable=False, default=ItemTypeEnum.STOCK_ITEM
    )

    # --- BEHAVIORAL FLAGS ---

    is_fixed_asset: Mapped[bool] = mapped_column(db.Boolean, default=False, index=True)

    # Status
    status: Mapped[StatusEnum] = mapped_column(db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE,
                                               index=True)

    # --- Relationships (All essential relationships from your old model are here) ---
    item_group: Mapped["ItemGroup"] = relationship(back_populates="items")
    brand: Mapped[Optional["Brand"]] = relationship(back_populates="items")
    base_uom: Mapped["UnitOfMeasure"] = relationship("UnitOfMeasure", foreign_keys=[base_uom_id])
    asset_category: Mapped[Optional["AssetCategory"]] = relationship(back_populates="items")
    company: Mapped["Company"] = relationship("Company", back_populates="items")

    ledger_entries: Mapped[list["StockLedgerEntry"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    uom_conversions: Mapped[List["UOMConversion"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    bins: Mapped[list["Bin"]] = relationship(back_populates="item")
    assets: Mapped[List["Asset"]] = relationship(back_populates="item")  # Asset relationship link
    purchase_receipt_items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        "PurchaseReceiptItem", back_populates="item", cascade="all, delete-orphan"
    )
    purchase_invoice_items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        "PurchaseInvoiceItem", back_populates="item", cascade="all, delete-orphan"
    )
    item_prices: Mapped[List["ItemPrice"]] = relationship(
        "ItemPrice", back_populates="item", cascade="all, delete-orphan"
    )

    # --- Table Constraints & Indices ---
    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_item_company_sku"),
        # Ensures that a fixed asset item has its required rulebook (AssetCategory)
        CheckConstraint(
            "(is_fixed_asset = false) OR (is_fixed_asset = true AND asset_category_id IS NOT NULL)",
            name="ck_item_fixed_asset_requires_category"
        ),
        # Index on common foreign keys for joins and lookups
        Index("ix_item_fks", "item_group_id", "brand_id", "base_uom_id"),
        # ADDED: Performance indexes for UOM conversions
        Index("ix_item_base_uom", "base_uom_id", "status"),
        Index("ix_item_sku_status", "sku", "status"),
        Index("ix_item_company_status", "company_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Item {self.sku} - {self.name}>"




# ------------------------------------------------------------------------------
# PRICE LIST MODEL
# ------------------------------------------------------------------------------

class PriceListType(str, enum.Enum):
    BUYING = "Buying"
    SELLING = "Selling"
    BOTH = "Both"

class PriceList(BaseModel):
    __tablename__ = "price_lists"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(db.String(255), nullable=False)

    list_type: Mapped[PriceListType] = mapped_column(
        db.Enum(PriceListType),
        nullable=False,
        default=PriceListType.SELLING,
    )

    price_not_uom_dependent: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    # ✅ NEW: company default price list (replaces "Selling Settings Default Price List")
    is_default: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Relationships
    item_prices: Mapped[List["ItemPrice"]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan"
    )
    company: Mapped["Company"] = relationship("Company", back_populates="price_lists")

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_price_list_company_name"),

        # Useful query index
        Index("ix_price_list_company_type_active_default", "company_id", "list_type", "is_active", "is_default"),

        # ✅ Postgres-only: ensure only one default SELLING-compatible list per company
        Index(
            "uq_price_list_default_selling",
            "company_id",
            unique=True,
            postgresql_where=db.and_(
                is_default.is_(True),
                list_type.in_([PriceListType.SELLING, PriceListType.BOTH]),
            ),
        ),

        # ✅ Postgres-only: ensure only one default BUYING-compatible list per company
        Index(
            "uq_price_list_default_buying",
            "company_id",
            unique=True,
            postgresql_where=db.and_(
                is_default.is_(True),
                list_type.in_([PriceListType.BUYING, PriceListType.BOTH]),
            ),
        ),
    )

    def __repr__(self) -> str:
        return f"<PriceList {self.name} ({self.list_type.value}) default={self.is_default}>"


# ------------------------------------------------------------------------------
# ITEM PRICE MODEL
# ------------------------------------------------------------------------------

class ItemPrice(BaseModel):
    __tablename__ = "item_prices"

    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price_list_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Branch override: NULL = global
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id"), nullable=True, index=True
    )

    # UOM override: NULL = base / not uom dependent (depending on price list behavior)
    uom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id"), nullable=True, index=True
    )

    rate: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False)

    valid_from: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    valid_upto: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)

    # Relationships
    item: Mapped["Item"] = relationship(back_populates="item_prices")
    price_list: Mapped["PriceList"] = relationship(back_populates="item_prices")
    branch: Mapped[Optional["Branch"]] = relationship(back_populates="item_prices")
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship(back_populates="item_prices")
    company: Mapped["Company"] = relationship("Company", back_populates="item_prices")

    __table_args__ = (
        # ✅ Allow multiple rows for same item+price_list if validity differs (ERPNext style)
        # No UniqueConstraint here.

        CheckConstraint(
            "valid_from IS NULL OR valid_upto IS NULL OR valid_from <= valid_upto",
            name="ck_item_price_valid_from_upto",
        ),

        # Fast lookup index (the one that matters)
        Index(
            "ix_item_price_lookup",
            "company_id", "price_list_id", "item_id", "branch_id", "uom_id", "valid_from", "valid_upto",
        ),

        # Optional: speed branch/global scans in Postgres
        Index(
            "ix_item_price_branch_null",
            "company_id", "price_list_id", "item_id", "uom_id", "valid_from", "valid_upto",
            postgresql_where=branch_id.is_(None),
        ),
        Index(
            "ix_item_price_branch_some",
            "company_id", "price_list_id", "item_id", "branch_id", "uom_id", "valid_from", "valid_upto",
            postgresql_where=branch_id.is_not(None),
        ),
    )

    def __repr__(self) -> str:
        return f"<ItemPrice item={self.item_id} pl={self.price_list_id} rate={self.rate}>"


# ──────────────────────────────────────────────────────────────────────────────
# UOM CONVERSION (Option B - PERFECT for all industries)
# ──────────────────────────────────────────────────────────────────────────────
class UOMConversion(BaseModel):
    """
    BEST PRACTICE: Simple, clean UOM conversion system
    Works for ALL industries: Tailor, Pharmacy, Electronics, Production

    Rule: 1 [This UOM] = conversion_factor [Stock UOM]
    Example: 1 'Box' = 24.0 'Pieces' (if stock UOM is Pieces)
    """
    __tablename__ = "uom_conversions"

    # Core Relationships
    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    uom_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id"),
        nullable=False, index=True
    )

    # Simple Conversion Factor
    conversion_factor: Mapped[Decimal] = mapped_column(
        db.Numeric(18, 6), nullable=False, default=1.0,
        comment="1 [This UOM] = conversion_factor [Stock UOM]"
    )

    # Active flag for temporary UOMs
    is_active: Mapped[bool] = mapped_column(db.Boolean, default=True, index=True)

    # Relationships
    item: Mapped["Item"] = relationship(back_populates="uom_conversions")
    uom: Mapped["UnitOfMeasure"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("item_id", "uom_id", name="uq_uom_conv_item_uom"),
        CheckConstraint("conversion_factor > 0", name="ck_uom_conv_positive_factor"),


        Index("ix_uom_conv_item_lookup", "item_id", "uom_id"),
        Index("ix_uom_conv_active", "item_id", "is_active"),
        Index("ix_uom_conv_fast", "item_id", "uom_id", "is_active", "conversion_factor"),
    )

    def __repr__(self) -> str:
        return f"<UOMConversion item={self.item_id} uom={self.uom_id} factor={self.conversion_factor}>"




