# app/application_stock/list_configs.py
from __future__ import annotations
from sqlalchemy import func

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_stock.query_builders.build_bins_query import build_bins_query
from app.application_stock.stock_models import Warehouse, Bin
from app.application_org.models.company import Branch, Company
from app.application_stock.query_builders.build_warehouses_query import build_warehouses_query  # Fixed import path

from app.application_nventory.inventory_models import Item
STOCK_LIST_CONFIGS = {
    "warehouses": ListConfig(
        permission_tag="Warehouse",
        query_builder=build_warehouses_query,
        # Search across name, code, branch name, company name
        search_fields=[Warehouse.name, Warehouse.code, Branch.name, Company.name],
        # Sortable columns
        sort_fields={
            "name": Warehouse.name,
            "code": Warehouse.code,
            "status": Warehouse.status,
            "branch": Branch.name,
            "company": Company.name,
            "is_group": Warehouse.is_group,
            "id": Warehouse.id,
        },
        # Filterable columns
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
        cache_scope="COMPANY",
    ),
    "bins": ListConfig(
        permission_tag="Bin",
        query_builder=build_bins_query,
        # Searching by code, warehouse name, item name, branch, company
        search_fields=[Bin.code, Warehouse.name, Item.name, Branch.name, Company.name],
        # Sorting support
        sort_fields={
            "code": Bin.code,
            "warehouse_name": Warehouse.name,
            "item_name": Item.name,
            "actual_qty": Bin.actual_qty,
            "valuation_rate": Bin.valuation_rate,
            "id": Bin.id,
        },
        # Filters you’ll commonly want
        filter_fields={
            "company_id": Bin.company_id,
            "warehouse_id": Bin.warehouse_id,
            "item_id": Bin.item_id,
            "code": Bin.code,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
}

def register_module_lists() -> None:
    register_list_configs("stock", STOCK_LIST_CONFIGS)