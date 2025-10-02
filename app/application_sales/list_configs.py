# app/application_selling/list_configs.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_sales.models import (
    SalesQuotation, SalesDeliveryNote, SalesInvoice, SalesReturn
)
from app.application_parties.parties_models import Party
from app.application_sales.query_builders.build_selling_queries import (
    build_sales_quotations_query,
    build_sales_delivery_notes_query,
    build_sales_invoices_query,
    build_sales_returns_query,
)

SELLING_LIST_CONFIGS = {
    "sales_quotations": ListConfig(
        permission_tag="Sales Quotation",
        query_builder=build_sales_quotations_query,
        search_fields=[SalesQuotation.code, Party.name],
        sort_fields={
            "posting_date": SalesQuotation.posting_date,
            "document_number": SalesQuotation.code,
            "id": SalesQuotation.id,
        },
        filter_fields={
            "company_id": SalesQuotation.company_id,
            "branch_id": SalesQuotation.branch_id,
            "customer_id": SalesQuotation.customer_id,
            "status": SalesQuotation.doc_status,
            "posting_date": SalesQuotation.posting_date,
        },
        cache_enabled=False,
    ),
    "sales_delivery_notes": ListConfig(
        permission_tag="Sales Delivery Note",
        query_builder=build_sales_delivery_notes_query,
        search_fields=[SalesDeliveryNote.code, Party.name],
        sort_fields={
            "posting_date": SalesDeliveryNote.posting_date,
            "document_number": SalesDeliveryNote.code,
            "total_amount": SalesDeliveryNote.total_amount,
            "id": SalesDeliveryNote.id,
        },
        filter_fields={
            "company_id": SalesDeliveryNote.company_id,
            "branch_id": SalesDeliveryNote.branch_id,
            "customer_id": SalesDeliveryNote.customer_id,
            "status": SalesDeliveryNote.doc_status,
            "posting_date": SalesDeliveryNote.posting_date,
        },
        cache_enabled=False,
    ),
    "sales_invoices": ListConfig(
        permission_tag="Sales Invoice",
        query_builder=build_sales_invoices_query,
        search_fields=[SalesInvoice.code, Party.name],
        sort_fields={
            "posting_date": SalesInvoice.posting_date,
            "document_number": SalesInvoice.code,
            "total_amount": SalesInvoice.total_amount,
            "amount_paid": SalesInvoice.amount_paid,
            "balance_due": SalesInvoice.balance_due,
            "id": SalesInvoice.id,
        },
        filter_fields={
            "company_id": SalesInvoice.company_id,
            "branch_id": SalesInvoice.branch_id,
            "customer_id": SalesInvoice.customer_id,
            "status": SalesInvoice.doc_status,
            "posting_date": SalesInvoice.posting_date,
            "update_stock": SalesInvoice.update_stock,
        },
        cache_enabled=False,
    ),
    "sales_returns": ListConfig(
        permission_tag="Sales Return",
        query_builder=build_sales_returns_query,
        search_fields=[SalesReturn.code, Party.name],
        sort_fields={
            "posting_date": SalesReturn.posting_date,
            "document_number": SalesReturn.code,
            "id": SalesReturn.id,
        },
        filter_fields={
            "company_id": SalesReturn.company_id,
            "branch_id": SalesReturn.branch_id,
            "customer_id": SalesReturn.customer_id,
            "status": SalesReturn.doc_status,
            "posting_date": SalesReturn.posting_date,
        },
        cache_enabled=False,
    ),
}

def register_module_lists() -> None:
    register_list_configs("selling", SELLING_LIST_CONFIGS)