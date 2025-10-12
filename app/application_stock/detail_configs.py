# app/application_stock/detail_configs.py
from __future__ import annotations
from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_stock.query_builders.bin_detail_builders import load_bin_detail, resolve_bin_id_strict, \
    resolve_bin_by_code
from app.application_stock.query_builders.warehouse_detail_builders import (
    resolve_id_strict, resolve_warehouse_by_code, resolve_warehouse_by_name, load_warehouse_detail
)

STOCK_DETAIL_CONFIGS = {
    "warehouses": DetailConfig(
        permission_tag="Warehouse",
        loader=load_warehouse_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_warehouse_by_code,
            "name": resolve_warehouse_by_name,  # Support lookup by URL-encoded name
        },
        cache_enabled=True,
        cache_ttl=900,  # Warehouse details change infrequently
        default_by="code",
    ),

    "bins": DetailConfig(
        permission_tag="Bin",
        loader=load_bin_detail,
        resolver_map={
            "id": resolve_bin_id_strict,
            "code": resolve_bin_by_code,
        },
        cache_enabled=True,
        cache_ttl=600,
        default_by="code",  # you asked: “detail make code please”
    ),
}

def register_stock_detail_configs() -> None:
    register_detail_configs("stock", STOCK_DETAIL_CONFIGS)  # Changed from "inventory" to "stock"