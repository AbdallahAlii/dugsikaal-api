# app/application_buying/models.py
from __future__ import annotations

from typing import Optional, List
from datetime import datetime
import enum

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey, text

from config.database import db
from app.common.models.base import BaseModel, StatusEnum
from app.application_stock.stock_models import DocStatusEnum
from app.application_parties.parties_models import Party


# ──────────────────────────────────────────────────────────────────────────────
# 1) PURCHASE QUOTATION (RFQ / Quote)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseQuotation(BaseModel):
    """
    A Purchase Quotation (RFQ). No stock or GL impact.
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

    # Relationships (kept as-is)
    supplier: Mapped["Party"] = relationship()
    items: Mapped[List["PurchaseQuotationItem"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    branch: Mapped["Branch"] = relationship("Branch", back_populates="purchase_quotations")
    company: Mapped["Company"] = relationship("Company", back_populates="purchase_quotations")

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
    Line within a Purchase Quotation.
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

    # Fields
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )

    # Relationships (kept as-is)
    quotation: Mapped["PurchaseQuotation"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pqi_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_pqi_rate_nonneg"),
        Index("ix_pqi_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseQuotationItem id={self.id} item={self.item_id} qty={self.quantity}>"


# ──────────────────────────────────────────────────────────────────────────────
# 2) PURCHASE RECEIPT (Stock only) — ERPNext style (returns are negative)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseReceipt(BaseModel):
    """
    Records physical receipt/return of goods.
    Returns are represented by negative quantities and is_return=True.
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
    # Header warehouse required
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id"),
                                              nullable=True, index=True)

    # Self return reference (ERPNext style)
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id"), nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)

    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)

    # Return Management
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships (kept as-is)
    branch: Mapped["Branch"] = relationship("Branch", back_populates="purchase_receipts")
    company: Mapped["Company"] = relationship("Company", back_populates="purchase_receipts")
    supplier: Mapped["Party"] = relationship("Party", back_populates="purchase_receipts")
    warehouse: Mapped["Warehouse"] = relationship("Warehouse", back_populates="purchase_receipts")
    created_by: Mapped["User"] = relationship(back_populates="created_purchase_receipts")

    items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )
    invoices: Mapped[List["PurchaseInvoice"]] = relationship(
        back_populates="receipt",
        foreign_keys="PurchaseInvoice.receipt_id",
        cascade="all, delete-orphan",
    )

    return_against: Mapped[Optional["PurchaseReceipt"]] = relationship(
        remote_side="PurchaseReceipt.id", back_populates="returns",
        foreign_keys=[return_against_id]
    )
    returns: Mapped[List["PurchaseReceipt"]] = relationship(
        back_populates="return_against",
        foreign_keys="PurchaseReceipt.return_against_id"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pr_branch_code"),
        Index("ix_pr_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pr_company_supplier", "company_id", "supplier_id"),
        Index("ix_pr_company_posting_date", "company_id", "posting_date"),
        Index("ix_pr_is_return", "is_return"),

        # Require original for returns
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_pr_return_requires_original",
        ),

        # ERPNext-style sign rule: receipts positive, returns negative
        CheckConstraint(
            """
            (
                is_return = false
                AND total_amount >= 0
            )
            OR
            (
                is_return = true
                AND total_amount <= 0
            )
            """,
            name="ck_pr_amount_sign_by_return",
        ),
    )


    def __repr__(self) -> str:
        return f"<PurchaseReceipt {self.code} supplier={self.supplier_id} return={self.is_return}>"


class PurchaseReceiptItem(BaseModel):
    """
    Line within a Purchase Receipt.
    Returns store negative quantities.
    """
    __tablename__ = "purchase_receipt_items"

    # Foreign Keys
    receipt_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)

    # NEW: per-line warehouse (nullable; header warehouse is required)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id"), nullable=True, index=True
    )

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

    # Tracks quantity returned against this **original** (non-return) line
    returned_qty: Mapped[float] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0.000,
        comment="Total quantity returned against this item line"
    )

    # Relationships (kept as-is + new nullable warehouse relationship)
    receipt: Mapped["PurchaseReceipt"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="purchase_receipt_items")
    uom: Mapped["UnitOfMeasure"] = relationship(back_populates="purchase_receipt_items")
    warehouse: Mapped[Optional["Warehouse"]] = relationship()

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

    __table_args__ = (
        # Direction by parent is_return
        CheckConstraint(
            "(receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = false) "
            " AND received_qty > 0 AND accepted_qty > 0) OR "
            "(receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = true) "
            " AND received_qty < 0 AND accepted_qty < 0)",
            name="ck_pri_qty_direction",
        ),
        CheckConstraint(
            "ABS(accepted_qty) <= ABS(received_qty)",
            name="ck_pri_accepted_leq_received",
        ),
        # returned_qty is only meaningful on non-return source lines
        CheckConstraint(
            "("
            " receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = false)"
            " AND returned_qty >= 0"
            " AND returned_qty <= accepted_qty"
            ") OR ("
            " receipt_id IN (SELECT id FROM purchase_receipts WHERE is_return = true)"
            " AND returned_qty = 0"
            ")",
            name="ck_pri_returned_qty_logic",
        ),
        Index("ix_pri_item", "item_id"),
        Index("ix_pri_warehouse", "warehouse_id"),
        Index("ix_pri_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReceiptItem item={self.item_id} qty={self.accepted_qty} return={self.receipt.is_return}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) PURCHASE INVOICE (Finance + Optional Stock) — ERPNext style
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseInvoice(BaseModel):
    """
    Supplier financial invoice (or Return/Debit Note when is_return=True).
    Returns use negative quantities/amounts — no separate model.
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

    # Return against reference
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id"), nullable=True, index=True
    )

    # Link to originating receipt (clears GRNI)
    receipt_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id"),
        nullable=True, index=True,
        comment="The Purchase Receipt this invoice is generated from (clears GRNI)."
    )

    # Core accounting linkage (kept as-is; nullable per your code)
    payable_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id"), nullable=True, index=True,
        comment="Accounts Payable (Credit) account."
    )

    # Payment-on-invoice (ERPNext style)
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

    # Only this flag — no is_debit_note
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # Finance Fields
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    paid_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    outstanding_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)
    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships (kept as-is)
    company: Mapped["Company"] = relationship(back_populates="purchase_invoices")
    branch: Mapped["Branch"] = relationship(back_populates="purchase_invoices")
    created_by: Mapped["User"] = relationship(back_populates="created_purchase_invoices")
    supplier: Mapped["Party"] = relationship(back_populates="purchase_invoices")
    warehouse: Mapped[Optional["Warehouse"]] = relationship(back_populates="purchase_invoices")
    items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    receipt: Mapped[Optional["PurchaseReceipt"]] = relationship(
        back_populates="invoices",
        foreign_keys=[receipt_id]
    )

    payable_account: Mapped["Account"] = relationship(
        foreign_keys=[payable_account_id], back_populates="purchase_invoices_payable"
    )

    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship(back_populates="purchase_invoices")
    cash_bank_account: Mapped[Optional["Account"]] = relationship(
        foreign_keys=[cash_bank_account_id], back_populates="purchase_invoices_cash_bank"
    )

    return_against: Mapped[Optional["PurchaseInvoice"]] = relationship(
        remote_side="PurchaseInvoice.id", back_populates="debit_notes",
        foreign_keys=[return_against_id]
    )
    # NOTE: keeping name 'debit_notes' to match your existing relations
    debit_notes: Mapped[List["PurchaseInvoice"]] = relationship(
        back_populates="return_against",
        foreign_keys="PurchaseInvoice.return_against_id"
    )

    assets: Mapped[List["Asset"]] = relationship("Asset", back_populates="purchase_invoice_rel")


    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pin_branch_code"),
        Index("ix_pin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pin_company_supplier", "company_id", "supplier_id"),
        Index("ix_pin_company_posting_date", "company_id", "posting_date"),
        Index("ix_pin_company_update_stock", "company_id", "update_stock"),
        Index("ix_pin_is_return", "is_return"),
        Index("ix_pin_receipt_id", "receipt_id"),
        Index("ix_pin_payable_account", "payable_account_id"),
        Index("ix_pin_mode_of_payment", "mode_of_payment_id"),
        Index("ix_pin_cash_bank_account", "cash_bank_account_id"),
        Index("ix_pin_warehouse", "warehouse_id"),

        # Return requires original (ERPNext pattern)
        CheckConstraint(
            "(is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)",
            name="ck_pin_return_requires_original",
        ),

        # Core amount relationship (works for positive or negative)
        CheckConstraint(
            "total_amount = paid_amount + outstanding_amount",
            name="ck_pin_amount_consistency",
        ),

        # Sign-by-return (ERPNext-style):
        # - Normal invoices: totals and balances are >= 0
        # - Returns (debit notes): totals and balances are <= 0
        CheckConstraint(
            """
            (
                is_return = false
                AND total_amount >= 0
                AND paid_amount >= 0
                AND outstanding_amount >= 0
            )
            OR
            (
                is_return = true
                AND total_amount <= 0
                AND paid_amount <= 0
                AND outstanding_amount <= 0
            )
            """,
            name="ck_pin_amounts_sign_by_return",
        ),

        # Payment consistency (supports refunds from supplier with negative paid_amount):
        # - No payment: paid_amount = 0 → no MOP / cash-bank
        # - Normal invoice: paid_amount > 0 → require MOP + cash-bank
        # - Return: paid_amount < 0 (refund from supplier) → require MOP + cash-bank
        CheckConstraint(
            """
            (
                paid_amount = 0
                AND mode_of_payment_id IS NULL
                AND cash_bank_account_id IS NULL
            )
            OR
            (
                is_return = false
                AND paid_amount > 0
                AND mode_of_payment_id IS NOT NULL
                AND cash_bank_account_id IS NOT NULL
            )
            OR
            (
                is_return = true
                AND paid_amount < 0
                AND mode_of_payment_id IS NOT NULL
                AND cash_bank_account_id IS NOT NULL
            )
            """,
            name="ck_pin_payment_consistency_signed",
        ),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoice {self.code} supplier={self.supplier_id} paid={self.paid_amount}/{self.total_amount}>"


class PurchaseInvoiceItem(BaseModel):
    """
    Line within a Purchase Invoice.
    Returns use negative quantities; standard invoices positive.
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

    # Optional link to receipt item (GRNI clearing flow)
    receipt_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipt_items.id"),
        nullable=True, index=True
    )

    # NEW: per-line warehouse (nullable; used when update_stock=True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id"),
        nullable=True, index=True
    )

    # Return against item reference
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoice_items.id"), nullable=True, index=True
    )

    # Line amounts (NEGATIVE for returns)
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[float] = mapped_column(db.Numeric(12, 4), nullable=False)
    amount: Mapped[float] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Denormalized: total returned against this standard line (not used on return lines)
    returned_qty: Mapped[float] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0.000,
        comment="Total quantity returned against this standard Invoice Item (via linked returns)."
    )

    # Relationships (kept as-is + new nullable warehouse relationship)
    invoice: Mapped["PurchaseInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="purchase_invoice_items")
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship(back_populates="purchase_invoice_items")
    receipt_item: Mapped[Optional["PurchaseReceiptItem"]] = relationship(back_populates="invoice_items")
    warehouse: Mapped[Optional["Warehouse"]] = relationship()

    return_against_item: Mapped[Optional["PurchaseInvoiceItem"]] = relationship(
        remote_side="PurchaseInvoiceItem.id", back_populates="debit_note_items",
        foreign_keys=[return_against_item_id]
    )
    # NOTE: keep naming to match your existing relations
    debit_note_items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="PurchaseInvoiceItem.return_against_item_id"
    )

    __table_args__ = (
        # Direction depends on parent is_return
        CheckConstraint(
            "(invoice_id IN (SELECT id FROM purchase_invoices WHERE is_return = false) "
            " AND quantity > 0) OR "
            "(invoice_id IN (SELECT id FROM purchase_invoices WHERE is_return = true) "
            " AND quantity < 0)",
            name="ck_pii_quantity_direction",
        ),
        CheckConstraint("rate >= 0", name="ck_pii_rate_non_negative"),
        Index("ix_pii_item", "item_id"),
        Index("ix_pii_warehouse", "warehouse_id"),
        Index("ix_pii_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoiceItem item={self.item_id} qty={self.quantity} amount={self.amount} debit_note={self.invoice.is_return}>"


# ──────────────────────────────────────────────────────────────────────────────
# 4) LANDED COST VOUCHER (same structure, tidy)
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
    PURCHASE_INVOICE = "PURCHASE_INVOICE"   # only valid if update_stock = true (enforced in service)


class LandedCostVoucher(BaseModel):
    """
    Distribute additional costs (freight/duty/etc.) onto PR/PI items to adjust valuation.
    """
    __tablename__ = "landed_cost_vouchers"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id:  Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),  nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, index=True)

    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status:   Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum), nullable=False,
                                                        default=DocStatusEnum.DRAFT, index=True)
    allocation_method: Mapped["LCVAllocationMethodEnum"] = mapped_column(
        db.Enum(LCVAllocationMethodEnum), nullable=False, default=LCVAllocationMethodEnum.VALUE, index=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Denormalized
    charges_total:   Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0)
    allocated_total: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0)

    # Children
    charges: Mapped[List["LCVCharge"]] = relationship(back_populates="lcv", cascade="all, delete-orphan")
    allocations: Mapped[List["LandedCostAllocation"]] = relationship(back_populates="lcv", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_lcv_branch_code"),
        Index("ix_lcv_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_lcv_company_posting_date", "company_id", "posting_date"),
        Index("ix_lcv_company_alloc_method", "company_id", "allocation_method"),
    )

    def __repr__(self) -> str:
        return f"<LCV code={self.code!r} status={self.doc_status} method={self.allocation_method}>"


class LCVCharge(BaseModel):
    __tablename__ = "lcv_charges"

    lcv_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("landed_cost_vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_type: Mapped["LCVChargeTypeEnum"] = mapped_column(db.Enum(LCVChargeTypeEnum), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(db.String(140))
    amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False)

    # Optional expense account to credit
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
