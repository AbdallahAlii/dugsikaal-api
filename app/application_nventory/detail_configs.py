from __future__ import annotations

from .query_builders.detail_builders import (
    resolve_brand_by_name, load_brand,
    resolve_uom_by_name, load_uom,
    resolve_item_by_sku, resolve_item_by_name, load_item_detail,
    resolve_item_group_by_name, load_item_group,
    resolve_price_list_by_name, load_price_list,
    resolve_item_price_by_code, load_item_price,
    load_uom_conversion, resolve_id_strict,
)
from ..application_doctypes.core_lists.config import DetailConfig, register_detail_configs

INVENTORY_DETAIL_CONFIGS = {
    "brands": DetailConfig(
        permission_tag="Brand",
        loader=load_brand,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_brand_by_name
        },
        cache_enabled=False,
        default_by="name",
    ),
    "uoms": DetailConfig(
        permission_tag="UnitOfMeasure",
        loader=load_uom,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_uom_by_name
        },
        cache_enabled=False,
        default_by="name",
    ),
    "items": DetailConfig(
        permission_tag="Item",
        loader=load_item_detail,
        resolver_map={
            "id": resolve_id_strict,
            "sku": resolve_item_by_sku,
            "name": resolve_item_by_name,
        },
        cache_enabled=True,
        cache_ttl=900,
        default_by="name",
    ),
    "item_groups": DetailConfig(
        permission_tag="ItemGroup",
        loader=load_item_group,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_item_group_by_name,
        },
        cache_enabled=True,
        cache_ttl=1800,
        default_by="name",
    ),
    "price_lists": DetailConfig(
        permission_tag="PriceList",
        loader=load_price_list,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_price_list_by_name,
        },
        cache_enabled=True,
        cache_ttl=1800,
        default_by="name",
    ),
    "item_prices": DetailConfig(
        permission_tag="ItemPrice",
        loader=load_item_price,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_item_price_by_code,
        },
        cache_enabled=True,
        cache_ttl=300,
        default_by="id",
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