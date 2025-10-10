# app/application_buying/list_configs.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_buying.models import (
    PurchaseQuotation, PurchaseReceipt, PurchaseInvoice
)
from app.application_parties.parties_models import Party
from app.application_buying.query_builders.build_buying_queries import (
    build_purchase_quotations_query,
    build_purchase_receipts_query,
    build_purchase_invoices_query,

)

BUYING_LIST_CONFIGS = {
    "purchase_quotations": ListConfig(
        permission_tag="Purchase Quotation",
        query_builder=build_purchase_quotations_query,
        search_fields=[PurchaseQuotation.code, Party.name],
        sort_fields={
            "posting_date": PurchaseQuotation.posting_date,
            "document_number": PurchaseQuotation.code,
            "id": PurchaseQuotation.id,
        },
        filter_fields={
            "company_id": PurchaseQuotation.company_id,
            "branch_id": PurchaseQuotation.branch_id,
            "supplier_id": PurchaseQuotation.supplier_id,
            "status": PurchaseQuotation.doc_status,
            "posting_date": PurchaseQuotation.posting_date,
        },
        cache_enabled=False,
    ),
    "purchase_receipts": ListConfig(
        permission_tag="Purchase Receipt",
        query_builder=build_purchase_receipts_query,
        search_fields=[PurchaseReceipt.code, Party.name],
        sort_fields={
            "posting_date": PurchaseReceipt.posting_date,
            "document_number": PurchaseReceipt.code,
            "total_amount": PurchaseReceipt.total_amount,
            "id": PurchaseReceipt.id,
        },
        filter_fields={
            "company_id": PurchaseReceipt.company_id,
            "branch_id": PurchaseReceipt.branch_id,
            "supplier_id": PurchaseReceipt.supplier_id,
            "status": PurchaseReceipt.doc_status,
            "posting_date": PurchaseReceipt.posting_date,
        },
        cache_enabled=False,
    ),
    "purchase_invoices": ListConfig(
        permission_tag="Purchase Invoice",
        query_builder=build_purchase_invoices_query,
        search_fields=[PurchaseInvoice.code, Party.name],
        sort_fields={
            "posting_date": PurchaseInvoice.posting_date,
            "document_number": PurchaseInvoice.code,
            "total_amount": PurchaseInvoice.total_amount,
            # "amount_paid": PurchaseInvoice.amount_paid,
            # "balance_due": PurchaseInvoice.balance_due,
            "id": PurchaseInvoice.id,
        },
        filter_fields={
            "company_id": PurchaseInvoice.company_id,
            "branch_id": PurchaseInvoice.branch_id,
            "supplier_id": PurchaseInvoice.supplier_id,
            "status": PurchaseInvoice.doc_status,
            "posting_date": PurchaseInvoice.posting_date,
            "update_stock": PurchaseInvoice.update_stock,
        },
        cache_enabled=False,
    ),

}

def register_module_lists() -> None:
    register_list_configs("buying", BUYING_LIST_CONFIGS)