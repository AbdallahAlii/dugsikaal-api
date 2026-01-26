from __future__ import annotations
from typing import List, Dict, Any
from app.application_print.models import PrintAlign

PRINT_LETTERHEAD_DEFS: List[Dict[str, Any]] = [

    # ---------------- GLOBAL ----------------
    dict(
        company_id=1,  # any existing company OR pick first company
        name="Global Default Letterhead",
        code="global_default",
        header_based_on_image=True,
        header_image_key="logos/global_logo.png",
        header_image_height=60,
        header_image_width=None,
        header_align=PrintAlign.LEFT,
        footer_based_on_image=False,
        footer_html="<hr><div style='text-align:center;font-size:11px'>System Generated</div>",
        is_default_for_company=False,
    ),

    # ---------------- ZAAD TECH (36) ----------------
    dict(
        company_id=36,
        name="Zaad Tech Sales Letterhead",
        code="zt_sales",
        header_based_on_image=True,
        header_image_key="logos/zaad_sales.png",
        header_image_height=70,
        header_align=PrintAlign.LEFT,
        is_default_for_company=True,
    ),

    dict(
        company_id=36,
        name="Zaad Tech Payment Letterhead",
        code="zt_payment",
        header_based_on_image=True,
        header_image_key="logos/zaad_payment.png",
        header_image_height=70,
        header_align=PrintAlign.CENTER,
        is_default_for_company=False,
    ),

    dict(
        company_id=36,
        name="Zaad Tech Purchase Letterhead",
        code="zt_purchase",
        header_based_on_image=True,
        header_image_key="logos/zaad_purchase.png",
        header_image_height=70,
        header_align=PrintAlign.LEFT,
        is_default_for_company=False,
    ),
]
