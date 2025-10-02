from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_nventory.inventory_models import Item, UnitOfMeasure, Brand, BranchItemPricing, UOMConversion
from app.application_nventory.query_builders.dropdown_builders import (
    build_items_dropdown, build_uoms_dropdown, build_brands_dropdown,
    build_branch_prices_dropdown, build_item_uoms_dropdown,
    build_active_items_dropdown, build_active_uoms_dropdown, build_active_brands_dropdown
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
    "branch_item_prices": DropdownConfig(
        permission_tag="BranchItemPricing",
        query_builder=build_branch_prices_dropdown,
        cache_enabled=False,  # volatile → no cache
        cache_scope=CacheScope.BRANCH,
        default_limit=20, max_limit=100,
    ),
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
}


def register_inventory_dropdowns() -> None:
    register_dropdown_configs("inventory", INVENTORY_DROPDOWN_CONFIGS)