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
    __tablename__ = "sales_delivery_notes"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id:  Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),  nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),  nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),  nullable=False, index=True)


    # Returns
    return_against_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("sales_delivery_notes.id"), nullable=True, index=True)

    # Core
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True)
    is_return: Mapped[bool]         = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[Decimal]  = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # Relationships
    customer: Mapped["Party"] = relationship()
    items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(back_populates="delivery_note", cascade="all, delete-orphan")

    return_against: Mapped[Optional["SalesDeliveryNote"]] = relationship(
        remote_side="SalesDeliveryNote.id", back_populates="returns", foreign_keys=[return_against_id]
    )
    returns: Mapped[List["SalesDeliveryNote"]] = relationship(back_populates="return_against", foreign_keys="SalesDeliveryNote.return_against_id")

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sdn_branch_code"),
        Index("ix_sdn_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sdn_company_customer", "company_id", "customer_id"),
        Index("ix_sdn_company_posting_date", "company_id", "posting_date"),
        Index("ix_sdn_is_return", "is_return"),
        CheckConstraint("(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)", name="ck_sdn_return_requires_original"),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNote code={self.code!r} customer={self.customer_id} return={self.is_return}>"


class SalesDeliveryNoteItem(BaseModel):
    __tablename__ = "sales_delivery_note_items"

    delivery_note_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("sales_delivery_notes.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id:          Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),       nullable=False, index=True)
    uom_id:           Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),        nullable=True, index=True)

    # Real posting warehouse (per-line, required on DN)
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"), nullable=False, index=True)

    # Returns linkage
    return_against_item_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"), nullable=True, index=True)

    # Quantities & price
    delivered_qty: Mapped[Decimal]  = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price:    Mapped[Optional[Decimal]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount:        Mapped[Optional[Decimal]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("CASE WHEN unit_price IS NULL THEN NULL ELSE delivered_qty * unit_price END", persisted=True),
        nullable=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    delivery_note: Mapped["SalesDeliveryNote"] = relationship(back_populates="items")
    item:          Mapped["Item"] = relationship()
    uom:           Mapped[Optional["UnitOfMeasure"]] = relationship()

    return_against_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship(
        remote_side="SalesDeliveryNoteItem.id", back_populates="return_items", foreign_keys=[return_against_item_id]
    )
    return_items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(back_populates="return_against_item", foreign_keys="SalesDeliveryNoteItem.return_against_item_id")

    # Link to invoice items (optional)
    invoice_items: Mapped[List["SalesInvoiceItem"]] = relationship(back_populates="delivery_note_item")

    __table_args__ = (
        CheckConstraint("delivered_qty <> 0", name="ck_sdni_qty_non_zero"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="ck_sdni_rate_non_negative"),
        Index("ix_sdni_item", "item_id"),
        Index("ix_sdni_warehouse", "warehouse_id"),
        Index("ix_sdni_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNoteItem item={self.item_id} qty={self.delivered_qty}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) SALES INVOICE (Finance + Optional Stock) - ERPNext Style
# ──────────────────────────────────────────────────────────────────────────────
class SalesInvoice(BaseModel):
    __tablename__ = "sales_invoices"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[int]  = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),  nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),  nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),  nullable=False, index=True)

    # Receivable ("Debit To")
    debit_to_account_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=False, index=True)



    # Returns (Credit Note)
    return_against_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("sales_invoices.id"), nullable=True, index=True)

    # VAT (simple)
    vat_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True)
    vat_rate: Mapped[Optional[Decimal]]   = mapped_column(db.Numeric(6, 3), nullable=True)
    vat_amount: Mapped[Decimal]           = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # Payment captured on invoice
    mode_of_payment_id: Mapped[Optional[int]]  = mapped_column(db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True)
    cash_bank_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True)

    # Core fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True)
    update_stock: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    is_return: Mapped[bool]    = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Amounts
    total_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))
    paid_amount:  Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))
    outstanding_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # Other
    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks:  Mapped[Optional[str]]      = mapped_column(db.Text)
    send_sms: Mapped[bool]               = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Relationships
    customer: Mapped["Party"] = relationship()
    debit_to_account: Mapped["Account"] = relationship(foreign_keys=[debit_to_account_id])
    vat_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[vat_account_id])
    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship()
    cash_bank_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[cash_bank_account_id])

    items: Mapped[List["SalesInvoiceItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    return_against: Mapped[Optional["SalesInvoice"]] = relationship(
        remote_side="SalesInvoice.id", back_populates="credit_notes", foreign_keys=[return_against_id]
    )
    credit_notes: Mapped[List["SalesInvoice"]] = relationship(
        back_populates="return_against", foreign_keys="SalesInvoice.return_against_id"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sin_branch_code"),
        Index("ix_sin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sin_company_customer", "company_id", "customer_id"),
        Index("ix_sin_company_posting_date", "company_id", "posting_date"),
        Index("ix_sin_company_update_stock", "company_id", "update_stock"),
        Index("ix_sin_is_return", "is_return"),
        Index("ix_sin_vat_account", "vat_account_id"),
        Index("ix_sin_mode_of_payment", "mode_of_payment_id"),
        Index("ix_sin_cash_bank_account", "cash_bank_account_id"),

        CheckConstraint("(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)", name="ck_sin_return_requires_original"),
        CheckConstraint("paid_amount >= 0 AND outstanding_amount >= 0", name="ck_sin_amounts_non_negative"),
        CheckConstraint("total_amount = paid_amount + outstanding_amount", name="ck_sin_amount_consistency"),
        CheckConstraint(
            "(paid_amount = 0 AND mode_of_payment_id IS NULL AND cash_bank_account_id IS NULL) OR "
            "(paid_amount > 0 AND mode_of_payment_id IS NOT NULL AND cash_bank_account_id IS NOT NULL)",
            name="ck_sin_payment_consistency"
        ),
        CheckConstraint(
            "(vat_amount = 0 AND vat_account_id IS NULL AND vat_rate IS NULL) OR "
            "(vat_amount > 0 AND vat_account_id IS NOT NULL AND vat_rate IS NOT NULL)",
            name="ck_sin_vat_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoice {self.code} customer={self.customer_id} paid={self.paid_amount}/{self.total_amount}>"


class SalesInvoiceItem(BaseModel):
    __tablename__ = "sales_invoice_items"

    invoice_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id:    Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"), nullable=False, index=True)
    uom_id:     Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"), nullable=True, index=True)

    # Real posting warehouse (per-line, required only when SI.update_stock = True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"), nullable=True, index=True)

    # Link to Delivery Note Item (common ERPNext mapping)
    delivery_note_item_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"), nullable=True, index=True)

    # Returns linkage
    return_against_item_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("sales_invoice_items.id"), nullable=True, index=True)

    # Amounts
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate:     Mapped[Decimal] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount:   Mapped[Decimal] = mapped_column(db.Numeric(14, 4), db.Computed("quantity * rate", persisted=True), nullable=False)

    # Accounting per line
    income_account_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True)
    cost_center_id:    Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("cost_centers.id"), nullable=True, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    invoice: Mapped["SalesInvoice"] = relationship(back_populates="items")
    item:    Mapped["Item"] = relationship()
    uom:     Mapped[Optional["UnitOfMeasure"]] = relationship()
    delivery_note_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship()

    return_against_item: Mapped[Optional["SalesInvoiceItem"]] = relationship(
        remote_side="SalesInvoiceItem.id", back_populates="credit_note_items", foreign_keys=[return_against_item_id]
    )
    credit_note_items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="return_against_item", foreign_keys="SalesInvoiceItem.return_against_item_id"
    )

    __table_args__ = (
        CheckConstraint("rate >= 0", name="ck_sii_rate_non_negative"),
        CheckConstraint("quantity <> 0", name="ck_sii_qty_non_zero"),
        Index("ix_sii_item", "item_id"),
        Index("ix_sii_warehouse", "warehouse_id"),
        Index("ix_sii_income_account", "income_account_id"),
        Index("ix_sii_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoiceItem item={self.item_id} qty={self.quantity} amount={self.amount}>"
