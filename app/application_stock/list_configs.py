from __future__ import annotations
from sqlalchemy import func, desc

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_stock.query_builders.build_bins_query import build_bins_query
from app.application_stock.query_builders.build_stock_reconciliations_query import build_stock_reconciliations_query
from app.application_stock.stock_models import Warehouse, Bin, StockReconciliation
from app.application_org.models.company import Branch, Company
from app.application_stock.query_builders.build_warehouses_query import build_warehouses_query
from app.auth.models.users import User
from app.application_nventory.inventory_models import Item

STOCK_LIST_CONFIGS = {
    "warehouses": ListConfig(
        permission_tag="Warehouse",
        query_builder=build_warehouses_query,
        search_fields=[Warehouse.name, Warehouse.code, Branch.name, Company.name],
        sort_fields={
            "name": Warehouse.name,
            "code": Warehouse.code,
            "status": Warehouse.status,
            "branch": Branch.name,
            "company": Company.name,
            "is_group": Warehouse.is_group,
            "id": Warehouse.id,
        },
        filter_fields={
            "company_id": Warehouse.company_id,
            "status": Warehouse.status,
            "code": Warehouse.code,
            "branch_id": Warehouse.branch_id,
            "is_group": Warehouse.is_group,
            "parent_warehouse_id": Warehouse.parent_warehouse_id,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="BRANCH",
    ),
    "bins": ListConfig(
        permission_tag="Bin",
        query_builder=build_bins_query,
        search_fields=[Bin.code, Warehouse.name, Item.name, Branch.name, Company.name],
        sort_fields={
            "code": Bin.code,
            "warehouse_name": Warehouse.name,
            "item_name": Item.name,
            "actual_qty": Bin.actual_qty,
            "valuation_rate": Bin.valuation_rate,
            "id": Bin.id,
        },
        filter_fields={
            "company_id": Bin.company_id,
            "warehouse_id": Bin.warehouse_id,
            "item_id": Bin.item_id,
            "code": Bin.code,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="BRANCH",
    ),
    "stock_reconciliations": ListConfig(
        permission_tag="Stock Reconciliation",
        query_builder=build_stock_reconciliations_query,
        search_fields=[
            StockReconciliation.code,
            Branch.name,
            User.username,  # Only use username since User model has no email
            StockReconciliation.purpose
        ],
        sort_fields={
            "posting_date": StockReconciliation.posting_date,
            "created_at": StockReconciliation.created_at,
            "code": StockReconciliation.code,
            "status": StockReconciliation.doc_status,
            "location": Branch.name,
            "created_by": User.username,  # Only use username
            "purpose": StockReconciliation.purpose,
            "id": StockReconciliation.id,
        },
        filter_fields={
            "company_id": StockReconciliation.company_id,
            "branch_id": StockReconciliation.branch_id,
            "status": StockReconciliation.doc_status,
            "purpose": StockReconciliation.purpose,
            "posting_date": StockReconciliation.posting_date,
            "created_by_id": StockReconciliation.created_by_id,
        },
        cache_enabled=False,

    ),
}

def register_stock_lists() -> None:
    register_list_configs("stock", STOCK_LIST_CONFIGS)