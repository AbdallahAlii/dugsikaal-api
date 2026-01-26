# app/application_selling/model.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, TenantMixin
from app.application_stock.stock_models import DocStatusEnum
from app.application_parties.parties_models import Party


# ──────────────────────────────────────────────────────────────────────────────
# 1) SALES QUOTATION (Quote)
# ──────────────────────────────────────────────────────────────────────────────
class SalesQuotation(BaseModel, TenantMixin):
    """
    Sales Quotation / Quote (ERPNext-like).
    - Used before Sales Invoice.
    - Optional education context (student/program) if you want to quote fees.
    """
    __tablename__ = "sales_quotations"

    # ---- Core links ----
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("parties.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Optional pricing context (if you support ItemPrice)
    selling_price_list_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("price_lists.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Optional education context (only when quote is for student fees)
    student_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    program_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # ---- Document fields ----
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum),
        nullable=False,
        default=DocStatusEnum.DRAFT,
        index=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)

    # ---- Relationships ----
    customer: Mapped["Party"] = relationship()
    selling_price_list: Mapped[Optional["PriceList"]] = relationship("PriceList", lazy="joined")

    student: Mapped[Optional["Student"]] = relationship("Student", lazy="joined")
    program: Mapped[Optional["Program"]] = relationship("Program", lazy="joined")

    items: Mapped[List["SalesQuotationItem"]] = relationship(
        back_populates="quotation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # Code uniqueness inside one company+branch (like ERPNext naming series per branch)
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sq_company_branch_code"),

        # Common filters
        Index("ix_sq_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sq_company_customer", "company_id", "customer_id"),
        Index("ix_sq_company_posting_date", "company_id", "posting_date"),
        Index("ix_sq_company_student", "company_id", "student_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesQuotation id={self.id} code={self.code!r} customer_id={self.customer_id} status={self.doc_status.value}>"


class SalesQuotationItem(BaseModel, TenantMixin):
    """
    Quotation line items.
    - Quantity must be > 0.
    - Amount is computed by DB.
    """
    __tablename__ = "sales_quotation_items"

    quotation_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_quotations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    uom_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    quantity: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(db.Numeric(12, 4), nullable=False)

    amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )

    quotation: Mapped["SalesQuotation"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped["UnitOfMeasure"] = relationship()

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sqi_qty_pos"),
        CheckConstraint("rate >= 0", name="ck_sqi_rate_nonneg"),
        Index("ix_sqi_company_quotation", "company_id", "quotation_id"),
        Index("ix_sqi_item", "item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesQuotationItem id={self.id} quotation_id={self.quotation_id} item_id={self.item_id} qty={self.quantity}>"

# ──────────────────────────────────────────────────────────────────────────────
# 2) SALES DELIVERY NOTE (Stock out)
# ──────────────────────────────────────────────────────────────────────────────
class SalesDeliveryNote(BaseModel):
    __tablename__ = "sales_delivery_notes"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("parties.id"), nullable=False, index=True)

    # Returns
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_notes.id"), nullable=True, index=True
    )

    # Core
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    )
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    total_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # Relationships
    customer: Mapped["Party"] = relationship()
    items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(
        back_populates="delivery_note", cascade="all, delete-orphan"
    )

    return_against: Mapped[Optional["SalesDeliveryNote"]] = relationship(
        remote_side="SalesDeliveryNote.id",
        back_populates="returns",
        foreign_keys=[return_against_id],
    )
    returns: Mapped[List["SalesDeliveryNote"]] = relationship(
        back_populates="return_against",
        foreign_keys="SalesDeliveryNote.return_against_id",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sdn_branch_code"),
        Index("ix_sdn_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sdn_company_customer", "company_id", "customer_id"),
        Index("ix_sdn_company_posting_date", "company_id", "posting_date"),
        Index("ix_sdn_is_return", "is_return"),
        # Strong consistency:
        # - if is_return=true => must have return_against_id
        # - if is_return=false => must NOT have return_against_id
        CheckConstraint(
            """
            (
              is_return = true AND return_against_id IS NOT NULL
            )
            OR
            (
              is_return = false AND return_against_id IS NULL
            )
            """,
            name="ck_sdn_return_link_consistency",
        ),
    )

    def __repr__(self) -> str:
        return f"<SalesDeliveryNote code={self.code!r} customer={self.customer_id} return={self.is_return}>"


class SalesDeliveryNoteItem(BaseModel):
    __tablename__ = "sales_delivery_note_items"

    delivery_note_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("sales_delivery_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    uom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Real posting warehouse (per-line, required on DN)
    warehouse_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Returns linkage (line-to-line)
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_delivery_note_items.id"), nullable=True, index=True
    )

    # Quantities & price
    delivered_qty: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(12, 4), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(
        db.Numeric(14, 4),
        db.Computed(
            "CASE WHEN unit_price IS NULL THEN NULL ELSE delivered_qty * unit_price END",
            persisted=True,
        ),
        nullable=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # Relationships
    delivery_note: Mapped["SalesDeliveryNote"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship()

    return_against_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship(
        remote_side="SalesDeliveryNoteItem.id",
        back_populates="return_items",
        foreign_keys=[return_against_item_id],
    )
    return_items: Mapped[List["SalesDeliveryNoteItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="SalesDeliveryNoteItem.return_against_item_id",
    )

    # Link to invoice items (optional)
    invoice_items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="delivery_note_item",
        foreign_keys="SalesInvoiceItem.delivery_note_item_id",
    )

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
# 2) SALES INVOICE (ERPNext style) + Fee integration
# ──────────────────────────────────────────────────────────────────────────────
class SalesInvoice(BaseModel, TenantMixin):
    """
    Sales Invoice (ERPNext-like).
    - Supports service items (fees) and stock items.
    - If many lines use the same warehouse, user selects warehouse once on header.
      (Item warehouse_id can stay NULL for non-stock lines or if header warehouse is used.)
    """
    __tablename__ = "sales_invoices"

    # ---- Core links ----
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("parties.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    debit_to_account_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Optional header warehouse (UI convenience)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Optional default warehouse for this invoice; item rows may inherit via service layer."
    )

    # ---- Fee integration (minimal) ----
    is_fee_invoice: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False, index=True)

    student_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Keep program_id because your UI wants it (ERPNext-like)
    program_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_programs.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Optional: helps correctness if student changes program later
    program_enrollment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_program_enrollments.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Created from Fee Schedule bulk-run
    fee_schedule_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_schedules.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # ---- Return/Credit note ----
    return_against_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    is_return: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # ---- VAT (optional; keep light constraints, service layer decides) ----
    vat_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    vat_rate: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(6, 3), nullable=True)
    vat_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    # ---- Payment hint fields (optional) ----
    mode_of_payment_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("modes_of_payment.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    cash_bank_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # ---- Document fields ----
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)
    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)

    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum),
        nullable=False,
        default=DocStatusEnum.DRAFT,
        index=True
    )

    update_stock: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True,
        comment="If true, service layer will affect stock/GL accordingly."
    )

    total_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))
    paid_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))
    outstanding_amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 4), nullable=False, default=Decimal("0.0000"))

    due_date: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(db.Text)
    send_sms: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    # ---- Relationships ----
    customer: Mapped["Party"] = relationship()
    debit_to_account: Mapped["Account"] = relationship(foreign_keys=[debit_to_account_id])

    warehouse: Mapped[Optional["Warehouse"]] = relationship("Warehouse", lazy="joined")

    vat_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[vat_account_id])
    mode_of_payment: Mapped[Optional["ModeOfPayment"]] = relationship()
    cash_bank_account: Mapped[Optional["Account"]] = relationship(foreign_keys=[cash_bank_account_id])

    student: Mapped[Optional["Student"]] = relationship("Student", lazy="joined")
    program: Mapped[Optional["Program"]] = relationship("Program", lazy="joined")
    program_enrollment: Mapped[Optional["ProgramEnrollment"]] = relationship("ProgramEnrollment", lazy="joined")
    fee_schedule: Mapped[Optional["FeeSchedule"]] = relationship("FeeSchedule", lazy="joined")

    items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    return_against: Mapped[Optional["SalesInvoice"]] = relationship(
        remote_side="SalesInvoice.id",
        back_populates="credit_notes",
        foreign_keys=[return_against_id],
    )
    credit_notes: Mapped[List["SalesInvoice"]] = relationship(
        back_populates="return_against",
        foreign_keys="SalesInvoice.return_against_id",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "branch_id", "code", name="uq_sin_company_branch_code"),

        # Protect against double-run (schedule + student) duplicates
        # Note: NULL fee_schedule_id will not block normal invoices in Postgres.
        UniqueConstraint(
            "company_id", "fee_schedule_id", "student_id",
            name="uq_sin_fee_schedule_student_once",
        ),

        # Common filters
        Index("ix_sin_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_sin_company_customer", "company_id", "customer_id"),
        Index("ix_sin_company_posting_date", "company_id", "posting_date"),
        Index("ix_sin_company_due_date", "company_id", "due_date"),
        Index("ix_sin_company_fee_schedule", "company_id", "fee_schedule_id"),
        Index("ix_sin_company_student", "company_id", "student_id", "posting_date"),
        Index("ix_sin_company_program", "company_id", "program_id", "posting_date"),

        # Keep DB rules light (service layer handles business complexity)
        # Core amount relationship (works for positive or negative)
        CheckConstraint(
            "total_amount = paid_amount + outstanding_amount",
            name="ck_sin_amount_consistency",
        ),

        # Sign-by-return (ERPNext-style)
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
            name="ck_sin_amounts_sign_by_return",
        ),

        # CORRECTED: Payment consistency - allows both direct payments AND Payment Entry payments
        CheckConstraint(
            """
            (
                -- Case 1: Unpaid invoice
                paid_amount = 0
                AND mode_of_payment_id IS NULL
                AND cash_bank_account_id IS NULL
            )
            OR
            (
                -- Case 2: Regular invoice with payment (direct OR via Payment Entry)
                is_return = false
                AND paid_amount > 0
                AND (
                    -- Either direct payment details exist
                    (mode_of_payment_id IS NOT NULL AND cash_bank_account_id IS NOT NULL)
                    OR
                    -- OR payment was made via Payment Entry (details remain NULL)
                    (mode_of_payment_id IS NULL AND cash_bank_account_id IS NULL)
                )
            )
            OR
            (
                -- Case 3: Credit note with refund (direct OR via Payment Entry)
                is_return = true
                AND paid_amount < 0
                AND (
                    -- Either direct refund details exist
                    (mode_of_payment_id IS NOT NULL AND cash_bank_account_id IS NOT NULL)
                    OR
                    -- OR refund was made via Payment Entry (details remain NULL)
                    (mode_of_payment_id IS NULL AND cash_bank_account_id IS NULL)
                )
            )
            """,
            name="ck_sin_payment_consistency_signed",
        ),

        # VAT consistency
        CheckConstraint(
            """
            (
                vat_amount = 0
                AND vat_account_id IS NULL
                AND vat_rate IS NULL
            )
            OR
            (
                vat_amount <> 0
                AND vat_account_id IS NOT NULL
                AND vat_rate IS NOT NULL
            )
            """,
            name="ck_sin_vat_consistency_signed",
        ),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoice {self.code} customer={self.customer_id} paid={self.paid_amount}/{self.total_amount}>"


class SalesInvoiceItem(BaseModel, TenantMixin):
    """
    Sales Invoice line items.
    - warehouse_id is optional because:
        (1) fee/service items don't need warehouse
        (2) invoice header may provide default warehouse via service layer
    """
    __tablename__ = "sales_invoice_items"

    invoice_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    uom_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Optional per-line warehouse (nullable for services/fees)
    warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Fee line grouping (when lines are generated from Fee Schedule)
    fee_category_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("edu_fee_categories.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Filled when this line came from Fee Schedule/Structure."
    )

    # Return mapping at line level (credit note lines)
    return_against_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("sales_invoice_items.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    quantity: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(db.Numeric(12, 4), nullable=False)

    amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 4),
        db.Computed("quantity * rate", persisted=True),
        nullable=False
    )

    income_account_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    cost_center_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("cost_centers.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    # ---- Relationships ----
    invoice: Mapped["SalesInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    uom: Mapped[Optional["UnitOfMeasure"]] = relationship()
    warehouse: Mapped[Optional["Warehouse"]] = relationship("Warehouse", lazy="joined")

    fee_category: Mapped[Optional["FeeCategory"]] = relationship("FeeCategory", lazy="joined")

    return_against_item: Mapped[Optional["SalesInvoiceItem"]] = relationship(
        remote_side="SalesInvoiceItem.id",
        back_populates="credit_note_items",
        foreign_keys=[return_against_item_id],
    )
    credit_note_items: Mapped[List["SalesInvoiceItem"]] = relationship(
        back_populates="return_against_item",
        foreign_keys="SalesInvoiceItem.return_against_item_id",
    )
    delivery_note_item_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("sales_delivery_note_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Links invoice item to delivery note item (for stock reconciliation)."
    )
    delivery_note_item: Mapped[Optional["SalesDeliveryNoteItem"]] = relationship(
        back_populates="invoice_items",
        foreign_keys=[delivery_note_item_id],
    )

    __table_args__ = (
        # Light + safe rules
        CheckConstraint("rate >= 0", name="ck_sii_rate_nonneg"),
        CheckConstraint("quantity <> 0", name="ck_sii_qty_non_zero"),

        # Common filters
        Index("ix_sii_company_invoice", "company_id", "invoice_id"),
        Index("ix_sii_item", "item_id"),
        Index("ix_sii_fee_category", "fee_category_id"),
        Index("ix_sii_warehouse", "warehouse_id"),
        Index("ix_sii_return_against", "return_against_item_id"),
    )

    def __repr__(self) -> str:
        return f"<SalesInvoiceItem id={self.id} invoice_id={self.invoice_id} item_id={self.item_id} qty={self.quantity} amount={self.amount}>"
