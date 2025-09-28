from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_buying.models import (
    PurchaseQuotation, PurchaseReceipt, PurchaseInvoice, PurchaseReturn
)
from app.application_parties.parties_models import Party
from app.application_buying.query_builders.build_buying_queries import (
    build_purchase_quotations_query,
    build_purchase_receipts_query,
    build_purchase_invoices_query,
    build_purchase_returns_query,
)

BUYING_LIST_CONFIGS = {
    "purchase_receipts": ListConfig(
        permission_tag="Purchase Receipt",
        query_builder=build_purchase_receipts_query,
        search_fields=[PurchaseReceipt.code, Party.name],  # code + supplier_name
        sort_fields={
            "posting_date": PurchaseReceipt.posting_date,
            "code": PurchaseReceipt.code,
            "total_amount": PurchaseReceipt.total_amount,
            "id": PurchaseReceipt.id,
        },
        filter_fields={
            "company_id": PurchaseReceipt.company_id,    # usually implicit via context
            "branch_id": PurchaseReceipt.branch_id,
            "supplier_id": PurchaseReceipt.supplier_id,  # optional
            "doc_status": PurchaseReceipt.doc_status,
            "posting_date": PurchaseReceipt.posting_date,  # repo applies range
        },
        cache_enabled=False,
    ),
    "purchase_invoices": ListConfig(
        permission_tag="Purchase Invoice",  # << fixed (no space)
        query_builder=build_purchase_invoices_query,
        search_fields=[PurchaseInvoice.code, Party.name],
        sort_fields={
            "posting_date": PurchaseInvoice.posting_date,
            "code": PurchaseInvoice.code,
            "total_amount": PurchaseInvoice.total_amount,
            "amount_paid": PurchaseInvoice.amount_paid,
            "id": PurchaseInvoice.id,
        },
        filter_fields={
            "company_id": PurchaseInvoice.company_id,
            "branch_id": PurchaseInvoice.branch_id,
            "supplier_id": PurchaseInvoice.supplier_id,  # optional
            "doc_status": PurchaseInvoice.doc_status,
            "posting_date": PurchaseInvoice.posting_date,
        },
        cache_enabled=False,
    ),
    "purchase_quotations": ListConfig(
        permission_tag="Purchase Quotation",
        query_builder=build_purchase_quotations_query,
        search_fields=[PurchaseQuotation.code, Party.name],
        sort_fields={
            "posting_date": PurchaseQuotation.posting_date,
            "code": PurchaseQuotation.code,
            "id": PurchaseQuotation.id,
        },
        filter_fields={
            "company_id": PurchaseQuotation.company_id,
            "branch_id": PurchaseQuotation.branch_id,
            "supplier_id": PurchaseQuotation.supplier_id,  # optional
            "doc_status": PurchaseQuotation.doc_status,
            "posting_date": PurchaseQuotation.posting_date,
        },
        cache_enabled=False,
    ),
    "purchase_returns": ListConfig(
        permission_tag="Purchase Return",
        query_builder=build_purchase_returns_query,
        search_fields=[PurchaseReturn.code, Party.name],
        sort_fields={
            "posting_date": PurchaseReturn.posting_date,
            "code": PurchaseReturn.code,
            "id": PurchaseReturn.id,
        },
        filter_fields={
            "company_id": PurchaseReturn.company_id,
            "branch_id": PurchaseReturn.branch_id,
            "supplier_id": PurchaseReturn.supplier_id,  # optional
            "doc_status": PurchaseReturn.doc_status,
            "posting_date": PurchaseReturn.posting_date,
        },
        cache_enabled=False,
    ),
}

register_list_configs("buying", BUYING_LIST_CONFIGS)
