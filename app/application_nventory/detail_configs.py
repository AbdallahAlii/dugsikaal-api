# app/application_inventory/detail_configs.py
from __future__ import annotations

from app.application_nventory.inventory_models import Brand, UnitOfMeasure, Item
from .query_builders.detail_builders import (
    resolve_brand_by_name, load_brand,
    resolve_uom_by_name, load_uom,
    resolve_item_by_sku, resolve_item_by_name, load_item,
    load_uom_conversion, resolve_id_strict,
)
from ..application_doctypes.core_lists.config import DetailConfig, register_detail_configs

INVENTORY_DETAIL_CONFIGS = {
    "brands": DetailConfig(
        permission_tag="Brand",
        loader=load_brand,
        resolver_map={"id": resolve_id_strict, "name": resolve_brand_by_name},
        cache_enabled=False,  # default OFF
        default_by="name",
    ),
    "uoms": DetailConfig(
        permission_tag="UnitOfMeasure",
        loader=load_uom,
        resolver_map={"id": resolve_id_strict, "name": resolve_uom_by_name},
        cache_enabled=False,
        default_by="name",
    ),
    "items": DetailConfig(
        permission_tag="Item",
        loader=load_item,
        resolver_map={
            "id":   resolve_id_strict,
            "code": resolve_item_by_sku,
            "sku":  resolve_item_by_sku,   # alias
            "name": resolve_item_by_name
        },
        cache_enabled=False,  # turn ON only if you add bumps on all dependent writes
        cache_ttl=900,
        default_by="name",
    ),
    "uom_conversions": DetailConfig(
        permission_tag="UOMConversion",
        loader=load_uom_conversion,
        resolver_map={"id": resolve_id_strict},
        cache_enabled=False,
    ),

}

def register_inventory_detail_configs() -> None:
    register_detail_configs("inventory", INVENTORY_DETAIL_CONFIGS)

