# app/application_selling/list_config.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_selling.models import (
    SalesQuotation,  SalesInvoice
)
from app.application_parties.parties_models import Party
from app.application_selling.query_builders.build_selling_queries import (
    build_sales_quotations_query,

    build_sales_invoices_query,
)
from app.application_org.models.company import Branch
SELLING_LIST_CONFIGS = {
    "sales_invoices": ListConfig(
        permission_tag="Sales Invoice",
        query_builder=build_sales_invoices_query,
        # search by code or customer
        search_fields=[SalesInvoice.code, Party.name],

        # allow common sorts; expose both "code" and "document_number" for compatibility
        sort_fields={
            "posting_date": SalesInvoice.posting_date,
            "code": SalesInvoice.code,
            "document_number": SalesInvoice.code,
            "total_amount": SalesInvoice.total_amount,
            "id": SalesInvoice.id,
        },
        # keep powerful filters even if not returned in columns
        filter_fields={
            "company_id": SalesInvoice.company_id,
            "branch_id": SalesInvoice.branch_id,
            "branch_name": Branch.name,
            "customer_id": SalesInvoice.customer_id,
            "status": SalesInvoice.doc_status,
            "posting_date": SalesInvoice.posting_date,
            "due_date": SalesInvoice.due_date,
        },
        cache_enabled=False,
    ),

    "sales_quotations": ListConfig(
        permission_tag="Sales Quotation",
        query_builder=build_sales_quotations_query,
        search_fields=[SalesQuotation.code, Party.name],
        sort_fields={
            "posting_date": SalesQuotation.posting_date,
            "code": SalesQuotation.code,
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
}

def register_module_lists() -> None:
    register_list_configs("selling", SELLING_LIST_CONFIGS)
