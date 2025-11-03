from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope
from app.application_nventory.inventory_models import Item, UnitOfMeasure
from app.application_selling.query_builders.dropdown_builders import build_item_sales_uoms_dropdown

SELLING_DROPDOWN_CONFIGS = {
    # Dependent UOMs for a chosen item (base + active conversions)
    "item_sales_uoms": DropdownConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_item_sales_uoms_dropdown,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        filter_fields={"item_id": Item.id},   # enforce dependency
        cache_enabled=True,
        cache_ttl=900,                        # short TTL; conversions can change
        cache_scope=CacheScope.COMPANY,
        default_limit=20,
        max_limit=50,
        window_when_empty=0,                  # don’t query until item_id is set
    ),
}

def register_selling_dropdowns() -> None:
    register_dropdown_configs("selling", SELLING_DROPDOWN_CONFIGS)
