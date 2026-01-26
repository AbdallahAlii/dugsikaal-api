# app/seed_data/print_formats/settings.py
from __future__ import annotations

from typing import Dict, Any, List

# Very small for now; you can extend later.
PRINT_SETTINGS_DEFS: List[Dict[str, Any]] = [
    dict(
        company_id=None,                 # global row
        send_print_as_pdf=True,
        send_email_print_attachments_as_pdf=True,
        repeat_header_footer_in_pdf=True,
        pdf_page_size="A4",
        print_with_letterhead=True,
        compact_item_print=False,
        print_uom_after_qty=True,
        allow_print_for_draft=False,
        always_add_draft_heading=True,
        allow_page_break_inside_tables=False,
        allow_print_for_cancelled=False,
        print_taxes_with_zero_amount=False,
        default_print_style_code="redesign",  # resolved to id at seed time
        default_font_family=None,
        default_font_size_pt=None,
        default_language=None,
        additional_options=None,
    )
]
