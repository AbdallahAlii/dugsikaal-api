from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, ItemGroup, PriceList, ItemPrice, UOMConversion
)
from app.application_nventory.query_builders.build_inventory_queries import (
    build_brands_query,
    build_uoms_query,
    build_items_query,
    build_item_groups_query,
    build_price_lists_query,
    build_item_prices_query,
    build_uom_conversions_query,
)

# Company-scoped lists with pagination support
INVENTORY_LIST_CONFIGS = {
    "brands": ListConfig(
        permission_tag="Brand",
        query_builder=build_brands_query,
        search_fields=[Brand.name],
        sort_fields={
            "name": Brand.name,
            "id": Brand.id,
            "created_at": Brand.created_at
        },
        filter_fields={
            "company_id": Brand.company_id,
            "status": Brand.status
        },
        cache_enabled=True,
        cache_ttl=3600,
        cache_scope="COMPANY",
    ),
    "uoms": ListConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_uoms_query,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        sort_fields={
            "name": UnitOfMeasure.name,
            "symbol": UnitOfMeasure.symbol,
            "id": UnitOfMeasure.id,
            "created_at": UnitOfMeasure.created_at
        },
        filter_fields={
            "company_id": UnitOfMeasure.company_id,
            "status": UnitOfMeasure.status
        },
        cache_enabled=True,
        cache_ttl=3600,
        cache_scope="COMPANY",
    ),
    "items": ListConfig(
        permission_tag="Item",
        query_builder=build_items_query,
        search_fields=[Item.name, Item.sku],
        sort_fields={
            "name": Item.name,
            "sku": Item.sku,
            "id": Item.id,
            "created_at": Item.created_at
        },
        filter_fields={
            "company_id": Item.company_id,
            "item_type": Item.item_type,
            "status": Item.status,
            "is_fixed_asset": Item.is_fixed_asset
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope="COMPANY",
    ),
    "item_groups": ListConfig(
        permission_tag="ItemGroup",
        query_builder=build_item_groups_query,
        search_fields=[ItemGroup.name],
        sort_fields={
            "name": ItemGroup.name,
            "id": ItemGroup.id,
            "created_at": ItemGroup.created_at
        },
        filter_fields={
            "company_id": ItemGroup.company_id,
            "is_group": ItemGroup.is_group
        },
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope="COMPANY",
        # Note: Only returns id, name, parent_name, is_group per user request
    ),
    "price_lists": ListConfig(
        permission_tag="PriceList",
        query_builder=build_price_lists_query,
        search_fields=[PriceList.name],
        sort_fields={
            "name": PriceList.name,
            "list_type": PriceList.list_type,
            "id": PriceList.id,
            "created_at": PriceList.created_at
        },
        filter_fields={
            "company_id": PriceList.company_id,
            "list_type": PriceList.list_type,
            "is_active": PriceList.is_active,
            "is_default": PriceList.is_default
        },
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope="COMPANY",
        # Note: Only returns id, name, list_type, is_active per user request
    ),
    "item_prices": ListConfig(
        permission_tag="ItemPrice",
        query_builder=build_item_prices_query,
        search_fields=["Item.name", "PriceList.name", "ItemPrice.code"],
        sort_fields={
            "item_name": "item_name",
            "price_list_name": "price_list_name",
            "code": "code",
            "id": ItemPrice.id,
            "created_at": ItemPrice.created_at
        },
        filter_fields={
            "company_id": ItemPrice.company_id,
            "price_list_id": ItemPrice.price_list_id,
            "item_id": ItemPrice.item_id
        },
        cache_enabled=True,
        cache_ttl=300,
        cache_scope="COMPANY",
        # Note: Only returns id, code, item_name, price_list_name per user request
    ),
    "uom_conversions": ListConfig(
        permission_tag="UOMConversion",
        query_builder=build_uom_conversions_query,
        search_fields=[],
        sort_fields={
            "id": UOMConversion.id,
            "created_at": UOMConversion.created_at
        },
        filter_fields={

            "item_id": UOMConversion.item_id,
            "is_active": UOMConversion.is_active
        },
        cache_enabled=False,
        cache_scope="COMPANY",
    ),
}

# Register into the global registry
def register_inventory_list_configs() -> None:
    register_list_configs("inventory", INVENTORY_LIST_CONFIGS)