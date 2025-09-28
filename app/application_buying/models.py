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
# 2) PURCHASE RECEIPT (Stock only)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseReceipt(BaseModel):
    """
    A document that records the physical receipt of goods from a supplier.
    This document affects inventory stock but not the general ledger.
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

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[float] = mapped_column(db.Numeric(14, 4), nullable=False, default=0.0000)

    # Relationships
    supplier: Mapped["Party"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    items: Mapped[List["PurchaseReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pr_branch_code"),
        Index("ix_pr_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pr_company_supplier", "company_id", "supplier_id"),
        Index("ix_pr_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReceipt code={self.code!r} supplier={self.supplier_id} status={self.doc_status}>"


class PurchaseReceiptItem(BaseModel):
    """
    Represents an item line within a Purchase Receipt document.
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

    # Item Line Fields
    received_qty: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    accepted_qty: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Optional[float]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("CASE WHEN unit_price IS NULL THEN NULL ELSE accepted_qty * unit_price END", persisted=True),
        nullable=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    receipt: Mapped["PurchaseReceipt"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("received_qty > 0", name="ck_pri_received_pos"),
        CheckConstraint("accepted_qty >= 0 AND accepted_qty <= received_qty", name="ck_pri_accepted_valid"),

        Index("ix_pri_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReceiptItem id={self.id} item={self.item_id} acc={self.accepted_qty}>"


# ──────────────────────────────────────────────────────────────────────────────
# 3) PURCHASE INVOICE (Finance-only or Direct-with-stock)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseInvoice(BaseModel):
    """
    The supplier's financial invoice.
    It can either bill a prior receipt or act as a single document for both stock and finance.
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
    supplier: Mapped["Party"] = relationship()
    warehouse: Mapped[Optional["Warehouse"]] = relationship()
    items: Mapped[List["PurchaseInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pin_branch_code"),
        Index("ix_pin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pin_company_supplier", "company_id", "supplier_id"),
        Index("ix_pin_company_posting_date", "company_id", "posting_date"),
        Index("ix_pin_company_update_stock", "company_id", "update_stock"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoice code={self.code!r} supplier={self.supplier_id} stock={self.update_stock}>"


class PurchaseInvoiceItem(BaseModel):
    """
    Represents an item line within a Purchase Invoice document.
    """
    __tablename__ = "purchase_invoice_items"

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    # This is optional and can default to Item.base_uom in service logic if not provided
    uom_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                                  nullable=True, index=True)
    # Link to a previous PurchaseReceiptItem if this invoice is billing for a receipt
    receipt_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipt_items.id"),
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
    invoice: Mapped["PurchaseInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship()
    receipt_item: Mapped[Optional["PurchaseReceiptItem"]] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pii_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_pii_rate_nonneg"),
        Index("ix_pii_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseInvoiceItem id={self.id} item={self.item_id} qty={self.quantity}>"


# ──────────────────────────────────────────────────────────────────────────────
# 4) PURCHASE RETURN (Stock out)
# ──────────────────────────────────────────────────────────────────────────────
class PurchaseReturn(BaseModel):
    """
    A document that records the physical return of goods to a supplier.
    This reduces inventory stock and may be linked to a prior receipt or invoice.
    """
    __tablename__ = "purchase_returns"

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

    # Optional references to the original documents being returned against
    receipt_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipts.id"),
        nullable=True, index=True
    )
    invoice_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoices.id"),
        nullable=True, index=True
    )

    # Document Fields
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # Relationships
    supplier: Mapped["Party"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()
    receipt: Mapped[Optional["PurchaseReceipt"]] = relationship()
    invoice: Mapped[Optional["PurchaseInvoice"]] = relationship()
    items: Mapped[List["PurchaseReturnItem"]] = relationship(
        back_populates="purchase_return", cascade="all, delete-orphan"
    )

    # Table Constraints & Indices
    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_pret_branch_code"),
        Index("ix_pret_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_pret_company_supplier", "company_id", "supplier_id"),
        Index("ix_pret_company_posting_date", "company_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReturn code={self.code!r} supplier={self.supplier_id} status={self.doc_status}>"


class PurchaseReturnItem(BaseModel):
    """
    Represents an item line within a Purchase Return document.
    """
    __tablename__ = "purchase_return_items"

    # Foreign Keys
    purchase_return_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_returns.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    uom_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("units_of_measure.id"),
                                        nullable=False, index=True)
    # Optional links to the original item lines from either a receipt or an invoice
    receipt_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_receipt_items.id"),
        nullable=True, index=True
    )
    invoice_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("purchase_invoice_items.id"),
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
    purchase_return: Mapped["PurchaseReturn"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()
    receipt_item: Mapped[Optional["PurchaseReceiptItem"]] = relationship()
    invoice_item: Mapped[Optional["PurchaseInvoiceItem"]] = relationship()

    # Table Constraints & Indices
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_pret_qty_pos"),
        CheckConstraint("rate IS NULL OR rate >= 0", name="ck_pret_rate_nonneg"),
        UniqueConstraint("purchase_return_id", "item_id", "batch_number", name="uq_pret_item_batch"),
        Index("ix_pret_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseReturnItem id={self.id} item={self.item_id} qty={self.quantity}>"
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