# app/application_buying/detail_configs.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_buying.query_builders.detail_builders import (
    # resolvers
    resolve_quotation_by_code, resolve_receipt_by_code,
    resolve_invoice_by_code, resolve_return_by_code,
    # loaders
    load_purchase_quotation, load_purchase_receipt,
    load_purchase_invoice, load_purchase_return,
)

# NOTE:
# • code-only identifiers (no "id" resolver), so default lookup is by code
# • cache disabled for freshness and simplicity

BUYING_DETAIL_CONFIGS = {
    "purchase_quotations": DetailConfig(
        permission_tag="Purchase Quotation",
        loader=load_purchase_quotation,
        resolver_map={
            "code": resolve_quotation_by_code,
        },
        cache_enabled=False,
    ),
    "purchase_receipts": DetailConfig(
        permission_tag="Purchase Receipt",
        loader=load_purchase_receipt,
        resolver_map={
            "code": resolve_receipt_by_code,
        },
        cache_enabled=False,
    ),
    "purchase_invoices": DetailConfig(
        permission_tag="Purchase Invoice",
        loader=load_purchase_invoice,
        resolver_map={
            "code": resolve_invoice_by_code,
        },
        cache_enabled=False,
    ),
    "purchase_returns": DetailConfig(
        permission_tag="Purchase Return",
        loader=load_purchase_return,
        resolver_map={
            "code": resolve_return_by_code,
        },
        cache_enabled=False,
    ),
}

def register_buying_detail_configs() -> None:
    register_detail_configs("buying", BUYING_DETAIL_CONFIGS)
