# app/application_print/schemas/print_config.py
from __future__ import annotations

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from app.application_print.models import (
    PrintAlign,
    PdfPageSize,
    PrintFormatType,
)

# ---------------------------------------------------------------------
# PRINT STYLE
# ---------------------------------------------------------------------


class PrintStyleBase(BaseModel):
    name: str = Field(..., max_length=140)
    description: Optional[str] = Field(None, max_length=255)
    css: str
    company_id: Optional[int] = None
    is_disabled: bool = False
    is_default_global: bool = False


class PrintStyleCreate(PrintStyleBase):
    code: str = Field(..., max_length=100)


class PrintStyleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=140)
    description: Optional[str] = Field(None, max_length=255)
    css: Optional[str] = None
    company_id: Optional[int] = None
    is_disabled: Optional[bool] = None
    is_default_global: Optional[bool] = None


# ---------------------------------------------------------------------
# LETTERHEAD
# ---------------------------------------------------------------------


class PrintLetterheadBase(BaseModel):
    company_id: int
    name: str = Field(..., max_length=140)

    header_based_on_image: bool = True
    header_image_key: Optional[str] = None
    header_image_height: Optional[int] = None
    header_image_width: Optional[int] = None
    header_align: PrintAlign = PrintAlign.LEFT
    header_html: Optional[str] = None

    footer_based_on_image: bool = False
    footer_image_key: Optional[str] = None
    footer_image_height: Optional[int] = None
    footer_image_width: Optional[int] = None
    footer_align: PrintAlign = PrintAlign.LEFT
    footer_html: Optional[str] = None

    is_disabled: bool = False
    is_default_for_company: bool = False


class PrintLetterheadCreate(PrintLetterheadBase):
    code: str = Field(..., max_length=100)


class PrintLetterheadUpdate(BaseModel):
    # code is immutable
    name: Optional[str] = Field(None, max_length=140)

    header_based_on_image: Optional[bool] = None
    header_image_key: Optional[str] = None
    header_image_height: Optional[int] = None
    header_image_width: Optional[int] = None
    header_align: Optional[PrintAlign] = None
    header_html: Optional[str] = None

    footer_based_on_image: Optional[bool] = None
    footer_image_key: Optional[str] = None
    footer_image_height: Optional[int] = None
    footer_image_width: Optional[int] = None
    footer_align: Optional[PrintAlign] = None
    footer_html: Optional[str] = None

    is_disabled: Optional[bool] = None
    is_default_for_company: Optional[bool] = None


# ---------------------------------------------------------------------
# PRINT SETTINGS
# ---------------------------------------------------------------------


class PrintSettingsBase(BaseModel):
    company_id: Optional[int] = None

    send_print_as_pdf: bool = True
    send_email_print_attachments_as_pdf: bool = True

    repeat_header_footer_in_pdf: bool = True
    pdf_page_size: PdfPageSize = PdfPageSize.A4

    print_with_letterhead: bool = True
    compact_item_print: bool = False
    print_uom_after_qty: bool = True

    allow_print_for_draft: bool = False
    always_add_draft_heading: bool = True
    allow_page_break_inside_tables: bool = False
    allow_print_for_cancelled: bool = False
    print_taxes_with_zero_amount: bool = False

    enable_raw_printing: bool = False

    default_print_style_id: Optional[int] = None
    default_font_family: Optional[str] = None
    default_font_size_pt: Optional[int] = None

    default_language: Optional[str] = None
    additional_options: Optional[Dict[str, Any]] = None


class PrintSettingsCreate(PrintSettingsBase):
    # nothing extra; kept for symmetry
    pass


class PrintSettingsUpdate(BaseModel):
    send_print_as_pdf: Optional[bool] = None
    send_email_print_attachments_as_pdf: Optional[bool] = None
    repeat_header_footer_in_pdf: Optional[bool] = None
    pdf_page_size: Optional[PdfPageSize] = None
    print_with_letterhead: Optional[bool] = None
    compact_item_print: Optional[bool] = None
    print_uom_after_qty: Optional[bool] = None
    allow_print_for_draft: Optional[bool] = None
    always_add_draft_heading: Optional[bool] = None
    allow_page_break_inside_tables: Optional[bool] = None
    allow_print_for_cancelled: Optional[bool] = None
    print_taxes_with_zero_amount: Optional[bool] = None
    enable_raw_printing: Optional[bool] = None
    default_print_style_id: Optional[int] = None
    default_font_family: Optional[str] = None
    default_font_size_pt: Optional[int] = None
    default_language: Optional[str] = None
    additional_options: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------
# PRINT FORMAT
# ---------------------------------------------------------------------


class PrintFormatBase(BaseModel):
    doctype: str
    module: Optional[str] = None
    name: str
    company_id: Optional[int] = None

    default_print_language: Optional[str] = None
    is_standard: bool = False
    is_default_for_doctype: bool = False
    is_disabled: bool = False

    print_format_type: PrintFormatType = PrintFormatType.JINJA
    custom_format: bool = True
    raw_printing: bool = False

    margin_top_mm: int = 15
    margin_bottom_mm: int = 15
    margin_left_mm: int = 15
    margin_right_mm: int = 15

    font_size_pt: Optional[int] = None
    google_font: Optional[str] = None

    align_labels_to_right: bool = False
    show_section_headings: bool = True
    show_line_breaks_after_sections: bool = True

    template_html: Optional[str] = None
    custom_css: Optional[str] = None

    external_url: Optional[str] = None
    raw_payload_template: Optional[str] = None

    default_letterhead_id: Optional[int] = None
    print_style_id: Optional[int] = None

    layout_options: Optional[Dict[str, Any]] = None


class PrintFormatCreate(PrintFormatBase):
    code: str


class PrintFormatUpdate(BaseModel):
    # doctype/module/code are immutable
    name: Optional[str] = None
    company_id: Optional[int] = None
    default_print_language: Optional[str] = None
    is_standard: Optional[bool] = None
    is_default_for_doctype: Optional[bool] = None
    is_disabled: Optional[bool] = None

    print_format_type: Optional[PrintFormatType] = None
    custom_format: Optional[bool] = None
    raw_printing: Optional[bool] = None

    margin_top_mm: Optional[int] = None
    margin_bottom_mm: Optional[int] = None
    margin_left_mm: Optional[int] = None
    margin_right_mm: Optional[int] = None

    font_size_pt: Optional[int] = None
    google_font: Optional[str] = None

    align_labels_to_right: Optional[bool] = None
    show_section_headings: Optional[bool] = None
    show_line_breaks_after_sections: Optional[bool] = None

    template_html: Optional[str] = None
    custom_css: Optional[str] = None

    external_url: Optional[str] = None
    raw_payload_template: Optional[str] = None

    default_letterhead_id: Optional[int] = None
    print_style_id: Optional[int] = None

    layout_options: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------
# FIELD TEMPLATE
# ---------------------------------------------------------------------


class PrintFormatFieldTemplateBase(BaseModel):
    print_format_id: int
    doctype: str
    field_name: str
    field_label: Optional[str] = None
    description: Optional[str] = None
    template_html: str
    is_default_for_field: bool = False
    language: Optional[str] = None


class PrintFormatFieldTemplateCreate(PrintFormatFieldTemplateBase):
    pass


class PrintFormatFieldTemplateUpdate(BaseModel):
    field_label: Optional[str] = None
    description: Optional[str] = None
    template_html: Optional[str] = None
    is_default_for_field: Optional[bool] = None
    language: Optional[str] = None
