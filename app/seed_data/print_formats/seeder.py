# # # app/seed_data/print_formats/seeder.py
#
# from __future__ import annotations
#
# import logging
# from typing import Optional, Dict
#
# from sqlalchemy import select
# from sqlalchemy.orm import Session
#
# from app.application_print.models import (
#     PrintStyle,
#     PrintSettings,
#     PrintFormat,
#     PrintFormatType,
#     PrintLetterhead,
# )
#
# from .letterheads import PRINT_LETTERHEAD_DEFS
# from .styles import PRINT_STYLE_DEFS
# from .settings import PRINT_SETTINGS_DEFS
# from .formats import PRINT_FORMAT_DEFS
#
# logger = logging.getLogger(__name__)
#
#
# # ---------------------- helpers ----------------------
# def _style_by_code(db: Session) -> Dict[str, PrintStyle]:
#     rows = db.scalars(select(PrintStyle)).all()
#     return {s.code: s for s in rows}
#
#
# # ---------------------- seed styles ----------------------
# def seed_print_styles(db: Session) -> None:
#     logger.info("🌱 Seeding Print Styles...")
#
#     existing = {s.code: s for s in db.scalars(select(PrintStyle)).all()}
#
#     for row in PRINT_STYLE_DEFS:
#         code = row["code"]
#         obj = existing.get(code)
#
#         if obj:
#             obj.name = row["name"]
#             obj.description = row.get("description")
#             obj.css = row["css"]
#             obj.company_id = None
#             obj.is_disabled = False
#             obj.is_default_global = bool(row.get("is_default_global", False))
#             db.flush([obj])
#         else:
#             obj = PrintStyle(
#                 code=code,
#                 name=row["name"],
#                 description=row.get("description"),
#                 css=row["css"],
#                 company_id=None,
#                 is_disabled=False,
#                 is_default_global=bool(row.get("is_default_global", False)),
#             )
#             db.add(obj)
#
#     db.flush()
#     logger.info("✅ Print Styles seeded.")
#
#
# # ---------------------- seed settings ----------------------
# def seed_print_settings(db: Session) -> None:
#     logger.info("🌱 Seeding Print Settings...")
#
#     style_idx = _style_by_code(db)
#
#     for row in PRINT_SETTINGS_DEFS:
#         company_id = row["company_id"]
#         stmt = select(PrintSettings).where(PrintSettings.company_id.is_(company_id)).limit(1)
#         settings: Optional[PrintSettings] = db.scalar(stmt)
#
#         style_code = row.get("default_print_style_code")
#         style = style_idx.get(style_code) if style_code else None
#         style_id = int(style.id) if style else None
#
#         if settings:
#             settings.send_print_as_pdf = row["send_print_as_pdf"]
#             settings.send_email_print_attachments_as_pdf = row["send_email_print_attachments_as_pdf"]
#             settings.repeat_header_footer_in_pdf = row["repeat_header_footer_in_pdf"]
#             settings.pdf_page_size = row["pdf_page_size"]
#             settings.print_with_letterhead = row["print_with_letterhead"]
#             settings.compact_item_print = row["compact_item_print"]
#             settings.print_uom_after_qty = row["print_uom_after_qty"]
#             settings.allow_print_for_draft = row["allow_print_for_draft"]
#             settings.always_add_draft_heading = row["always_add_draft_heading"]
#             settings.allow_page_break_inside_tables = row["allow_page_break_inside_tables"]
#             settings.allow_print_for_cancelled = row["allow_print_for_cancelled"]
#             settings.print_taxes_with_zero_amount = row["print_taxes_with_zero_amount"]
#             settings.default_print_style_id = style_id
#             settings.default_font_family = row.get("default_font_family")
#             settings.default_font_size_pt = row.get("default_font_size_pt")
#             settings.default_language = row.get("default_language")
#             settings.additional_options = row.get("additional_options")
#             db.flush([settings])
#         else:
#             settings = PrintSettings(
#                 company_id=company_id,
#                 send_print_as_pdf=row["send_print_as_pdf"],
#                 send_email_print_attachments_as_pdf=row["send_email_print_attachments_as_pdf"],
#                 repeat_header_footer_in_pdf=row["repeat_header_footer_in_pdf"],
#                 pdf_page_size=row["pdf_page_size"],
#                 print_with_letterhead=row["print_with_letterhead"],
#                 compact_item_print=row["compact_item_print"],
#                 print_uom_after_qty=row["print_uom_after_qty"],
#                 allow_print_for_draft=row["allow_print_for_draft"],
#                 always_add_draft_heading=row["always_add_draft_heading"],
#                 allow_page_break_inside_tables=row["allow_page_break_inside_tables"],
#                 allow_print_for_cancelled=row["allow_print_for_cancelled"],
#                 print_taxes_with_zero_amount=row["print_taxes_with_zero_amount"],
#                 default_print_style_id=style_id,
#                 default_font_family=row.get("default_font_family"),
#                 default_font_size_pt=row.get("default_font_size_pt"),
#                 default_language=row.get("default_language"),
#                 additional_options=row.get("additional_options"),
#             )
#             db.add(settings)
#
#     db.flush()
#     logger.info("✅ Print Settings seeded.")
#
#
# # ---------------------- seed formats ----------------------
# # ---------------------- seed formats ----------------------
# def seed_print_formats(db: Session) -> None:
#     logger.info("🌱 Seeding Print Formats...")
#
#     style_idx = _style_by_code(db)
#     existing = {(pf.doctype, pf.company_id, pf.code): pf for pf in db.scalars(select(PrintFormat)).all()}
#
#     for row in PRINT_FORMAT_DEFS:
#         key = (row["doctype"], row["company_id"], row["code"])
#         pf = existing.get(key)
#
#         style_code = row.get("print_style_code")
#         style = style_idx.get(style_code) if style_code else None
#         style_id = int(style.id) if style else None
#         fmt_type = PrintFormatType[row["print_format_type"].upper()]
#
#         if pf:
#             # --- CRITICAL FIX: Update the template_html here ---
#             pf.template_html = row.get("template_html")
#             pf.module = row["module"]
#             pf.name = row["name"]
#             pf.default_print_language = row.get("default_print_language")
#             pf.is_standard = row.get("is_standard", False)
#             pf.is_default_for_doctype = row.get("is_default_for_doctype", False)
#             pf.is_disabled = row.get("is_disabled", False)
#             pf.print_format_type = fmt_type
#             pf.custom_format = row.get("custom_format", False)
#             pf.raw_printing = row.get("raw_printing", False)
#             pf.margin_top_mm = row.get("margin_top_mm", 15)
#             pf.margin_bottom_mm = row.get("margin_bottom_mm", 15)
#             pf.margin_left_mm = row.get("margin_left_mm", 15)
#             pf.margin_right_mm = row.get("margin_right_mm", 15)
#             pf.font_size_pt = row.get("font_size_pt")
#             pf.google_font = row.get("google_font")
#             pf.align_labels_to_right = row.get("align_labels_to_right", False)
#             pf.show_section_headings = row.get("show_section_headings", True)
#             pf.show_line_breaks_after_sections = row.get("show_line_breaks_after_sections", True)
#             pf.custom_css = row.get("custom_css")
#             pf.external_url = row.get("external_url")
#             pf.raw_payload_template = row.get("raw_payload_template")
#             pf.default_letterhead_id = row.get("default_letterhead_id")
#             pf.print_style_id = style_id
#             pf.layout_options = row.get("layout_options")
#             db.flush([pf]) # Sync changes to DB
#         else:
#             pf = PrintFormat(
#                 doctype=row["doctype"],
#                 module=row["module"],
#                 name=row["name"],
#                 code=row["code"],
#                 company_id=row["company_id"],
#                 print_format_type=fmt_type,
#                 template_html=row.get("template_html"), # Set for new records
#                 # ... rest of your existing init code ...
#                 is_standard=row.get("is_standard", False),
#                 is_default_for_doctype=row.get("is_default_for_doctype", False),
#                 margin_top_mm=row.get("margin_top_mm", 15),
#                 margin_bottom_mm=row.get("margin_bottom_mm", 15),
#                 margin_left_mm=row.get("margin_left_mm", 15),
#                 margin_right_mm=row.get("margin_right_mm", 15),
#                 print_style_id=style_id
#             )
#             db.add(pf)
#
#     db.flush()
#     logger.info("✅ Print Formats seeded and updated.")
#
#
#
# # ---------------------- seed letterheads ----------------------
# def seed_print_letterheads(db: Session) -> None:
#     logger.info("🌱 Seeding Print Letterheads...")
#
#     existing = {(lh.company_id, lh.code): lh for lh in db.scalars(select(PrintLetterhead)).all()}
#
#     for row in PRINT_LETTERHEAD_DEFS:
#         key = (row["company_id"], row["code"])
#         lh = existing.get(key)
#
#         if lh:
#             for k, v in row.items():
#                 setattr(lh, k, v)
#             db.flush([lh])
#         else:
#             db.add(PrintLetterhead(**row))
#
#     db.flush()
#     logger.info("✅ Print Letterheads seeded.")
#
#
# # ---------------------- public entry ----------------------
# def seed_print_framework(db: Session) -> None:
#     """
#     Seeding order:
#       - styles
#       - settings
#       - formats
#       - letterheads
#     """
#     seed_print_styles(db)
#     seed_print_settings(db)
#     seed_print_formats(db)
#     seed_print_letterheads(db)
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, Tuple, Set, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application_print.models import (
    PrintStyle,
    PrintSettings,
    PrintFormat,
    PrintFormatType,
    PrintLetterhead,
)

from .letterheads import PRINT_LETTERHEAD_DEFS
from .styles import PRINT_STYLE_DEFS
from .settings import PRINT_SETTINGS_DEFS
from .formats import PRINT_FORMAT_DEFS

logger = logging.getLogger(__name__)


# ---------------------- helpers ----------------------
def _style_by_code(db: Session) -> Dict[str, PrintStyle]:
    rows = db.scalars(select(PrintStyle)).all()
    return {s.code: s for s in rows}


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return bool(v)


def _apply_print_format_fields(pf: PrintFormat, row: Dict[str, Any], style_id: Optional[int]) -> None:
    """
    Apply ALL fields consistently for both update and create.
    This prevents "partial rows" being created.
    """
    fmt_type = PrintFormatType[row["print_format_type"].upper()]

    pf.doctype = row["doctype"]
    pf.module = row["module"]
    pf.name = row["name"]
    pf.code = row["code"]
    pf.company_id = row.get("company_id")

    pf.default_print_language = row.get("default_print_language")
    pf.is_standard = _as_bool(row.get("is_standard"), False)
    pf.is_default_for_doctype = _as_bool(row.get("is_default_for_doctype"), False)
    pf.is_disabled = _as_bool(row.get("is_disabled"), False)

    pf.print_format_type = fmt_type
    pf.custom_format = _as_bool(row.get("custom_format"), False)
    pf.raw_printing = _as_bool(row.get("raw_printing"), False)

    pf.margin_top_mm = row.get("margin_top_mm", 15)
    pf.margin_bottom_mm = row.get("margin_bottom_mm", 15)
    pf.margin_left_mm = row.get("margin_left_mm", 15)
    pf.margin_right_mm = row.get("margin_right_mm", 15)

    pf.font_size_pt = row.get("font_size_pt")
    pf.google_font = row.get("google_font")

    pf.align_labels_to_right = _as_bool(row.get("align_labels_to_right"), False)
    pf.show_section_headings = _as_bool(row.get("show_section_headings"), True)
    pf.show_line_breaks_after_sections = _as_bool(row.get("show_line_breaks_after_sections"), True)

    # CRITICAL: template update
    pf.template_html = row.get("template_html")
    pf.custom_css = row.get("custom_css")
    pf.external_url = row.get("external_url")
    pf.raw_payload_template = row.get("raw_payload_template")

    pf.default_letterhead_id = row.get("default_letterhead_id")
    pf.print_style_id = style_id
    pf.layout_options = row.get("layout_options")


def _desired_keys() -> Set[Tuple[str, Optional[int], str]]:
    return {(r["doctype"], r.get("company_id"), r["code"]) for r in PRINT_FORMAT_DEFS}


# ---------------------- seed styles ----------------------
def seed_print_styles(db: Session) -> None:
    logger.info("🌱 Seeding Print Styles...")

    existing = {s.code: s for s in db.scalars(select(PrintStyle)).all()}

    for row in PRINT_STYLE_DEFS:
        code = row["code"]
        obj = existing.get(code)

        if obj:
            obj.name = row["name"]
            obj.description = row.get("description")
            obj.css = row["css"]
            obj.company_id = None
            obj.is_disabled = False
            obj.is_default_global = bool(row.get("is_default_global", False))
            db.flush([obj])
        else:
            obj = PrintStyle(
                code=code,
                name=row["name"],
                description=row.get("description"),
                css=row["css"],
                company_id=None,
                is_disabled=False,
                is_default_global=bool(row.get("is_default_global", False)),
            )
            db.add(obj)

    db.flush()
    logger.info("✅ Print Styles seeded.")


# ---------------------- seed settings ----------------------
def seed_print_settings(db: Session) -> None:
    logger.info("🌱 Seeding Print Settings...")

    style_idx = _style_by_code(db)

    for row in PRINT_SETTINGS_DEFS:
        company_id = row["company_id"]
        stmt = select(PrintSettings).where(PrintSettings.company_id.is_(company_id)).limit(1)
        settings: Optional[PrintSettings] = db.scalar(stmt)

        style_code = row.get("default_print_style_code")
        style = style_idx.get(style_code) if style_code else None
        style_id = int(style.id) if style else None

        if settings:
            settings.send_print_as_pdf = row["send_print_as_pdf"]
            settings.send_email_print_attachments_as_pdf = row["send_email_print_attachments_as_pdf"]
            settings.repeat_header_footer_in_pdf = row["repeat_header_footer_in_pdf"]
            settings.pdf_page_size = row["pdf_page_size"]
            settings.print_with_letterhead = row["print_with_letterhead"]
            settings.compact_item_print = row["compact_item_print"]
            settings.print_uom_after_qty = row["print_uom_after_qty"]
            settings.allow_print_for_draft = row["allow_print_for_draft"]
            settings.always_add_draft_heading = row["always_add_draft_heading"]
            settings.allow_page_break_inside_tables = row["allow_page_break_inside_tables"]
            settings.allow_print_for_cancelled = row["allow_print_for_cancelled"]
            settings.print_taxes_with_zero_amount = row["print_taxes_with_zero_amount"]
            settings.default_print_style_id = style_id
            settings.default_font_family = row.get("default_font_family")
            settings.default_font_size_pt = row.get("default_font_size_pt")
            settings.default_language = row.get("default_language")
            settings.additional_options = row.get("additional_options")
            db.flush([settings])
        else:
            settings = PrintSettings(
                company_id=company_id,
                send_print_as_pdf=row["send_print_as_pdf"],
                send_email_print_attachments_as_pdf=row["send_email_print_attachments_as_pdf"],
                repeat_header_footer_in_pdf=row["repeat_header_footer_in_pdf"],
                pdf_page_size=row["pdf_page_size"],
                print_with_letterhead=row["print_with_letterhead"],
                compact_item_print=row["compact_item_print"],
                print_uom_after_qty=row["print_uom_after_qty"],
                allow_print_for_draft=row["allow_print_for_draft"],
                always_add_draft_heading=row["always_add_draft_heading"],
                allow_page_break_inside_tables=row["allow_page_break_inside_tables"],
                allow_print_for_cancelled=row["allow_print_for_cancelled"],
                print_taxes_with_zero_amount=row["print_taxes_with_zero_amount"],
                default_print_style_id=style_id,
                default_font_family=row.get("default_font_family"),
                default_font_size_pt=row.get("default_font_size_pt"),
                default_language=row.get("default_language"),
                additional_options=row.get("additional_options"),
            )
            db.add(settings)

    db.flush()
    logger.info("✅ Print Settings seeded.")


# ---------------------- seed formats ----------------------
def seed_print_formats(db: Session) -> None:
    """
    Fixes:
      - Properly updates template_html (and all fields)
      - Safely removes legacy seed formats that are no longer in PRINT_FORMAT_DEFS
      - Ensures only ONE default per (doctype, company_id)
    """
    logger.info("🌱 Seeding Print Formats...")

    style_idx = _style_by_code(db)
    desired = _desired_keys()

    # 1) Load all formats once
    all_formats: List[PrintFormat] = db.scalars(select(PrintFormat)).all()
    existing_by_key: Dict[Tuple[str, Optional[int], str], PrintFormat] = {
        (pf.doctype, pf.company_id, pf.code): pf for pf in all_formats
    }

    # 2) SAFE CLEANUP of legacy seed rows (company_id=None only)
    # We delete only:
    #   - company_id is None
    #   - and either is_standard == True OR code is in legacy list
    #   - and not present in desired defs
    legacy_codes = {
        # ones you showed in DB
        "standard",
        "standard_invoice",
        "pos_invoice",
        "djibouti_standard_invoice",
    }

    delete_count = 0
    for pf in list(all_formats):
        key = (pf.doctype, pf.company_id, pf.code)

        if pf.company_id is None and key not in desired:
            if bool(pf.is_standard) or pf.code in legacy_codes:
                logger.info(
                    "[print seed] deleting legacy PrintFormat doctype=%s code=%s is_standard=%s default=%s",
                    pf.doctype,
                    pf.code,
                    pf.is_standard,
                    pf.is_default_for_doctype,
                )
                db.delete(pf)
                delete_count += 1

    if delete_count:
        db.flush()
        logger.info("🧹 Deleted %s legacy print formats.", delete_count)

    # Refresh after deletions
    all_formats = db.scalars(select(PrintFormat)).all()
    existing_by_key = {(pf.doctype, pf.company_id, pf.code): pf for pf in all_formats}

    # 3) UPSERT the desired defs
    upserted: List[PrintFormat] = []
    for row in PRINT_FORMAT_DEFS:
        key = (row["doctype"], row.get("company_id"), row["code"])
        pf = existing_by_key.get(key)

        style_code = row.get("print_style_code")
        style = style_idx.get(style_code) if style_code else None
        style_id = int(style.id) if style else None

        if pf:
            _apply_print_format_fields(pf, row, style_id)
            db.flush([pf])
            upserted.append(pf)
            logger.info("[print seed] updated doctype=%s code=%s default=%s",
                        pf.doctype, pf.code, pf.is_default_for_doctype)
        else:
            pf = PrintFormat()
            _apply_print_format_fields(pf, row, style_id)
            db.add(pf)
            db.flush([pf])
            upserted.append(pf)
            logger.info("[print seed] created doctype=%s code=%s default=%s",
                        pf.doctype, pf.code, pf.is_default_for_doctype)

        existing_by_key[key] = pf

    db.flush()

    # 4) ENFORCE ONE DEFAULT per (doctype, company_id)
    # If multiple defaults exist, keep the one that is default in PRINT_FORMAT_DEFS
    desired_default_by_group: Dict[Tuple[str, Optional[int]], str] = {}
    for row in PRINT_FORMAT_DEFS:
        if bool(row.get("is_default_for_doctype")):
            grp = (row["doctype"], row.get("company_id"))
            desired_default_by_group[grp] = row["code"]

    all_formats = db.scalars(select(PrintFormat)).all()

    # group defaults
    grouped_defaults: Dict[Tuple[str, Optional[int]], List[PrintFormat]] = {}
    for pf in all_formats:
        if pf.is_default_for_doctype:
            grouped_defaults.setdefault((pf.doctype, pf.company_id), []).append(pf)

    fixed_defaults = 0
    for grp, defaults in grouped_defaults.items():
        if len(defaults) <= 1:
            continue

        keep_code = desired_default_by_group.get(grp)
        keep: Optional[PrintFormat] = None

        if keep_code:
            keep = next((x for x in defaults if x.code == keep_code), None)

        # fallback: keep first standard, else first
        if keep is None:
            keep = next((x for x in defaults if x.is_standard), None) or defaults[0]

        for pf in defaults:
            if pf.id != keep.id:
                pf.is_default_for_doctype = False
                fixed_defaults += 1
                logger.info(
                    "[print seed] unset extra default doctype=%s company_id=%s code=%s (keeping %s)",
                    pf.doctype, pf.company_id, pf.code, keep.code
                )
        db.flush(defaults)

    if fixed_defaults:
        logger.info("🧯 Fixed %s extra default flags.", fixed_defaults)

    logger.info("✅ Print Formats seeded / updated / cleaned.")


# ---------------------- seed letterheads ----------------------
def seed_print_letterheads(db: Session) -> None:
    logger.info("🌱 Seeding Print Letterheads...")

    existing = {(lh.company_id, lh.code): lh for lh in db.scalars(select(PrintLetterhead)).all()}

    for row in PRINT_LETTERHEAD_DEFS:
        key = (row["company_id"], row["code"])
        lh = existing.get(key)

        if lh:
            for k, v in row.items():
                setattr(lh, k, v)
            db.flush([lh])
        else:
            db.add(PrintLetterhead(**row))

    db.flush()
    logger.info("✅ Print Letterheads seeded.")


# ---------------------- public entry ----------------------
def seed_print_framework(db: Session) -> None:
    """
    Seeding order:
      - styles
      - settings
      - formats
      - letterheads
    """
    seed_print_styles(db)
    seed_print_settings(db)
    seed_print_formats(db)
    seed_print_letterheads(db)
