# app/application_print/models.py
from __future__ import annotations

from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Text,
    Enum as SQLEnum,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import db
from app.common.models.base import BaseModel


# ---------------------------------------------------------------------------
# ENUMS
# ---------------------------------------------------------------------------

class PrintOrientation(str, Enum):
    PORTRAIT = "Portrait"
    LANDSCAPE = "Landscape"


class PdfPageSize(str, Enum):
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"
    LETTER = "Letter"
    LEGAL = "Legal"
    CUSTOM = "Custom"


class PrintFormatType(str, Enum):
    # Similar to Frappe: "Jinja" custom HTML, or builder / raw
    STANDARD_BUILDER = "Standard Builder"   # auto layout from DocType meta
    JINJA = "Jinja"                         # freehand HTML+CSS+Jinja
    RAW = "Raw"                             # text/ESC/P etc for receipt printers
    EXTERNAL_URL = "External URL"          # e.g. BI/report URL


class PrintAlign(str, Enum):
    LEFT = "Left"
    CENTER = "Center"
    RIGHT = "Right"


# ---------------------------------------------------------------------------
# LETTERHEAD
# ---------------------------------------------------------------------------

class PrintLetterhead(BaseModel):
    """
    Company letterhead (header + optional footer), similar to Frappe's Letter Head.
    Used across all print formats (quotations, invoices, etc).
    """
    __tablename__ = "print_letterheads"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Header variant
    header_based_on_image: Mapped[bool] = mapped_column(Boolean, default=True)
    header_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    header_image_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    header_image_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    header_align: Mapped[PrintAlign] = mapped_column(
        SQLEnum(PrintAlign), default=PrintAlign.LEFT, nullable=False
    )

    # HTML variant (when not based on image)
    header_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Footer
    footer_based_on_image: Mapped[bool] = mapped_column(Boolean, default=False)
    footer_image_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    footer_image_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    footer_image_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    footer_align: Mapped[PrintAlign] = mapped_column(
        SQLEnum(PrintAlign), default=PrintAlign.LEFT, nullable=False
    )

    footer_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Flags
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default_for_company: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Relationships
    company: Mapped["Company"] = relationship(
        "Company", back_populates="print_letterheads", lazy="selectin"
    )

    __table_args__ = (
        db.Index("ix_print_letterheads_company_default", "company_id", "is_default_for_company"),
    )

    def __repr__(self) -> str:
        return f"<PrintLetterhead {self.code} company={self.company_id}>"


# ---------------------------------------------------------------------------
# PRINT STYLE (CSS only)
# ---------------------------------------------------------------------------

class PrintStyle(BaseModel):
    """
    Pure CSS style, similar to Frappe's 'Print Style' DocType:
    - Standard / Classic / Modern / Monochrome, etc.
    """
    __tablename__ = "print_styles"

    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # CSS snippet applied to print-format wrapper (.print-format ...)
    css: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional scoping
    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True
    )

    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Relationships
    company: Mapped[Optional["Company"]] = relationship(
        "Company", back_populates="print_styles", lazy="selectin"
    )

    __table_args__ = (
        db.Index("ix_print_styles_company_code", "company_id", "code"),
    )

    def __repr__(self) -> str:
        return f"<PrintStyle {self.code}>"


# ---------------------------------------------------------------------------
# PRINT SETTINGS (global or per company; SINGLE-like)
# ---------------------------------------------------------------------------

class PrintSettings(BaseModel):
    """
    Global / per-company print behaviour, similar to Frappe's Print Settings DocType.
    Typically one row per company, or one global row (company_id NULL).
    """
    __tablename__ = "print_settings"

    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True
    )

    # DF Settings
    send_print_as_pdf: Mapped[bool] = mapped_column(Boolean, default=True)
    send_email_print_attachments_as_pdf: Mapped[bool] = mapped_column(Boolean, default=True)

    repeat_header_footer_in_pdf: Mapped[bool] = mapped_column(Boolean, default=True)
    pdf_page_size: Mapped[PdfPageSize] = mapped_column(
        SQLEnum(PdfPageSize), default=PdfPageSize.A4, nullable=False
    )

    # Page Settings
    print_with_letterhead: Mapped[bool] = mapped_column(Boolean, default=True)
    compact_item_print: Mapped[bool] = mapped_column(Boolean, default=False)
    print_uom_after_qty: Mapped[bool] = mapped_column(Boolean, default=True)

    allow_print_for_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    always_add_draft_heading: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_page_break_inside_tables: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_print_for_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    print_taxes_with_zero_amount: Mapped[bool] = mapped_column(Boolean, default=False)

    # Raw Printing
    enable_raw_printing: Mapped[bool] = mapped_column(Boolean, default=False)

    # Default style / fonts
    default_print_style_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("print_styles.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    default_font_family: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    default_font_size_pt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Misc
    default_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    additional_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    company: Mapped[Optional["Company"]] = relationship(
        "Company", back_populates="print_settings", lazy="selectin"
    )
    default_print_style: Mapped[Optional["PrintStyle"]] = relationship(
        "PrintStyle", lazy="selectin"
    )

    __table_args__ = (
        db.UniqueConstraint("company_id", name="uq_print_settings_company"),
    )

    def __repr__(self) -> str:
        return f"<PrintSettings company={self.company_id}>"


# ---------------------------------------------------------------------------
# PRINT FORMAT
# ---------------------------------------------------------------------------

class PrintFormat(BaseModel):
    """
    Concrete print format for a specific DocType.
    Example: 'Standard', 'POS Invoice', 'Surad Quotation', 'Minimal Receipt', etc.
    """
    __tablename__ = "print_formats"

    # Scope
    doctype: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    module: Mapped[Optional[str]] = mapped_column(String(140), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True, index=True
    )

    # Behaviour
    default_print_language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    is_standard: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_default_for_doctype: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    print_format_type: Mapped[PrintFormatType] = mapped_column(
        SQLEnum(PrintFormatType), default=PrintFormatType.STANDARD_BUILDER, nullable=False
    )
    custom_format: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_printing: Mapped[bool] = mapped_column(Boolean, default=False)

    # Style / layout
    margin_top_mm: Mapped[int] = mapped_column(Integer, default=15)
    margin_bottom_mm: Mapped[int] = mapped_column(Integer, default=15)
    margin_left_mm: Mapped[int] = mapped_column(Integer, default=15)
    margin_right_mm: Mapped[int] = mapped_column(Integer, default=15)

    font_size_pt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    google_font: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    align_labels_to_right: Mapped[bool] = mapped_column(Boolean, default=False)
    show_section_headings: Mapped[bool] = mapped_column(Boolean, default=True)
    show_line_breaks_after_sections: Mapped[bool] = mapped_column(Boolean, default=True)

    # Template source
    # For Jinja / builder
    template_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_css: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # For external / raw
    external_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_payload_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Default letterhead / style
    default_letterhead_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("print_letterheads.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    print_style_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, ForeignKey("print_styles.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    # Optional meta override (e.g. “Compact columns”, “grouped by item group”)
    layout_options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    company: Mapped[Optional["Company"]] = relationship(
        "Company", back_populates="print_formats", lazy="selectin"
    )
    default_letterhead: Mapped[Optional["PrintLetterhead"]] = relationship(
        "PrintLetterhead", lazy="selectin"
    )
    print_style: Mapped[Optional["PrintStyle"]] = relationship(
        "PrintStyle", lazy="selectin"
    )
    field_templates: Mapped[List["PrintFormatFieldTemplate"]] = relationship(
        "PrintFormatFieldTemplate",
        back_populates="print_format",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        db.Index(
            "ix_print_formats_doctype_company_default",
            "doctype",
            "company_id",
            "is_default_for_doctype",
        ),
        db.Index(
            "ix_print_formats_doctype_standard",
            "doctype",
            "is_standard",
        ),
    )

    def __repr__(self) -> str:
        return f"<PrintFormat {self.code} doctype={self.doctype}>"


# ---------------------------------------------------------------------------
# PRINT FORMAT FIELD TEMPLATE
# ---------------------------------------------------------------------------

class PrintFormatFieldTemplate(BaseModel):
    """
    Optional per-field template overrides.
    Equivalent to Frappe's 'Print Format Field Template' DocType.
    """
    __tablename__ = "print_format_field_templates"

    print_format_id: Mapped[int] = mapped_column(
        db.BigInteger, ForeignKey("print_formats.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    doctype: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(140), nullable=False, index=True)
    field_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Small description / help
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Jinja/HTML snippet used to render this field
    # Example: `<b>{{ label }}</b>: {{ value or "-" }}`
    template_html: Mapped[str] = mapped_column(Text, nullable=False)

    # Default template per field or only for this print format?
    is_default_for_field: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Optional language code
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Relationships
    print_format: Mapped["PrintFormat"] = relationship(
        "PrintFormat", back_populates="field_templates", lazy="selectin"
    )

    __table_args__ = (
        db.Index(
            "ix_pfft_format_field",
            "print_format_id",
            "field_name",
        ),
        db.UniqueConstraint(
            "print_format_id",
            "field_name",
            "language",
            name="uq_pfft_format_field_lang",
        ),
    )

    def __repr__(self) -> str:
        return f"<PrintFormatFieldTemplate {self.field_name} format={self.print_format_id}>"
