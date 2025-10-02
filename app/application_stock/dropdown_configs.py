# app/application_stock/dropdown_configs.py
from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_stock.stock_models import Warehouse
from app.application_stock.dropdowns_builders.warehouses_dropdown import (
    build_warehouse_groups_dropdown,
    build_physical_warehouses_dropdown,
    build_all_warehouses_dropdown,
    build_child_warehouses_dropdown
)

# Stock module dropdown registrations
STOCK_DROPDOWN_CONFIGS = {
    "warehouse_groups": DropdownConfig(
        permission_tag="Warehouse",
        query_builder=build_warehouse_groups_dropdown,
        search_fields=[Warehouse.name, Warehouse.code],
        filter_fields={"status": Warehouse.status},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "physical_warehouses": DropdownConfig(
        permission_tag="Warehouse",
        query_builder=build_physical_warehouses_dropdown,
        search_fields=[Warehouse.name, Warehouse.code],
        filter_fields={"status": Warehouse.status},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "all_warehouses": DropdownConfig(
        permission_tag="Warehouse",
        query_builder=build_all_warehouses_dropdown,
        search_fields=[Warehouse.name, Warehouse.code],
        filter_fields={"status": Warehouse.status, "is_group": Warehouse.is_group},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "child_warehouses": DropdownConfig(
        permission_tag="Warehouse",
        query_builder=build_child_warehouses_dropdown,
        search_fields=[Warehouse.name, Warehouse.code],
        filter_fields={"parent_warehouse_id": Warehouse.parent_warehouse_id},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        # No window_when_empty; it's dependent on parent_warehouse_id
    ),
}

def register_stock_dropdowns() -> None:
    register_dropdown_configs("stock", STOCK_DROPDOWN_CONFIGS)