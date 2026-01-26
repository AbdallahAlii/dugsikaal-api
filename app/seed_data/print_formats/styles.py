# app/seed_data/print_formats/styles.py
from __future__ import annotations

from typing import List, Dict, Any

PRINT_STYLE_DEFS: List[Dict[str, Any]] = [
    # --- Modern (from your example) ---
    dict(
        code="modern",
        name="Modern",
        description="Clean modern ERP-style print.",
        css="""
.print-format {
    font-size: 13px;
    background: #ffffff;
}
.print-heading {
    text-align: right;
    text-transform: uppercase;
    color: #666;
    padding-bottom: 20px;
    margin-bottom: 20px;
    border-bottom: 1px solid #d1d8dd;
}
.print-heading h2 {
    font-size: 24px;
}
.print-format th {
    background-color: #eee !important;
    border-bottom: 0px !important;
}
.print-format .primary.compact-item {
    font-weight: bold;
}
        """.strip(),
        is_default_global=False,
    ),

    # --- Monochrome ---
    dict(
        code="monochrome",
        name="Monochrome",
        description="Black & white print, good for dot-matrix.",
        css="""
.print-format * {
    color: #000 !important;
}
.print-format .alert {
    background-color: inherit;
    border: 1px dashed #333;
}
.print-format .table-bordered,
.print-format .table-bordered > thead > tr > th,
.print-format .table-bordered > tbody > tr > th,
.print-format .table-bordered > tfoot > tr > th,
.print-format .table-bordered > thead > tr > td,
.print-format .table-bordered > tbody > tr > td,
.print-format .table-bordered > tfoot > tr > td {
    border: 1px solid #333;
}
.print-format hr {
    border-top: 1px solid #333;
}
.print-heading {
    border-bottom: 2px solid #333;
}
        """.strip(),
        is_default_global=False,
    ),

    # --- Classic (Georgia-like) ---
    dict(
        code="classic",
        name="Classic",
        description="Serif classic style (Georgia).",
        css="""
.print-format div,
.print-format span,
.print-format td,
.print-format h1,
.print-format h2,
.print-format h3,
.print-format h4 {
    font-family: Georgia, serif;
}
        """.strip(),
        is_default_global=False,
    ),

    # --- Redesign (default) ---
    dict(
        code="redesign",
        name="Redesign",
        description="ERPNext-style redesigned print.",
        css="""
.print-format {
    font-size: 13px;
    background: white;
}
.print-heading {
    border-bottom: 1px solid #f4f5f6;
    padding-bottom: 5px;
    margin-bottom: 10px;
}
.print-heading h2 {
    font-size: 24px;
}
.print-heading h2 div {
    font-weight: 600;
}
.print-heading small {
    font-size: 13px !important;
    font-weight: normal;
    line-height: 2.5;
    color: #4c5a67;
}
.print-format .letter-head {
    margin-bottom: 30px;
}
.print-format label {
    font-weight: normal;
    font-size: 13px;
    color: #4C5A67;
    margin-bottom: 0;
}
.print-format .data-field {
    margin-top: 0;
    margin-bottom: 0;
}
.print-format .value {
    color: #192734;
    line-height: 1.8;
}
.print-format .section-break:not(:last-child) {
    margin-bottom: 0;
}
.print-format .row:not(.section-break) {
    line-height: 1.6;
    margin-top: 15px !important;
}
.print-format .important .value {
    font-size: 13px;
    font-weight: 600;
}
.print-format th {
    color: #74808b;
    font-weight: normal;
    border-bottom-width: 1px !important;
}
.print-format .table-bordered td,
.print-format .table-bordered th {
    border: 1px solid #f4f5f6;
}
.print-format .table-bordered {
    border: 1px solid #f4f5f6;
}
.print-format td,
.print-format th {
    padding: 10px !important;
}
.print-format .primary.compact-item {
    font-weight: normal;
}
.print-format table td .value {
    font-size: 12px;
    line-height: 1.8;
}
        """.strip(),
        is_default_global=True,    # ← global default style
    ),
]
