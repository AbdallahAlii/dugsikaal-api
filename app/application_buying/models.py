from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, text
import enum
from app.application_stock.stock_models import DocStatusEnum
from config.database import db
from app.common.models.base import BaseModel, StatusEnum

from app.application_parties.parties_models import Party


# ──────────────────────────────────────────────────────────────────────────────
# 1) PURCHASE QUOTATION (RFQ / Quote)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseQuotation(BaseModel):
    """
    A Purchase Quotation, also known as a Request for Quotation (RFQ).
    This document is a request for pricing from a supplier and does not
    affect inventory stock or the general ledger.
    """
    __tablename__ = "purchase_quotations"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)  # Per-branch series
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    supplier: Mapped["Party"] = relationship()
    items: Mapped[List["PurchaseQuotationItem"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    branch: Mapped["Branch"] = relationship("Branch", back_populates="purchase_quotations")
    company: Mapped["Company"] = relationship("Company", back_populates="purchase_quotations")
    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pq_branch_code"),
        Index("ix_pq_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pq_company_supplier", "company_id", "supplier_id"),
        Index("ix_pq_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseQuotation code={self.code!r} supplier={self.supplier_id} status={self.doc_status}>"


class PurchaseQuotationItem(BaseModel):
    """
    Represents an item line within a Purchase Quotation document.
    """
    __tablename__ = "purchase_quotation_items"

    # Foreign Keys
    quotation_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_quotations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                        nullable=True, index=True)

    # Item Line Fields
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )

    # Relationships
    quotation: Mapped["PurchaseQuotation"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pqi_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_pqi_rate_nonneg"),
        Index("ix_pqi_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseQuotationItem id={self.id} item={self.item_id} qty={self.quantity}>"





# ──────────────────────────────────────────────────────────────────────────────
# PURCHASE RECEIPT (Stock only) - TRUE ERPNext Style
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseReceipt(BaseModel):
    """
    A document that records the physical receipt/return of goods from/to a supplier.
    TRUE ERPNext Style: Return documents store NEGATIVE quantities.
    """
    __tablename__ = "purchase_receipts"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                              nullable=False, index=True)

    # Return against reference (ERPNext style)
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id"), nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    # User-facing date (like ERPNext 'Dated')
    dated: Mapped[Optional[datetime]] = mapped_column(
        db.DateTime(timezone=True), nullable=True, index=True,
        comment="User-selected date for display (like ERPNext 'Dated' field)"
    )

    # System-effective date (like ERPNext 'Date') - for stock/accounting
    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, index=True,
        comment="System-determined date for stock/accounting (like ERPNext 'Date')"
    )


    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)

    # Return Management (ERPNext style)
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships
    branch: Mapped["Branch"] = relationship("Branch", back_populates="purchase_receipts")
    company: Mapped["Company"] = relationship("Company", back_populates="purchase_receipts")
    supplier: Mapped["Party"] = relationship("Party", back_populates="purchase_receipts")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", back_populates="purchase_receipts")
    created_by: Mapped["User"] = relationship(back_populates="created_purchase_receipts")
    items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )
    invoices: Mapped[List["PurchaseInvoice"]] = relationship(
        back_populates="receipt",  # Links back to the 'receipt' property on PurchaseInvoice
        foreign_keys="PurchaseInvoice.receipt_id",
        cascade="all, delete-orphan",  # Optional, but common for collections
    )

    # Self-referential relationship for returns (ERPNext style)
    return_against: Mapped[Optional["PurchaseReceipt"]] = relationship(
        remote_side="PurchaseReceipt.id", back_populates="returns",
        foreign_keys=[return_against_id]
    )
    returns: Mapped[List["PurchaseReceipt"]] = relationship(
        back_populates="return_against",
        foreign_keys="PurchaseReceipt.return_against_id"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pr_branch_code"),
        Index("ix_pr_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pr_company_supplier", "company_id", "supplier_id"),
        Index("ix_pr_company_posting_date", "company_id", "posting_date"),
        Index("ix_pr_is_return", "is_return"),

        # ERPNext-style constraints
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_pr_return_requires_original"
        ),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReceipt {self.code} supplier={self.supplier_id} return={self.is_return}>"


class PurchaseReceiptItem(BaseModel):
    """
    Represents an item line within a Purchase Receipt document.
    TRUE ERPNext Style: Return items store NEGATIVE quantities.
    """
    __tablename__ = "purchase_receipt_items"

    # Foreign Keys
    receipt_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                        nullable=True, index=True)

    # Return against item reference
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipt_items.id"), nullable=True, index=True
    )

    # Item Line Fields (NEGATIVE for returns, POSITIVE for receipts)
    received_qty: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    accepted_qty: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Optional[float]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("accepted_qty * unit_price", persisted=True),
        nullable=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))
    # ✅ SIMPLE FIELD: Returned quantity tracking
    returned_qty: Mapped[float] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0.000,
        comment="Total quantity returned against this item line"
    )

    # Relationships
    receipt: Mapped["PurchaseReceipt"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="purchase_receipt_items")
    uom: Mapped["UnitOfMeasure"] = relationship(back_populates="purchase_receipt_items")
    return_against_item: Mapped[Optional["PurchaseReceiptItem"]] = relationship(
        remote_side="PurchaseReceiptItem.id", back_populates="return_items",
        foreign_keys=[return_against_item_id]
    )
    return_items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="PurchaseReceiptItem.return_against_item_id"
    )

    # Link to invoice items
    invoice_items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="receipt_item"
    )

    # Table Constraints & Indices
    __table_args__ = (
        # ✅ IMPROVED: Allow UOM to be NULL for service items
        CheckConstraint(
            "(receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = false) AND received_qty > 0 AND accepted_qty > 0) OR "
            "(receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = true) AND received_qty < 0 AND accepted_qty < 0)",
            name="ck_pri_qty_direction"
        ),
        CheckConstraint(
            "ABS(accepted_qty) <= ABS(received_qty)",
            name="ck_pri_accepted_leq_received"
        ),
        CheckConstraint(
            "returned_qty >= 0 AND returned_qty <= accepted_qty",
            name="ck_pri_returned_qty_range"
        ),
        Index("ix_pri_item", "item_id"),
        Index("ix_pri_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReceiptItem item={self.item_id} qty={self.accepted_qty} return={self.receipt.is_return}>"



# ──────────────────────────────────────────────────────────────────────────────
# PURCHASE INVOICE (Finance + Optional Stock) - TRUE ERPNext Style (FIXED)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseInvoice(BaseModel):
    """
    The supplier's financial invoice or Debit Note.
    TRUE ERPNext Style: Debit notes store NEGATIVE amounts and quantities.
    """
    __tablename__ = "purchase_invoices"

    # Foreign Keys
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"),
                                             nullable=False, index=True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                                        nullable=True, index=True)

    # Return against reference (ERPNext style)
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id"), nullable=True, index=True
    )
    receipt_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id"),
        nullable=True, index=True,
        comment="The Purchase Receipt this invoice is generated from (clears GRNI)."
    )
    # 🔗 CORE ACCOUNTING LINKS (Mandatory Liability Link Restored)
    # 1. The GL Account for the primary Liability (Credit for PI)
    payable_account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment="The Accounts Payable (Liability) account used for the Credit posting."
    )


    # Payment Fields (ERPNext Style - Direct on Invoice)
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("modes_of_payment.id"), nullable=True, index=True
    )
    cash_bank_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    # User-facing date (like ERPNext 'Dated')
    dated: Mapped[Optional[datetime]] = mapped_column(
        db.DateTime(timezone=True), nullable=True, index=True,
        comment="User-selected date for display (like ERPNext 'Dated' field)"
    )

    # System-effective date (like ERPNext 'Date') - for stock/accounting
    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, index=True,
        comment="System-determined date for stock/accounting (like ERPNext 'Date')"
    )


    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)




    update_stock: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Return Management (ERPNext style)
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    is_debit_note: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Finance Fields (NEGATIVE for debit notes)
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    paid_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    outstanding_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="purchase_invoices")
    branch: Mapped["Branch"] = relationship(back_populates="purchase_invoices")
    created_by: Mapped["User"] = relationship(back_populates="created_purchase_invoices")
    supplier: Mapped["Party"] = relationship(back_populates="purchase_invoices")
    warehouse: Mapped[Optional["Warehouse"]] = relationship(back_populates="purchase_invoices")
    items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    receipt: Mapped[Optional["PurchaseReceipt"]] = relationship(
        back_populates="invoices",  # Assuming PurchaseReceipt has an 'invoices' backref
        foreign_keys=[receipt_id]
    )

    # Core Accounting Relationships (Restored)
    payable_account: Mapped["Account"] = relationship(
        foreign_keys=[payable_account_id], back_populates="purchase_invoices_payable"
    )

    # Payment Relationships (ERPNext Style)
    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship(back_populates="purchase_invoices")
    cash_bank_account: Mapped[Optional["Account"]] = relationship(
        foreign_keys=[cash_bank_account_id], back_populates="purchase_invoices_cash_bank"
    )

    # Self-referential relationship for returns (ERPNext style)
    return_against: Mapped[Optional["PurchaseInvoice"]] = relationship(
        remote_side="PurchaseInvoice.id", back_populates="debit_notes",
        foreign_keys=[return_against_id]
    )
    debit_notes: Mapped[List["PurchaseInvoice"]] = relationship(
        back_populates="return_against",
        foreign_keys="PurchaseInvoice.return_against_id"
    )
    assets: Mapped[List["Asset"]] = relationship(
        "Asset", back_populates="purchase_invoice"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pin_branch_code"),
        Index("ix_pin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pin_company_supplier", "company_id", "supplier_id"),
        Index("ix_pin_company_posting_date", "company_id", "posting_date"),
        Index("ix_pin_company_update_stock", "company_id", "update_stock"),
        Index("ix_pin_is_return", "is_return"),
    Index("ix_pin_receipt_id", "receipt_id"),
        # Accounting Index (Restored)
        Index("ix_pin_payable_account", "payable_account_id"),

        Index("ix_pin_mode_of_payment", "mode_of_payment_id"),
        Index("ix_pin_cash_bank_account", "cash_bank_account_id"),

        # ERPNext-style constraints
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_pin_return_requires_original"
        ),
        CheckConstraint(
            "paid_amount >= 0 AND outstanding_amount >= 0",
            name="ck_pin_amounts_non_negative"
        ),
        CheckConstraint(
            "total_amount = paid_amount + outstanding_amount",
            name="ck_pin_amount_consistency"
        ),
        # Payment validation
        CheckConstraint(
            "(paid_amount = 0 AND mode_of_payment_id IS NULL AND cash_bank_account_id IS NULL) OR "
            "(paid_amount > 0 AND mode_of_payment_id IS NOT NULL AND cash_bank_account_id IS NOT NULL)",
            name="ck_pin_payment_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoice {self.code} supplier={self.supplier_id} paid={self.paid_amount}/{self.total_amount}>"

class PurchaseInvoiceItem(BaseModel):
    """
    Represents an item line within a Purchase Invoice or Debit Note.
    TRUE ERPNext Style: Debit note items store NEGATIVE quantities and amounts.
    """
    __tablename__ = "purchase_invoice_items"

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)
    receipt_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipt_items.id"),
        nullable=True, index=True
    )

    # Return against item reference
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoice_items.id"), nullable=True, index=True
    )

    # Item Line Fields (NEGATIVE for debit notes, POSITIVE for invoices)
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))
    # ✅ DENORMALIZED FIELD: Tracks quantity returned via subsequent Debit Notes
    # This is only updated if the parent document (PurchaseInvoice) is NOT a return.
    returned_qty: Mapped[float] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0.000,
        comment="Total quantity returned against this standard Invoice Item (via linked Debit Notes)."
    )
    # Relationships
    invoice: Mapped["PurchaseInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="purchase_invoice_items")
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship(back_populates="purchase_invoice_items")
    receipt_item: Mapped[Optional["PurchaseReceiptItem"]] = relationship(back_populates="invoice_items")
    return_against_item: Mapped[Optional["PurchaseInvoiceItem"]] = relationship(
        remote_side="PurchaseInvoiceItem.id", back_populates="debit_note_items",
        foreign_keys=[return_against_item_id]
    )
    debit_note_items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="PurchaseInvoiceItem.return_against_item_id"
    )

    # Table Constraints & Indices
    __table_args__ = (
        # Quantity and rate constraints that allow negative values for debit notes
        CheckConstraint(
            "(invoice_id IN (SELECT id FROM purchase_invoices WHERE is_return = false) AND quantity > 0) OR "
            "(invoice_id IN (SELECT id FROM purchase_invoices WHERE is_return = true) AND quantity < 0)",
            name="ck_pii_quantity_direction"
        ),

        CheckConstraint("rate >= 0", name="ck_pii_rate_non_negative"),

        Index("ix_pii_item", "item_id"),
        Index("ix_pii_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoiceItem item={self.item_id} qty={self.quantity} amount={self.amount} debit_note={self.invoice.is_return}>"

# ──────────────────────────────────────────────────────────────────────────────
# 5) LANDED COST VOUCHER
# ──────────────────────────────────────────────────────────────────────────────

class LCVAllocationMethodEnum(str, enum.Enum):
    QUANTITY = "QUANTITY"   # by qty (PR: accepted_qty; PI: quantity)
    VALUE    = "VALUE"      # by line amount
    EQUAL    = "EQUAL"      # equal split
    MANUAL   = "MANUAL"     # user-specified per line

class LCVChargeTypeEnum(str, enum.Enum):
    FREIGHT   = "FREIGHT"
    INSURANCE = "INSURANCE"
    DUTY      = "DUTY"
    HANDLING  = "HANDLING"
    OTHER     = "OTHER"

class StockSourceDocTypeEnum(str, enum.Enum):
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"   # only valid if update_stock = true (enforce in service)
# ──────────────────────────────────────────────────────────────────────────────
# Header: Landed Cost Voucher
# ──────────────────────────────────────────────────────────────────────────────

class LandedCostVoucher(BaseModel):
    """
    Distribute additional costs (freight/duty/etc.) onto PR/PI items to adjust valuation.
    """
    __tablename__ = "landed_cost_vouchers"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id:  Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),  nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, index=True)

    # e.g. "MAT-LCV-.YYYY.-00001" (generated in service)
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status:   Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False,
                                                        default=DocStatusEnum.DRAFT, index=True)
    allocation_method: Mapped["LCVAllocationMethodEnum"] = mapped_column(
        db.Enum(LCVAllocationMethodEnum), nullable=False, default=LCVAllocationMethodEnum.VALUE, index=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Denormalized for fast reads/validation
    charges_total:   Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0)
    allocated_total: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0)

    # Children
    charges: Mapped[List["LCVCharge"]] = relationship(
        back_populates="lcv", cascade="all, delete-orphan"
    )
    allocations: Mapped[List["LandedCostAllocation"]] = relationship(
        back_populates="lcv", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_lcv_branch_code"),
        Index("ix_lcv_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_lcv_company_posting_date", "company_id", "posting_date"),
        Index("ix_lcv_company_alloc_method", "company_id", "allocation_method"),
    )

    def __repr__(self) -> str:
        return f"<LCV code={self.code!r} status={self.doc_status} method={self.allocation_method}>"

# ──────────────────────────────────────────────────────────────────────────────
# Charges (freight, duty, etc.)
# ──────────────────────────────────────────────────────────────────────────────

class LCVCharge(BaseModel):
    __tablename__ = "lcv_charges"

    lcv_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("landed_cost_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_type: Mapped["LCVChargeTypeEnum"] = mapped_column(db.Enum(LCVChargeTypeEnum), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.String(140))
    amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False)

    # Optional expense account to credit (finance posting)
    expense_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True
    )

    lcv: Mapped["LandedCostVoucher"] = relationship(back_populates="charges")

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_lcvcharge_amount_pos"),
        Index("ix_lcvcharge_account", "expense_account_id"),
    )

    def __repr__(self) -> str:
        return f"<LCVCharge lcv={self.lcv_id} {self.charge_type} amount={self.amount}>"

# ──────────────────────────────────────────────────────────────────────────────
# Allocation lines (this replaces both "TargetItem" and explicit "SourceDocument")
# ──────────────────────────────────────────────────────────────────────────────

class LandedCostAllocation(BaseModel):
    """
    One row per affected source item line.
    Polymorphic pointer: (doc_type, document_item_id) -> PR item or stock PI item.
    """
    __tablename__ = "lcv_allocations"

    lcv_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("landed_cost_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    doc_type: Mapped["StockSourceDocTypeEnum"] = mapped_column(db.Enum(StockSourceDocTypeEnum), nullable=False, index=True)
    document_item_id: Mapped[int] = mapped_column(db.BigInteger, nullable=False, index=True)

    # Optional echoes (speed/reporting; populated in service)
    item_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("items.id"), nullable=True, index=True)
    uom_id:  Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"), nullable=True, index=True)

    # Basis captured at allocation time (audit/replay)
    basis_qty:     Mapped[Optional[float]] = mapped_column(db.Numeric(16, 6))
    basis_amount:  Mapped[Optional[float]] = mapped_column(db.Numeric(16, 6))

    # Final result for this line
    allocated_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0)

    lcv: Mapped["LandedCostVoucher"] = relationship(back_populates="allocations")

    __table_args__ = (
        UniqueConstraint("lcv_id", "doc_type", "document_item_id", name="uq_lcvalc_unique"),
        Index("ix_lcvalc_type_item", "doc_type", "document_item_id"),
        CheckConstraint("allocated_amount >= 0", name="ck_lcvalc_alloc_nonneg"),
    )

    def __repr__(self) -> str:
        return f"<LCVAlloc lcv={self.lcv_id} {self.doc_type}:{self.document_item_id} alloc={self.allocated_amount}>"