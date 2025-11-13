# app/application_data_import/models.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from sqlalchemy import JSON, Enum as SQLEnum, String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey

from config.database import db
from app.common.models.base import BaseModel


class ImportStatus(str, Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    PARTIAL_SUCCESS = "Partial Success"
    SUCCESS = "Success"
    FAILED = "Failed"


class ImportType(str, Enum):
    INSERT = "Insert"
    UPDATE = "Update"


class FileType(str, Enum):
    CSV = "csv"
    EXCEL = "excel"


class DataImport(BaseModel):
    """
    Main Data Import - Simple form fields only
    """
    __tablename__ = "data_imports"

    # === Core Identification ===
    company_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    created_by_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # === Only 3 Essential Fields for First Save ===
    reference_doctype: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    import_type: Mapped[ImportType] = mapped_column(
        SQLEnum(ImportType), nullable=False, index=True
    )
    file_type: Mapped[FileType] = mapped_column(
        SQLEnum(FileType), nullable=False, index=True
    )

    # === File Upload (After Save) ===
    import_file_key: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, index=True
    )
    google_sheets_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )

    # === Status ===
    status: Mapped[ImportStatus] = mapped_column(
        SQLEnum(ImportStatus), nullable=False,
        default=ImportStatus.NOT_STARTED, index=True
    )

    # === Simple Counts ===
    total_rows: Mapped[int] = mapped_column(
        Integer, default=0, index=True
    )
    successful_rows: Mapped[int] = mapped_column(
        Integer, default=0, index=True
    )
    failed_rows: Mapped[int] = mapped_column(
        Integer, default=0, index=True
    )

    # === Background Job ===
    job_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    # === Preview Data ===
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )

    # === Only 1 Option as requested ===
    mute_emails: Mapped[bool] = mapped_column(
        Boolean, default=True
    )

    # === Relationships ===
    template_fields: Mapped[List["DataImportTemplateField"]] = relationship(
        "DataImportTemplateField",
        back_populates="data_import",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    import_logs: Mapped[List["DataImportLog"]] = relationship(
        "DataImportLog",
        back_populates="data_import",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # Company and Branch relationships for easy access
    company: Mapped["Company"] = relationship(
        "Company",
        back_populates="data_imports",
        lazy="selectin"
    )
    branch: Mapped["Branch"] = relationship(
        "Branch",
        back_populates="data_imports",
        lazy="selectin"
    )
    created_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin"
    )

    __table_args__ = (
        # Fast lookup by company and status
        db.Index('ix_data_imports_company_status', 'company_id', 'status'),
        # Fast lookup by doctype and status
        db.Index('ix_data_imports_doctype_status', 'reference_doctype', 'status'),
        # Fast lookup by creation date for recent imports
        db.Index('ix_data_imports_created_at', 'created_at'),
        # Fast counting and filtering by row counts
        db.Index('ix_data_imports_row_counts', 'total_rows', 'successful_rows', 'failed_rows'),
        # Fast job status lookup
        db.Index('ix_data_imports_job_status', 'job_id', 'status'),
    )

    def __repr__(self) -> str:
        return f"<DataImport {self.id} {self.reference_doctype} {self.status}>"


class DataImportTemplateField(BaseModel):
    """
    Stores field selection for template generation
    Separate model as requested
    """
    __tablename__ = "data_import_template_fields"

    data_import_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("data_imports.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # === Field Mapping ===
    # The actual database field name (e.g., 'sku') - Used by the service layer
    field_name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )

    # The display label shown to the user (e.g., 'Item Code') - Used for template headers
    field_label: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # The order in which the column appears in the template/file
    column_index: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )

    # Flag to indicate if the field is mandatory for the DocType
    is_required: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )

    # Relationships
    data_import: Mapped["DataImport"] = relationship(
        "DataImport",
        back_populates="template_fields",
        lazy="selectin"
    )

    __table_args__ = (
        # Fast lookup by import and field name
        db.Index('ix_template_fields_import_field', 'data_import_id', 'field_name'),
        # Fast ordering by column index for template generation
        db.Index('ix_template_fields_column_order', 'data_import_id', 'column_index'),
        # Fast lookup of required fields
        db.Index('ix_template_fields_required', 'data_import_id', 'is_required'),
        # Fast lookup by field label
        db.Index('ix_template_fields_label', 'data_import_id', 'field_label'),
        # Unique constraint to prevent duplicate fields per import
        db.UniqueConstraint('data_import_id', 'field_name', name='uq_template_field_import'),
    )

    def __repr__(self) -> str:
        return f"<DataImportTemplateField {self.field_name} required={self.is_required}>"


class DataImportLog(BaseModel):
    """
    Simple row-level log for fast processing of thousands of rows
    """
    __tablename__ = "data_import_logs"

    data_import_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("data_imports.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Essential fields only for performance
    row_index: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, index=True
    )
    messages: Mapped[Optional[List[str]]] = mapped_column(
        JSON, nullable=True
    )

    # Relationships
    data_import: Mapped["DataImport"] = relationship(
        "DataImport",
        back_populates="import_logs",
        lazy="selectin"
    )

    __table_args__ = (
        # Fast lookup by import and row index
        db.Index('ix_import_logs_import_row', 'data_import_id', 'row_index'),
        # Fast filtering by success status
        db.Index('ix_import_logs_success', 'data_import_id', 'success'),
        # Fast counting of successful/failed rows
        db.Index('ix_import_logs_status_count', 'data_import_id', 'success', 'row_index'),
        # REMOVED: Covering index with JSON column - PostgreSQL can't index JSON with B-tree
        # db.Index('ix_import_logs_covering', 'data_import_id', 'success', 'row_index', 'messages'),
    )

    def __repr__(self) -> str:
        return f"<DataImportLog row_{self.row_index} success={self.success}>"