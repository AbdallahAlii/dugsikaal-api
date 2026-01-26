from __future__ import annotations

from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext

from app.application_print.registry.print_registry import (
    PrintConfig,
    register_print_configs,
)
from app.application_selling.query_builders.detail_builders import (
    resolve_sales_invoice_by_code,

    resolve_sales_quotation_by_code,
    load_sales_invoice,

    load_sales_quotation,
)


# Thin wrappers so print URLs can use the document CODE (like SINV-0001)
def _load_sales_invoice_by_code(
    s: Session,
    ctx: AffiliationContext,
    identifier: str,
):
    """
    identifier = Sales Invoice code (e.g. SINV-0001)
    """
    invoice_id = resolve_sales_invoice_by_code(s, ctx, identifier)
    return load_sales_invoice(s, ctx, invoice_id)



def _load_sales_quotation_by_code(
    s: Session,
    ctx: AffiliationContext,
    identifier: str,
):
    """
    identifier = Sales Quotation code (e.g. SQ-0001)
    """
    sq_id = resolve_sales_quotation_by_code(s, ctx, identifier)
    return load_sales_quotation(s, ctx, sq_id)

#
# SELLING_PRINT_CONFIGS: dict[str, PrintConfig] = {
#     # /print/selling/sales_invoices/SINV-0001
#     "sales_invoices": PrintConfig(
#         permission_tag="Sales Invoice",
#         doctype="SalesInvoice",
#         loader=_load_sales_invoice_by_code,
#     ),
#     # /print/selling/sales_delivery_notes/DN-0001
#     "sales_delivery_notes": PrintConfig(
#         permission_tag="Sales Delivery Note",
#         doctype="SalesDeliveryNote",
#         loader=_load_delivery_note_by_code,
#     ),
#     # /print/selling/sales_quotations/SQ-0001
#     "sales_quotations": PrintConfig(
#         permission_tag="Sales Quotation",
#         doctype="SalesQuotation",
#         loader=_load_sales_quotation_by_code,
#     ),
# }

SELLING_PRINT_CONFIGS: dict[str, PrintConfig] = {
    # Use "sales_invoices" NOT "sellingsalesinvoices"
    "sales_invoices": PrintConfig(  # ← MUST be "sales_invoices" to match URL
        permission_tag="Sales Invoice",
        doctype="SalesInvoice",
        loader=_load_sales_invoice_by_code,
    ),

    "sales_quotations": PrintConfig(
        permission_tag="Sales Quotation",
        doctype="SalesQuotation",
        loader=_load_sales_quotation_by_code,
    ),
}

def register_selling_print_configs() -> None:
    """
    Called from app.application_selling.__init__.register_module_prints().
    """
    register_print_configs("selling", SELLING_PRINT_CONFIGS)
