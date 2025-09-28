from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, text

# These imports are assumed to be in your project structure
from app.application_stock.stock_models import DocStatusEnum
from config.database import db
from app.common.models.base import BaseModel, StatusEnum
from app.application_parties.parties_models import Party
# Placeholder for other models you need to import
# from app.application_items.item_models import Item, UnitOfMeasure
# from app.application_stock.stock_models import Warehouse

# ──────────────────────────────────────────────────────────────────────────────
# 1) SALES QUOTATION (Quote)
# ──────────────────────────────────────────────────────────────────────────────
class SalesQuotation(BaseModel):
    """
    A Sales Quotation, often called a Quote.
    This document is a proposal of pricing to a customer and does not
    affect inventory stock or the general ledger.
    """
    __tablename__ = "sales_quotations"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    customer: Mapped["Party"] = relationship()
    items: Mapped[List["SalesQuotationItem"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sq_branch_code"),
        Index("ix_sq_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sq_company_customer", "company_id", "customer_id"),
        Index("ix_sq_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<SalesQuotation code={self.code!r} customer={self.customer_id} status={self.doc_status}>"


class SalesQuotationItem(BaseModel):
    """
    Represents an item line within a Sales Quotation document.
    """
    __tablename__ = "sales_quotation_items"

    # Foreign Keys
    quotation_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_quotations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                        nullable=False, index=True)

    # Item Line Fields
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )

    # Relationships
    quotation: Mapped["SalesQuotation"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sqi_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_sqi_rate_nonneg"),
        Index("ix_sqi_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesQuotationItem id={self.id} item={self.item_id} qty={self.quantity}>"


# ──────────────────────────────────────────────────────────────────────────────
# 2) SALES DELIVERY NOTE (Stock out)
# ──────────────────────────────────────────────────────────────────────────────
class SalesDeliveryNote(BaseModel):
    """
    A document that records the physical delivery of goods to a customer.
    This document affects inventory stock but not the general ledger.
    """
    __tablename__ = "sales_delivery_notes"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                              nullable=False, index=True)

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships
    customer: Mapped["Party"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(
        back_populates="delivery_note", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sdn_branch_code"),
        Index("ix_sdn_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sdn_company_customer", "company_id", "customer_id"),
        Index("ix_sdn_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNote code={self.code!r} customer={self.customer_id} status={self.doc_status}>"


class SalesDeliveryNoteItem(BaseModel):
    """
    Represents an item line within a Sales Delivery Note document.
    """
    __tablename__ = "sales_delivery_note_items"

    # Foreign Keys
    delivery_note_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_notes.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)

    # Item Line Fields
    delivered_qty: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Optional[float]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("CASE WHEN unit_price IS NULL THEN NULL ELSE delivered_qty * unit_price END", persisted=True),
        nullable=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    delivery_note: Mapped["SalesDeliveryNote"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("delivered_qty > 0", name="ck_sdni_delivered_pos"),
        Index("ix_sdni_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNoteItem id={self.id} item={self.item_id} qty={self.delivered_qty}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) SALES INVOICE (Finance-only or Direct-with-stock)
# ──────────────────────────────────────────────────────────────────────────────
class SalesInvoice(BaseModel):
    """
    The financial invoice sent to a customer.
    It can either bill a prior delivery or act as a single document for both stock and finance.
    """
    __tablename__ = "sales_invoices"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)
    # This is required if `update_stock` is True
    warehouse_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                                        nullable=True, index=True)

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    update_stock: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Finance Fields
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    amount_paid: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    balance_due: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    customer: Mapped["Party"] = relationship()
    warehouse: Mapped[Optional["Warehouse"]] = relationship()
    items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sin_branch_code"),
        Index("ix_sin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sin_company_customer", "company_id", "customer_id"),
        Index("ix_sin_company_posting_date", "company_id", "posting_date"),
        Index("ix_sin_company_update_stock", "company_id", "update_stock"),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoice code={self.code!r} customer={self.customer_id} stock={self.update_stock}>"


class SalesInvoiceItem(BaseModel):
    """
    Represents an item line within a Sales Invoice document.
    """
    __tablename__ = "sales_invoice_items"

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    # This is optional and can default to Item.base_uom in service logic if not provided
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)
    # Link to a previous SalesDeliveryNoteItem if this invoice is billing for a delivery
    delivery_note_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"),
        nullable=True, index=True
    )

    # Item Line Fields
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    invoice: Mapped["SalesInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship()
    delivery_note_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sii_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_sii_rate_nonneg"),
        Index("ix_sii_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoiceItem id={self.id} item={self.item_id} qty={self.quantity}>"


# ──────────────────────────────────────────────────────────────────────────────
# 4) SALES RETURN (Stock in)
# ──────────────────────────────────────────────────────────────────────────────
class SalesReturn(BaseModel):
    """
    A document that records the physical return of goods from a customer.
    This increases inventory stock and may be linked to a prior delivery or invoice.
    """
    __tablename__ = "sales_returns"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                              nullable=False, index=True)

    # Optional references to the original documents being returned against
    delivery_note_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_notes.id"),
        nullable=True, index=True
    )
    invoice_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id"),
        nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    customer: Mapped["Party"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    delivery_note: Mapped[Optional["SalesDeliveryNote"]] = relationship()
    invoice: Mapped[Optional["SalesInvoice"]] = relationship()
    items: Mapped[List["SalesReturnItem"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sret_branch_code"),
        Index("ix_sret_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sret_company_customer", "company_id", "customer_id"),
        Index("ix_sret_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<SalesReturn code={self.code!r} customer={self.customer_id} status={self.doc_status}>"


class SalesReturnItem(BaseModel):
    """
    Represents an item line within a Sales Return document.
    """
    __tablename__ = "sales_return_items"

    # Foreign Keys
    sales_return_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_returns.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                        nullable=False, index=True)
    # Optional links to the original item lines from either a delivery or an invoice
    delivery_note_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"),
        nullable=True, index=True
    )
    invoice_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoice_items.id"),
        nullable=True, index=True
    )

    # Item Line Fields
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[Optional[float]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("CASE WHEN rate IS NULL THEN NULL ELSE quantity * rate END", persisted=True),
        nullable=True
    )
    batch_number: Mapped[Optional[str]] = mapped_column(db.String(100), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    sales_return: Mapped["SalesReturn"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()
    delivery_note_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship()
    invoice_item: Mapped[Optional["SalesInvoiceItem"]] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sret_qty_pos"),
        CheckConstraint("rate IS NULL OR rate >= 0", name="ck_sret_rate_nonneg"),
        UniqueConstraint("sales_return_id", "item_id", "batch_number", name="uq_sret_item_batch"),
        Index("ix_sret_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesReturnItem id={self.id} item={self.item_id} qty={self.quantity}>"
