from __future__ import annotations
from typing import Optional
import enum

from sqlalchemy import UniqueConstraint, Index, func, text
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

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_uom_company_name"),
        Index("ix_uoms_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<UnitOfMeasure id={self.id} company_id={self.company_id} name={self.name!r}>"


class Item(BaseModel):
    """
    Represents a salable product or service scoped to a single company.
    """
    __tablename__ = "items"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.Text)
    sku: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    item_type: Mapped[ItemTypeEnum] = mapped_column(
        db.Enum(ItemTypeEnum), nullable=False, default=ItemTypeEnum.STOCK_ITEM
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    base_uom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=True
    )
    brand: Mapped[Optional["Brand"]] = relationship(back_populates="items")
    base_uom: Mapped["UnitOfMeasure"] = relationship("UnitOfMeasure", foreign_keys=[base_uom_id])
    prices: Mapped[list["BranchItemPricing"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    ledger_entries: Mapped[list["StockLedgerEntry"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    uom_conversions: Mapped[list["UOMConversion"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    status: Mapped[StatusEnum] = mapped_column(db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE)
    bins: Mapped[list["Bin"]] = relationship(back_populates="item")

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_item_company_sku"),
        Index("ix_items_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<Item id={self.id} company_id={self.company_id} name={self.name!r} sku={self.sku!r}>"


class UOMConversion(BaseModel):
    """Defines conversion factors between units for a single item within a company."""
    __tablename__ = "uom_conversions"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    from_uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
                                             nullable=False)
    to_uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
                                           nullable=False)
    conversion_factor: Mapped[float] = mapped_column(db.Numeric(10, 4), nullable=False)
    item: Mapped["Item"] = relationship(back_populates="uom_conversions")
    from_uom: Mapped["UnitOfMeasure"] = relationship("UnitOfMeasure", foreign_keys=[from_uom_id])
    to_uom: Mapped["UnitOfMeasure"] = relationship("UnitOfMeasure", foreign_keys=[to_uom_id])

    __table_args__ = (
        UniqueConstraint("item_id", "from_uom_id", "to_uom_id", name="uq_uom_conversion"),
        Index("ix_uom_conversions_company_id", "company_id"),
    )


class BranchItemPricing(BaseModel):
    """
    Defines the standard rate and cost for a specific item at a specific company/branch.
    """
    __tablename__ = "branch_item_pricing"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="CASCADE"),
                                           nullable=False)
    standard_rate: Mapped[float] = mapped_column(db.Numeric(10, 2), nullable=False, default=0.0)
    cost: Mapped[float] = mapped_column(db.Numeric(10, 2), nullable=False, default=0.0)

    item: Mapped["Item"] = relationship(back_populates="prices")
    branch: Mapped["Branch"] = relationship()

    __table_args__ = (
        UniqueConstraint("company_id", "item_id", "branch_id", name="uq_branch_item_price"),
        Index("ix_branch_item_pricing_company_id", "company_id"),
    )

    def __repr__(self) -> str:
        return f"<BranchItemPricing id={self.id} company={self.company_id} item={self.item_id} branch={self.branch_id} rate={self.standard_rate}>"


