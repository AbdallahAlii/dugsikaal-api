# app/application_inventory/dropdown_configs.py
from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_nventory.inventory_models import Item, UnitOfMeasure, Brand, BranchItemPricing
from app.application_nventory.query_builders.dropdown_builders import build_items_dropdown, build_uoms_dropdown, \
    build_branch_prices_dropdown, build_item_uoms_dropdown

# inventory module registrations (example)
INVENTORY_DROPDOWN_CONFIGS = {
    "items": DropdownConfig(
        permission_tag="Item",
        query_builder=build_items_dropdown,
        search_fields=[Item.name, Item.sku],
        filter_fields={"item_type": Item.item_type, "status": Item.status},
        cache_enabled=True, cache_ttl=1800, cache_scope=CacheScope.COMPANY,
        default_limit=20, max_limit=100, window_when_empty=200,   # 👈 nice UX
    ),
    "uoms": DropdownConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        cache_enabled=True, cache_ttl=3600, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200,
    ),
    "branch_item_prices": DropdownConfig(
        permission_tag="BranchItemPricing",
        query_builder=build_branch_prices_dropdown,
        cache_enabled=False,            # volatile → no cache
        cache_scope=CacheScope.BRANCH,
        default_limit=20, max_limit=100,
    ),
    "item_uoms": DropdownConfig(
        permission_tag="PUBLIC",  # reuse UOM read permission
        query_builder=build_item_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        filter_fields={"item_id": UnitOfMeasure.id},  # allow-listed for safety; not actually used in apply_filters
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,  # company-scoped (items/UOMs are company-scoped)
        default_limit=50,
        max_limit=200,
        # no window_when_empty; it’s dependent – empty without item_id anyway
    ),
}


def register_inventory_dropdowns() -> None:
    register_dropdown_configs("inventory", INVENTORY_DROPDOWN_CONFIGS)

