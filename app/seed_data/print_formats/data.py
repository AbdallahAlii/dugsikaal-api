# # app/seed_data/print_formats/data.py
# from __future__ import annotations
#
# from typing import Any, Dict, List, Optional
#
# # =============================================================================
# # 1) GLOBAL PRINT STYLES (similar to ERPNext: Modern, Monochrome, Classic, Redesign)
# # =============================================================================
#
# PRINT_STYLES: List[Dict[str, Any]] = [
#     # --- Modern ---
#     dict(
#         code="modern",
#         name="Modern",
#         description="Modern ERP-style print theme.",
#         css="""
# .print-heading {
#     text-align: right;
#     text-transform: uppercase;
#     color: #666;
#     padding-bottom: 20px;
#     margin-bottom: 20px;
#     border-bottom: 1px solid #d1d8dd;
# }
#
# .print-heading h2 {
#     font-size: 24px;
# }
#
# .print-format th {
#     background-color: #eee !important;
#     border-bottom: 0px !important;
# }
#
# .print-format .primary.compact-item {
#     font-weight: bold;
# }
#
# /* modern format */
#         """,
#         # Global templates (no company), so:
#         company_id=None,
#         is_default_global=False,
#         is_disabled=False,
#     ),
#
#     # --- Monochrome ---
#     dict(
#         code="monochrome",
#         name="Monochrome",
#         description="Monochrome black & white print theme.",
#         css="""
# .print-format * {
#     color: #000 !important;
# }
#
# .print-format .alert {
#     background-color: inherit;
#     border: 1px dashed #333;
# }
#
# .print-format .table-bordered,
# .print-format .table-bordered > thead > tr > th,
# .print-format .table-bordered > tbody > tr > th,
# .print-format .table-bordered > tfoot > tr > th,
# .print-format .table-bordered > thead > tr > td,
# .print-format .table-bordered > tbody > tr > td,
# .print-format .table-bordered > tfoot > tr > td {
#     border: 1px solid #333;
# }
#
# .print-format hr {
#     border-top: 1px solid #333;
# }
#
# .print-heading {
#     border-bottom: 2px solid #333;
# }
#         """,
#         company_id=None,
#         is_default_global=False,
#         is_disabled=False,
#     ),
#
#     # --- Classic ---
#     dict(
#         code="classic",
#         name="Classic",
#         description="Classic serif-style print look.",
#         css="""
# /*
#     common style for whole page
#     This should include:
#     + page size related settings
#     + font family settings
#     + line spacing settings
# */
# .print-format div,
# .print-format span,
# .print-format td,
# .print-format h1,
# .print-format h2,
# .print-format h3,
# .print-format h4 {
#     font-family: Georgia, serif;
# }
#
# /* classic format */
#         """,
#         company_id=None,
#         is_default_global=False,
#         is_disabled=False,
#     ),
#
#     # --- Redesign (default) ---
#     dict(
#         code="redesign",
#         name="Redesign",
#         description="Redesigned default Ganacsikaal print style.",
#         css="""
# .print-format {
#     font-size: 13px;
#     background: white;
# }
#
# .print-heading {
#     border-bottom: 1px solid #f4f5f6;
#     padding-bottom: 5px;
#     margin-bottom: 10px;
# }
#
# .print-heading h2 {
#     font-size: 24px;
# }
#
# .print-heading h2 div {
#     font-weight: 600;
# }
#
# .print-heading small {
#     font-size: 13px !important;
#     font-weight: normal;
#     line-height: 2.5;
#     color: #4c5a67;
# }
#
# .print-format .letter-head {
#     margin-bottom: 30px;
# }
#
# .print-format label {
#     font-weight: normal;
#     font-size: 13px;
#     color: #4C5A67;
#     margin-bottom: 0;
# }
#
# .print-format .data-field {
#     margin-top: 0;
#     margin-bottom: 0;
# }
#
# .print-format .value {
#     color: #192734;
#     line-height: 1.8;
# }
#
# .print-format .section-break:not(:last-child) {
#     margin-bottom: 0;
# }
#
# .print-format .row:not(.section-break) {
#     line-height: 1.6;
#     margin-top: 15px !important;
# }
#
# .print-format .important .value {
#     font-size: 13px;
#     font-weight: 600;
# }
#
# .print-format th {
#     color: #74808b;
#     font-weight: normal;
#     border-bottom-width: 1px !important;
# }
#
# .print-format .table-bordered td, .print-format .table-bordered th {
#     border: 1px solid #f4f5f6;
# }
#
# .print-format .table-bordered {
#     border: 1px solid #f4f5f6;
# }
#
# .print-format td, .print-format th {
#     padding: 10px !important;
# }
#
# .print-format .primary.compact-item {
#     font-weight: normal;
# }
#
# .print-format table td .value {
#     font-size: 12px;
#     line-height: 1.8;
# }
#         """,
#         company_id=None,
#         is_default_global=True,   # this one is default
#         is_disabled=False,
#     ),
# ]
#
#
# # =============================================================================
# # 2) PRINT FORMAT TEMPLATES (HTML + meta)
# #    For now: PaymentEntry standard receipt. You can add SalesInvoice, etc. easily.
# # =============================================================================
#
# PAYMENT_ENTRY_STANDARD_HTML = r"""
# <!DOCTYPE html>
# <html>
# <head>
#     <meta charset="utf-8" />
#     <title>Payment {{ doc.code }}</title>
#     <style>
#         body {
#             font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
#             font-size: 12px;
#             color: #222;
#             margin: 0;
#             padding: 0;
#         }
#
#         .print-wrapper {
#             width: 800px;
#             margin: 0 auto;
#             padding: 24px 32px;
#         }
#
#         .header {
#             display: flex;
#             justify-content: space-between;
#             align-items: flex-start;
#             border-bottom: 2px solid #111;
#             padding-bottom: 10px;
#             margin-bottom: 16px;
#         }
#
#         .company-name {
#             font-size: 18px;
#             font-weight: 600;
#         }
#
#         .doc-title {
#             font-size: 20px;
#             font-weight: 600;
#             text-transform: uppercase;
#             text-align: right;
#         }
#
#         .meta-table {
#             width: 100%;
#             border-collapse: collapse;
#             margin-bottom: 12px;
#         }
#
#         .meta-table td {
#             padding: 2px 0;
#             vertical-align: top;
#         }
#
#         .meta-label {
#             font-weight: 600;
#             width: 120px;
#         }
#
#         .info-section {
#             margin-bottom: 8px;
#         }
#
#         .info-title {
#             font-weight: 600;
#             margin-bottom: 4px;
#             text-transform: uppercase;
#             font-size: 11px;
#             color: #555;
#         }
#
#         .table {
#             width: 100%;
#             border-collapse: collapse;
#             margin-top: 8px;
#             margin-bottom: 12px;
#         }
#
#         .table th,
#         .table td {
#             border: 1px solid #ccc;
#             padding: 4px 6px;
#             font-size: 11px;
#         }
#
#         .table th {
#             background: #f7f7f7;
#             font-weight: 600;
#         }
#
#         .text-right { text-align: right; }
#         .text-center { text-align: center; }
#
#         .totals-row td {
#             font-weight: 600;
#         }
#
#         .section-title {
#             font-weight: 600;
#             text-transform: uppercase;
#             font-size: 12px;
#             margin-top: 10px;
#             margin-bottom: 4px;
#         }
#
#         .remarks {
#             border: 1px solid #ddd;
#             padding: 6px;
#             min-height: 40px;
#             font-size: 11px;
#             white-space: pre-wrap;
#         }
#
#         .signature-row {
#             margin-top: 30px;
#             display: flex;
#             justify-content: space-between;
#         }
#
#         .signature-box {
#             width: 30%;
#             text-align: center;
#             font-size: 11px;
#         }
#
#         .signature-line {
#             border-top: 1px solid #000;
#             margin-top: 40px;
#             padding-top: 4px;
#         }
#     </style>
# </head>
# <body>
# <div class="print-wrapper">
#
#     <!-- HEADER -->
#     <div class="header">
#         <div>
#             <div class="company-name">
#                 {{ doc.company.name if doc.company is mapping else doc.company }}
#             </div>
#             <div style="font-size: 11px; color: #555;">
#                 {% if ctx.company_name %}
#                     {{ ctx.company_name }}
#                 {% endif %}
#             </div>
#         </div>
#
#         <div style="text-align: right;">
#             <div class="doc-title">Payment Receipt</div>
#             <table class="meta-table">
#                 <tr>
#                     <td class="meta-label">Payment #:</td>
#                     <td>{{ doc.code or doc.name or doc.id }}</td>
#                 </tr>
#                 <tr>
#                     <td class="meta-label">Date:</td>
#                     <td>{{ doc.posting_date }}</td>
#                 </tr>
#                 <tr>
#                     <td class="meta-label">Mode of Payment:</td>
#                     <td>{{ doc.mode_of_payment }}</td>
#                 </tr>
#                 <tr>
#                     <td class="meta-label">Currency:</td>
#                     <td>{{ doc.currency or "USD" }}</td>
#                 </tr>
#             </table>
#         </div>
#     </div>
#
#     <!-- PARTY INFO -->
#     <div class="info-section">
#         <div class="info-title">Received From</div>
#         <table class="meta-table">
#             <tr>
#                 <td class="meta-label">Party:</td>
#                 <td>
#                     {% if doc.party is mapping %}
#                         {{ doc.party.name }}
#                     {% else %}
#                         {{ doc.party }}
#                     {% endif %}
#                 </td>
#             </tr>
#             <tr>
#                 <td class="meta-label">Amount:</td>
#                 <td>
#                     {{ "{:,.2f}".format(doc.paid_amount or doc.base_paid_amount or 0) }}
#                     {{ doc.currency or "" }}
#                 </td>
#             </tr>
#         </table>
#     </div>
#
#     <!-- ALLOCATIONS TABLE -->
#     {% if doc.references %}
#         <div class="section-title">Allocations</div>
#         <table class="table">
#             <thead>
#                 <tr>
#                     <th class="text-center" style="width: 40px;">#</th>
#                     <th>Voucher Type</th>
#                     <th>Voucher No.</th>
#                     <th>Due Date</th>
#                     <th class="text-right">Invoice Amount</th>
#                     <th class="text-right">Allocated Amount</th>
#                 </tr>
#             </thead>
#             <tbody>
#                 {% set total_alloc = 0 %}
#                 {% for row in doc.references %}
#                     {% set total_alloc = total_alloc + (row.allocated_amount or 0) %}
#                     <tr>
#                         <td class="text-center">{{ row.idx or loop.index }}</td>
#                         <td>{{ row.voucher_type }}</td>
#                         <td>{{ row.voucher_no }}</td>
#                         <td>{{ row.due_date }}</td>
#                         <td class="text-right">
#                             {{ "{:,.2f}".format(row.amount or 0) }}
#                         </td>
#                         <td class="text-right">
#                             {{ "{:,.2f}".format(row.allocated_amount or 0) }}
#                         </td>
#                     </tr>
#                 {% endfor %}
#                 <tr class="totals-row">
#                     <td colspan="5" class="text-right">Total Allocated</td>
#                     <td class="text-right">
#                         {{ "{:,.2f}".format(total_alloc) }}
#                     </td>
#                 </tr>
#             </tbody>
#         </table>
#     {% endif %}
#
#     <!-- REMARKS -->
#     <div class="section-title">Remarks</div>
#     <div class="remarks">
#         {{ doc.remarks or "" }}
#     </div>
#
#     <!-- SIGNATURES -->
#     <div class="signature-row">
#         <div class="signature-box">
#             <div class="signature-line">Prepared By</div>
#         </div>
#         <div class="signature-box">
#             <div class="signature-line">Checked By</div>
#         </div>
#         <div class="signature-box">
#             <div class="signature-line">Received By</div>
#         </div>
#     </div>
#
# </div>
# </body>
# </html>
# """
#
# # =============================================================================
# # 3) PRINT FORMAT DEFINITIONS (metadata + which template/html to use)
# # =============================================================================
# # NOTE:
# # - print_format_type is a STRING ("Standard Builder", "Jinja", "Raw", "External URL")
# #   The seeder will map this string to PrintFormatType enum.
# # - print_style_code is optional; if set, seeder will link to that PrintStyle.
#
# PRINT_FORMAT_DEFS: List[Dict[str, Any]] = [
#     # -------------------------------------------------------------------------
#     # PaymentEntry standard receipt (global)
#     # -------------------------------------------------------------------------
#     dict(
#         doctype="PaymentEntry",      # must match your doctype name
#         module="accounting",         # logical module name
#         code="standard",
#         name="Standard Payment Receipt",
#         company_id=None,             # global default (no specific company)
#         print_format_type="Jinja",
#         is_standard=True,
#         is_default_for_doctype=True,
#         custom_format=True,
#         raw_printing=False,
#         margin_top_mm=15,
#         margin_bottom_mm=15,
#         margin_left_mm=10,
#         margin_right_mm=10,
#         font_size_pt=None,
#         google_font=None,
#         align_labels_to_right=False,
#         show_section_headings=True,
#         show_line_breaks_after_sections=True,
#         template_html=PAYMENT_ENTRY_STANDARD_HTML,
#         custom_css=None,
#         external_url=None,
#         raw_payload_template=None,
#         default_letterhead_code=None,   # could be used later if you seed letterheads
#         print_style_code="redesign",    # link to global "redesign" style
#         layout_options=None,
#     ),
#
# ]
