from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_nventory.inventory_models import Item, UnitOfMeasure, Brand, UOMConversion
from app.application_nventory.query_builders.dropdown_builders import (
    build_items_dropdown, build_uoms_dropdown, build_brands_dropdown,
    build_item_uoms_dropdown,
    build_active_items_dropdown, build_active_uoms_dropdown, build_active_brands_dropdown,
    build_item_group_parents_dropdown, build_item_group_leaves_dropdown, build_item_groups_dropdown
)

# inventory module registrations
INVENTORY_DROPDOWN_CONFIGS = {
    # Main dropdowns - for general use
    "items": DropdownConfig(
        permission_tag="Item",
        query_builder=build_items_dropdown,
        search_fields=[Item.name, Item.sku],
        filter_fields={"item_type": Item.item_type, "status": Item.status},
        cache_enabled=True, cache_ttl=1800, cache_scope=CacheScope.COMPANY,
        default_limit=20, max_limit=100, window_when_empty=200,
    ),
    "uoms": DropdownConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        filter_fields={"status": UnitOfMeasure.status},
        cache_enabled=True, cache_ttl=3600, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200,
    ),
    "brands": DropdownConfig(
        permission_tag="Brand",
        query_builder=build_brands_dropdown,
        search_fields=[Brand.name],
        filter_fields={"status": Brand.status},
        cache_enabled=True, cache_ttl=3600, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200,
    ),

    # Active-only dropdowns - for forms and transactions
    "active_items": DropdownConfig(
        permission_tag="Item",
        query_builder=build_active_items_dropdown,
        search_fields=[Item.name, Item.sku],
        filter_fields={"item_type": Item.item_type},
        cache_enabled=True, cache_ttl=900, cache_scope=CacheScope.COMPANY,  # Shorter TTL for active items
        default_limit=25, max_limit=100, window_when_empty=100,
    ),
    "active_uoms": DropdownConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_active_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        cache_enabled=True, cache_ttl=1800, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200,
    ),
    "active_brands": DropdownConfig(
        permission_tag="Brand",
        query_builder=build_active_brands_dropdown,
        search_fields=[Brand.name],
        cache_enabled=True, cache_ttl=1800, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200,
    ),

    # Specialized dropdowns

    "item_uoms": DropdownConfig(
        permission_tag="PUBLIC",  # reuse UOM read permission
        query_builder=build_item_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        filter_fields={"item_id": UnitOfMeasure.id},
        cache_enabled=True,
        cache_ttl=900,  # Shorter TTL for dependent dropdowns
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
    ),

 "item_groups": DropdownConfig(
        permission_tag="ItemGroup",
        query_builder=build_item_groups_dropdown,
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
    # Folders only (for Parent picker)
    "item_group_parents": DropdownConfig(
        permission_tag="ItemGroup",
        query_builder=build_item_group_parents_dropdown,
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
    # Leaves only (when you want a terminal category)
    "item_group_leaves": DropdownConfig(
        permission_tag="ItemGroup",
        query_builder=build_item_group_leaves_dropdown,
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),

}


def register_inventory_dropdowns() -> None:
    register_dropdown_configs("inventory", INVENTORY_DROPDOWN_CONFIGS)