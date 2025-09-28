from __future__ import annotations

from decimal import Decimal
from typing import Optional, List
from datetime import datetime, date
import enum

from sqlalchemy import UniqueConstraint, Index, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


# --- 1. Global Document Registry & Enums ---
class StockReconciliationPurpose(str, enum.Enum):
    OPENING_STOCK = "Opening Stock"
    STOCK_RECONCILIATION = "Stock Reconciliation"

class DocumentDomain(str, enum.Enum):
    """Domain to categorize document types."""
    INVENTORY = "Inventory"
    FINANCE = "Finance"
    ASSETS = "Assets"
    PAYROLL = "Payroll"
    OTHER = "Other"

class SLEAdjustmentType(str, enum.Enum):
    NORMAL = "NORMAL"                 # standard PR/DN/Stock Entry
    LCV = "LCV"                       # landed cost repost
    RECONCILIATION = "RECONCILIATION" # stock reconciliation
    REVERSAL = "REVERSAL"             # reversal row (system-generated)
    RETURN = "RETURN"                 # purchase/sales return
    TRANSFER = "TRANSFER"             # material transfer
class DocStatusEnum(str, enum.Enum):
    """
    Centralized enumeration for all document statuses across the system.
    This includes universal statuses (Draft, Submitted, Cancelled) and
    specialized financial/lifecycle statuses (Paid, Overdue, etc.).
    """
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    CANCELLED = "Cancelled"
    # --- Financial/Lifecycle Statuses ---
    UNPAID = "Unpaid"
    PARTIALLY_PAID = "Partially Paid"
    PAID = "Paid"
    OVERDUE = "Overdue"
    RETURNED = "Returned"

class StockEntryType(str, enum.Enum):
    """
    Specific enum for internal Stock Entry documents.
    Used for business logic within the stock module itself.
    """
    MATERIAL_RECEIPT = "Material Receipt"
    MATERIAL_ISSUE = "Material Issue"
    MATERIAL_TRANSFER = "Material Transfer"
    STOCK_ADJUSTMENT = "Stock Adjustment"
    STOCK_RECONCILIATION = "Stock Reconciliation"
    MANUFACTURE = "Manufacture"


class DocumentType(BaseModel):
    """
    System registry for all document kinds. This is a lookup table
    for linking ledgers to any source document.
    """
    __tablename__ = "document_types"

    code: Mapped[str] = mapped_column(db.String(80), nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(db.String(120), nullable=False)
    domain: Mapped[DocumentDomain] = mapped_column(
        db.Enum(DocumentDomain, name="document_domain_enum"), nullable=False, index=True
    )
    affects_stock: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    affects_gl: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    status: Mapped[StatusEnum] = mapped_column(db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE)

    def __repr__(self) -> str:
        return f"<DocumentType id={self.id} code={self.code!r} stock={self.affects_stock} gl={self.affects_gl}>"

# --- 2. Warehouse & Bin Models ---

class Warehouse(BaseModel):
    """
    Tree:
      - Company Root (group):        is_group=True,  branch_id NULL, parent_id NULL
      - Branch Group (group):        is_group=True,  branch_id set,  parent_id = company root
      - Physical Warehouse (leaf):   is_group=False, branch_id set,  parent_id = branch group

    Only leaf nodes are stock locations.
    """
    __tablename__ = "warehouses"

    # Keep global unique or switch to per-company (see __table_args__)
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, unique=True, index=True)

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(db.String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    is_group: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    parent_warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )

    # Relationships
    company: Mapped["Company"] = relationship("Company")
    branch:  Mapped[Optional["Branch"]] = relationship("Branch")

    parent_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse",
        remote_side="Warehouse.id",
        back_populates="child_warehouses",
    )
    child_warehouses: Mapped[List["Warehouse"]] = relationship(
        "Warehouse",
        back_populates="parent_warehouse",
        # No delete-orphan / passive_deletes: we want RESTRICT semantics
    )

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum), nullable=False, default=StatusEnum.ACTIVE, index=True
    )

    __table_args__ = (
        # Names unique within a branch (root group has branch_id NULL)
        UniqueConstraint("company_id", "branch_id", "name", name="uq_wh_company_branch_name"),
        # If you prefer sibling-unique instead, swap the line above for:
        # UniqueConstraint("company_id", "parent_warehouse_id", "name", name="uq_wh_parent_name"),

        Index("ix_wh_company_branch", "company_id", "branch_id"),
        Index("ix_wh_parent", "parent_warehouse_id"),
        Index("ix_wh_group_active", "company_id", "is_group", "status"),

        # Physical warehouses must belong to a branch AND have a parent
        CheckConstraint(
            "(is_group = FALSE AND branch_id IS NOT NULL AND parent_warehouse_id IS NOT NULL) "
            "OR (is_group = TRUE)",
            name="ck_wh_leaf_requires_branch_and_parent",
        ),
        # Safety: no self-parenting
        CheckConstraint("id IS NULL OR id <> parent_warehouse_id", name="ck_wh_not_self_parent"),

        # If you want per-company unique codes instead of global unique:
        # UniqueConstraint("company_id", "code", name="uq_wh_company_code"),
    )

    def __repr__(self) -> str:
        return (f"<Warehouse id={self.id} company={self.company_id} branch={self.branch_id} "
                f"is_group={self.is_group} name={self.name!r}>")


class Bin(BaseModel):
    """
    Stock snapshot (quant) per item per warehouse.
    Updated only by stock services.
    """
    __tablename__ = "bins"

    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id", ondelete="RESTRICT"),
                                            nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"), nullable=False,
                                         index=True)
    warehouse_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
                                              nullable=False, index=True)

    # Use Decimal-friendly Numeric; annotate as Decimal to avoid float drift
    actual_qty: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False, default=Decimal("0"))
    reserved_qty: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False, default=Decimal("0"))
    ordered_qty: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False, default=Decimal("0"))
    valuation_rate: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False, default=Decimal("0"))

    projected_qty: Mapped[Decimal] = mapped_column(
        db.Numeric(18, 6),
        db.Computed("actual_qty - reserved_qty + ordered_qty", persisted=True)
    )

    # Optional: keeps reports fast; it’s just actual_qty * valuation_rate
    stock_value: Mapped[Decimal] = mapped_column(
        db.Numeric(18, 6),
        db.Computed("actual_qty * valuation_rate", persisted=True)
    )

    company: Mapped["Company"] = relationship("Company")
    item: Mapped["Item"] = relationship(back_populates="bins")
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_bin_company_code"),
        UniqueConstraint("company_id", "item_id", "warehouse_id", name="uq_bin_location"),
        Index("idx_bin_item_warehouse", "item_id", "warehouse_id"),
        Index("idx_bin_company_warehouse", "company_id", "warehouse_id"),
    )

    def __repr__(self) -> str:
        return f"<Bin item={self.item_id} wh={self.warehouse_id} qty={self.actual_qty}>"

# --- 2. Stock Entry Models (The transaction documents) ---


class StockEntry(BaseModel):
    """Document representing a stock transaction (receipt, issue, transfer, etc.)."""
    __tablename__ = "stock_entries"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Human-readable series code (e.g., "SE-2025-00001")
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    # Unified doc status enum used across your system
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum), nullable=False, default=DocStatusEnum.DRAFT, index=True
    )

    # Keep timezone-aware; you already standardized on tz-aware ledgers
    posting_date: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, index=True
    )

    stock_entry_type: Mapped[StockEntryType] = mapped_column(
        db.Enum(StockEntryType), nullable=False, index=True
    )

    # Children
    items: Mapped[list["StockEntryItem"]] = relationship(
        back_populates="stock_entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # You previously used unique(code). If you prefer scope-specific uniqueness,
        # swap for ('company_id','branch_id','code'). Keeping your original:
        UniqueConstraint("code", name="uq_stock_entry_code"),
        # Helpful composite indexes for common queries:
        Index("idx_se_company_posting", "company_id", "posting_date"),
        Index("idx_se_branch_posting", "branch_id", "posting_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<StockEntry id={self.id} type={self.stock_entry_type!r} "
            f"company={self.company_id} status={self.doc_status}>"
        )


class StockEntryItem(BaseModel):
    """
    Line on a Stock Entry document.

    Semantics:
      - Material Receipt:   source_warehouse_id = NULL,        target_warehouse_id = required
      - Material Issue:     source_warehouse_id = required,    target_warehouse_id = NULL
      - Material Transfer:  source_warehouse_id = required,    target_warehouse_id = required
    """
    __tablename__ = "stock_entry_items"

    # Foreign keys
    stock_entry_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("stock_entries.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    source_warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )
    target_warehouse_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True, index=True
    )
    uom_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Core numeric fields (Decimal-safe)
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False)
    # Rate is kept generic so you can use it as “basic_rate”/incoming/outgoing contextually in services
    rate: Mapped[Decimal] = mapped_column(db.Numeric(18, 6), nullable=False, default=Decimal("0"))
    # Persisted computed amount keeps reporting snappy
    amount: Mapped[Decimal] = mapped_column(
        db.Numeric(18, 6),
        db.Computed("quantity * rate", persisted=True)
    )

    # Relationships
    stock_entry: Mapped["StockEntry"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship("Item")
    source_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse", foreign_keys=[source_warehouse_id]
    )
    target_warehouse: Mapped[Optional["Warehouse"]] = relationship(
        "Warehouse", foreign_keys=[target_warehouse_id]
    )
    uom: Mapped["UnitOfMeasure"] = relationship("UnitOfMeasure")

    __table_args__ = (
        # Fast lookups by movement side & item
        Index("idx_sei_item_source_wh", "item_id", "source_warehouse_id"),
        Index("idx_sei_item_target_wh", "item_id", "target_warehouse_id"),
        # Common parent/line fetch
        Index("idx_sei_entry_item", "stock_entry_id", "item_id"),
        # Useful when analyzing inter-warehouse flows
        Index("idx_sei_src_tgt", "source_warehouse_id", "target_warehouse_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StockEntryItem id={self.id} item={self.item_id} qty={self.quantity} "
            f"from={self.source_warehouse_id} to={self.target_warehouse_id}>"
        )

# --- 3. The Ledger (The final record of stock movement) ---

class StockLedgerEntry(BaseModel):
    """
    The complete historical record of a stock transaction and its valuation.
    This is the immutable source of truth for all stock reports and audits.
    """
    __tablename__ = "stock_ledger_entries"


    company_id:   Mapped[int]      = mapped_column(db.BigInteger, db.ForeignKey("companies.id"), nullable=False, index=True)
    branch_id:    Mapped[int]      = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id:      Mapped[int]      = mapped_column(db.BigInteger, db.ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id: Mapped[int]      = mapped_column(db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Human-readable identifier
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, unique=True, index=True)

    # Precise posting timestamp
    posting_date: Mapped[date]             = mapped_column(db.Date, nullable=False, index=True)
    posting_time: Mapped[datetime]         = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)

    # Quantities & rates (use Decimal-friendly Numeric)
    actual_qty:   Mapped[Decimal]          = mapped_column(db.Numeric(18, 6), nullable=False, comment="Base UOM delta (+/-).")
    incoming_rate:Mapped[Optional[Decimal]]= mapped_column(db.Numeric(18, 6), nullable=True,  comment="Cost for incoming.")
    outgoing_rate:Mapped[Optional[Decimal]]= mapped_column(db.Numeric(18, 6), nullable=True,  comment="Cost for outgoing.")
    valuation_rate:Mapped[Decimal]         = mapped_column(db.Numeric(18, 6), nullable=False, comment="Avg (or layer) value after this row.")

    # Monetary impact of this row (required for zero-qty valuation events or reconciliation)
    stock_value_difference: Mapped[Decimal] = mapped_column(db.Numeric(20, 6), nullable=False, default=Decimal("0"))

    # Document linkage
    doc_type_id: Mapped[int]               = mapped_column(db.BigInteger, db.ForeignKey("document_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    doc_id:      Mapped[int]               = mapped_column(db.BigInteger, nullable=False, index=True)
    doc_row_id:  Mapped[Optional[int]]     = mapped_column(db.BigInteger, nullable=True,  index=True)

    # Snapshot around the move
    qty_before_transaction: Mapped[Optional[Decimal]] = mapped_column(db.Numeric(18, 6), nullable=True)
    qty_after_transaction:  Mapped[Optional[Decimal]] = mapped_column(db.Numeric(18, 6), nullable=True)

    # Immutability / repost metadata
    is_cancelled: Mapped[bool]             = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    is_reversal:  Mapped[bool]             = mapped_column(db.Boolean, nullable=False, default=False, index=True)
    reversed_sle_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("stock_ledger_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    adjustment_type: Mapped[SLEAdjustmentType] = mapped_column(db.Enum(SLEAdjustmentType), nullable=False, default=SLEAdjustmentType.NORMAL, index=True)

    # Relationships
    item:      Mapped["Item"]        = relationship()
    branch:    Mapped["Branch"]      = relationship()
    warehouse: Mapped["Warehouse"]   = relationship()
    doc_type:  Mapped["DocumentType"]= relationship()
    reversed_sle: Mapped[Optional["StockLedgerEntry"]] = relationship(remote_side="StockLedgerEntry.id")

    __table_args__ = (
        # Fast chronological scans for replay
        db.Index("ix_sle_replay_scan", "company_id", "item_id", "warehouse_id", "posting_date", "posting_time", "id"),
        db.Index("ix_sle_item_branch_wh", "company_id", "item_id", "branch_id", "warehouse_id"),
        db.Index("ix_sle_doc_ref", "doc_type_id", "doc_id"),
        db.UniqueConstraint("code", name="uq_sle_code"),
    )

    def __repr__(self) -> str:
        return f"<SLE id={self.id} item={self.item_id} wh={self.warehouse_id} qty={self.actual_qty}>"


# --- 4. Stock Reconciliation Models ---

class StockReconciliation(BaseModel):
    """
    Adjust books to physical count. On submit:
      - For each line: diff = counted_qty - current_bin_qty
      - Post SLE (+/- diff) with valuation handling
      - Update Bin to counted_qty
    """
    __tablename__ = "stock_reconciliations"

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id"),
                                            nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("branches.id"),
                                           nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id"),
                                               nullable=False, index=True)

    # Per-branch series (unique only within branch/company)
    code: Mapped[str] = mapped_column(db.String(100), nullable=False, index=True)

    posting_date: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, index=True)
    doc_status: Mapped[DocStatusEnum] = mapped_column(db.Enum(DocStatusEnum),
                                                      nullable=False, default=DocStatusEnum.DRAFT, index=True)
    purpose: Mapped[StockReconciliationPurpose] = mapped_column(
        db.Enum(StockReconciliationPurpose), nullable=False,
        default=StockReconciliationPurpose.STOCK_RECONCILIATION, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(db.Text)

    items: Mapped[list["StockReconciliationItem"]] = relationship(
        back_populates="reconciliation", cascade="all, delete-orphan"
    )
    created_by: Mapped["User"] = relationship()

    __table_args__ = (
        # Unique per company+branch (so Branch A can have 000001 and Branch B can also have 000001)
        UniqueConstraint("company_id", "branch_id", "code", name="uq_reconciliation_branch_code"),
        Index("ix_reconciliation_company_branch_status", "company_id", "branch_id", "doc_status"),
        Index("ix_reconciliation_company_posting_date", "company_id", "posting_date"),
        Index("ix_reconciliation_company_purpose", "company_id", "purpose"),
    )

    def __repr__(self) -> str:
        return f"<StockReconciliation id={self.id} code={self.code!r} branch={self.branch_id} status={self.doc_status}>"


class StockReconciliationItem(BaseModel):
    """
    One counted line:
      - item
      - warehouse (line-level for flexibility)
      - counted quantity (final quantity)
      - optional valuation_rate (required by service for +ve adjustments / opening)
    """
    __tablename__ = "stock_reconciliation_items"

    reconciliation_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("stock_reconciliations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Final quantity after count (in base UOM)
    quantity: Mapped[float] = mapped_column(db.Numeric(12, 3), nullable=False)

    # Let service require this only when needed (opening stock / positive diff)
    valuation_rate: Mapped[Optional[float]] = mapped_column(db.Numeric(12, 2), nullable=True)

    reconciliation: Mapped["StockReconciliation"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

    __table_args__ = (
        # Allows the same item to appear for different warehouses on the same document.
        UniqueConstraint("reconciliation_id", "item_id", "warehouse_id", name="uq_recon_item_wh"),
        CheckConstraint("quantity >= 0", name="ck_recon_qty_nonneg"),
        CheckConstraint("valuation_rate IS NULL OR valuation_rate >= 0", name="ck_recon_valrate_nonneg"),
        Index("ix_recon_item_company_wh",
              # helpful composite for reporting joins; reconciliation.company_id is in parent row
              "item_id", "warehouse_id"),
    )

    def __repr__(self) -> str:
        return (f"<StockReconciliationItem id={self.id} recon_id={self.reconciliation_id} "
                f"item={self.item_id} wh={self.warehouse_id} qty={self.quantity} val={self.valuation_rate}>")
