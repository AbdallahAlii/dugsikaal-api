from __future__ import annotations

from decimal import Decimal
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
    ERPNext Style: Return documents store NEGATIVE quantities.
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

    # Return against reference (ERPNext style)
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_notes.id"), nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)

    # Return Management (ERPNext style)
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # Relationships
    customer: Mapped["Party"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(
        back_populates="delivery_note", cascade="all, delete-orphan"
    )

    # Self-referential relationship for returns (ERPNext style)
    return_against: Mapped[Optional["SalesDeliveryNote"]] = relationship(
        remote_side="SalesDeliveryNote.id", back_populates="returns",
        foreign_keys=[return_against_id]
    )
    returns: Mapped[List["SalesDeliveryNote"]] = relationship(
        back_populates="return_against",
        foreign_keys="SalesDeliveryNote.return_against_id"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sdn_branch_code"),
        Index("ix_sdn_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sdn_company_customer", "company_id", "customer_id"),
        Index("ix_sdn_company_posting_date", "company_id", "posting_date"),
        Index("ix_sdn_is_return", "is_return"),

        # ERPNext-style constraints
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_sdn_return_requires_original"
        ),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNote code={self.code!r} customer={self.customer_id} return={self.is_return}>"


class SalesDeliveryNoteItem(BaseModel):
    """
    Represents an item line within a Sales Delivery Note document.
    ERPNext Style: Return items store NEGATIVE quantities.
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

    # Return against item reference
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"), nullable=True, index=True
    )

    # Item Line Fields (NEGATIVE for returns, POSITIVE for deliveries)
    delivered_qty: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(12, 4), nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(
        db.Numeric(14, 4),
        # Ensure the DB computed expression correctly handles NUMERIC types
        db.Computed("CASE WHEN unit_price IS NULL THEN NULL ELSE delivered_qty * unit_price END", persisted=True),
        nullable=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    delivery_note: Mapped["SalesDeliveryNote"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()
    return_against_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship(
        remote_side="SalesDeliveryNoteItem.id", back_populates="return_items",
        foreign_keys=[return_against_item_id]
    )
    return_items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="SalesDeliveryNoteItem.return_against_item_id"
    )

    # Link to invoice items
    invoice_items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="delivery_note_item"
    )

    # Table Constraints & Indices
    __table_args__ = (
        # Quantity constraints that allow negative values for returns
        CheckConstraint(
            "(delivery_note_id IN (SELECT id FROM sales_delivery_notes WHERE is_return = false) AND delivered_qty > 0) OR "
            "(delivery_note_id IN (SELECT id FROM sales_delivery_notes WHERE is_return = true) AND delivered_qty < 0)",
            name="ck_sdni_qty_direction"
        ),
        Index("ix_sdni_item", "item_id"),
        Index("ix_sdni_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNoteItem item={self.item_id} qty={self.delivered_qty} return={self.delivery_note.is_return}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) SALES INVOICE (Finance + Optional Stock) - ERPNext Style
# ──────────────────────────────────────────────────────────────────────────────
class SalesInvoice(BaseModel):
    """
    The financial invoice sent to a customer.
    ERPNext Style: Credit notes store NEGATIVE amounts and quantities.
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

    # Return against reference (ERPNext style)
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id"), nullable=True, index=True
    )

    # 🔗 CORE ACCOUNTING LINKS


    # VAT/Tax Fields
    vat_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=True,
                                                          index=True)
    vat_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))  # FIXED    vat_rate: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(5, 2), nullable=True)  # FIXED

    # Payment Fields (ERPNext Style - Direct on Invoice)
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True
    )
    cash_bank_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    update_stock: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Return Management (ERPNext style)
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    is_credit_note: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # POS Features
    is_pos: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    send_sms: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Finance Fields (NEGATIVE for credit notes)
    total_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))  # FIXED
    paid_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))  # FIXED
    outstanding_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False,
                                                        default=Decimal("0.0000"))  # FIXED




    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    customer: Mapped["Party"] = relationship()
    warehouse: Mapped[Optional["Warehouse"]] = relationship()
    items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    # Core Accounting Relationships

    vat_account: Mapped[Optional["Account"]] = relationship(
        foreign_keys=[vat_account_id], back_populates="sales_invoices_vat"
    )

    # Payment Relationships (ERPNext Style)
    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship(
        back_populates="sales_invoices"
    )
    # For cash_bank_account_id: Use appropriate cash/bank accounts
    # This will vary based on payment method:
    # - Cash: 1111 (Cash) or 1112 (Merchant Cashier), etc.
    # - Bank: 1121-1128 (Various bank accounts)
    cash_bank_account: Mapped[Optional["Account"]] = relationship(
        foreign_keys=[cash_bank_account_id], back_populates="sales_invoices_cash_bank"
    )

    # Self-referential relationship for returns (ERPNext style)
    return_against: Mapped[Optional["SalesInvoice"]] = relationship(
        remote_side="SalesInvoice.id", back_populates="credit_notes",
        foreign_keys=[return_against_id]
    )
    credit_notes: Mapped[List["SalesInvoice"]] = relationship(
        back_populates="return_against",
        foreign_keys="SalesInvoice.return_against_id"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sin_branch_code"),
        Index("ix_sin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sin_company_customer", "company_id", "customer_id"),
        Index("ix_sin_company_posting_date", "company_id", "posting_date"),
        Index("ix_sin_company_update_stock", "company_id", "update_stock"),
        Index("ix_sin_is_return", "is_return"),
        Index("ix_sin_is_pos", "is_pos"),

        # Accounting Indices

        Index("ix_sin_vat_account", "vat_account_id"),
        Index("ix_sin_mode_of_payment", "mode_of_payment_id"),
        Index("ix_sin_cash_bank_account", "cash_bank_account_id"),

        # ERPNext-style constraints
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_sin_return_requires_original"
        ),
        CheckConstraint(
            "paid_amount >= 0 AND outstanding_amount >= 0",
            name="ck_sin_amounts_non_negative"
        ),
        CheckConstraint(
            "total_amount = paid_amount + outstanding_amount",
            name="ck_sin_amount_consistency"
        ),
        # Payment validation
        CheckConstraint(
            "(paid_amount = 0 AND mode_of_payment_id IS NULL AND cash_bank_account_id IS NULL) OR "
            "(paid_amount > 0 AND mode_of_payment_id IS NOT NULL AND cash_bank_account_id IS NOT NULL)",
            name="ck_sin_payment_consistency"
        ),
        # VAT validation
        CheckConstraint(
            "(vat_amount = 0 AND vat_account_id IS NULL AND vat_rate IS NULL) OR "
            "(vat_amount >= 0 AND vat_account_id IS NOT NULL AND vat_rate IS NOT NULL)",
            name="ck_sin_vat_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoice {self.code} customer={self.customer_id} paid={self.paid_amount}/{self.total_amount}>"


class SalesInvoiceItem(BaseModel):
    """
    Represents an item line within a Sales Invoice or Credit Note.
    ERPNext Style: Credit note items store NEGATIVE quantities and amounts.
    """
    __tablename__ = "sales_invoice_items"

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)
    delivery_note_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"),
        nullable=True, index=True
    )

    # Return against item reference
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoice_items.id"), nullable=True, index=True
    )

    # Item Line Fields (NEGATIVE for credit notes, POSITIVE for invoices)
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False) # FIXED
    rate: Mapped[Decimal] = mapped_column(db.Numeric(12, 4), nullable=False) # FIXED
    amount: Mapped[Decimal] = mapped_column( # FIXED
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
    return_against_item: Mapped[Optional["SalesInvoiceItem"]] = relationship(
        remote_side="SalesInvoiceItem.id", back_populates="credit_note_items",
        foreign_keys=[return_against_item_id]
    )
    credit_note_items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="SalesInvoiceItem.return_against_item_id"
    )

    # Table Constraints & Indices
    __table_args__ = (
        # Quantity and rate constraints that allow negative values for credit notes
        CheckConstraint(
            "(invoice_id IN (SELECT id FROM sales_invoices WHERE is_return = false) AND quantity > 0) OR "
            "(invoice_id IN (SELECT id FROM sales_invoices WHERE is_return = true) AND quantity < 0)",
            name="ck_sii_quantity_direction"
        ),
        CheckConstraint("rate >= 0", name="ck_sii_rate_non_negative"),
        Index("ix_sii_item", "item_id"),
        Index("ix_sii_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoiceItem item={self.item_id} qty={self.quantity} amount={self.amount} credit_note={self.invoice.is_return}>"
