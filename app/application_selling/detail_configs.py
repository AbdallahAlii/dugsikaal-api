from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_selling.query_builders.detail_builders import (
    # resolvers
    resolve_sales_quotation_by_code,

    resolve_sales_invoice_by_code,
    # loaders
    load_sales_quotation,

    load_sales_invoice,
)

SELLING_DETAIL_CONFIGS = {
    "sales_quotations": DetailConfig(
        permission_tag="Sales Quotation",
        loader=load_sales_quotation,
        resolver_map={"code": resolve_sales_quotation_by_code},
        cache_enabled=False,
    ),

    "sales_invoices": DetailConfig(
        permission_tag="Sales Invoice",
        loader=load_sales_invoice,
        resolver_map={"code": resolve_sales_invoice_by_code},
        cache_enabled=False,
    ),
}

def register_selling_detail_configs() -> None:
    register_detail_configs("selling", SELLING_DETAIL_CONFIGS)
