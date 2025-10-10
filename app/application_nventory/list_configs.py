# app/application_inventory/list_configs
from __future__ import annotations

from sqlalchemy import select
from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item
)
from app.application_nventory.query_builders.build_inventory_queries import (
    build_brands_query,
    build_uoms_query,
    build_items_query,
    build_uom_conversions_query,

)

# Company-scoped lists: cache at company level
# Branch pricing: cache at branch level
INVENTORY_LIST_CONFIGS = {
    "brands": ListConfig(
        permission_tag="Brand",
        query_builder=build_brands_query,
        search_fields=[Brand.name],
        sort_fields={"name": Brand.name, "id": Brand.id},
        filter_fields={"company_id": Brand.company_id},  # optional filter passthrough
        cache_enabled=True, cache_ttl=3600, cache_scope="COMPANY",
    ),
    "uoms": ListConfig(
        permission_tag="UnitOfMeasure",
        query_builder=build_uoms_query,
        search_fields=[UnitOfMeasure.name, UnitOfMeasure.symbol],
        sort_fields={"name": UnitOfMeasure.name, "symbol": UnitOfMeasure.symbol, "id": UnitOfMeasure.id},
        filter_fields={"company_id": UnitOfMeasure.company_id},
        cache_enabled=True, cache_ttl=3600, cache_scope="COMPANY",
    ),
    "items": ListConfig(
        permission_tag="Item",
        query_builder=build_items_query,
        search_fields=[Item.name, Item.sku],
        sort_fields={"name": Item.name, "sku": Item.sku, "id": Item.id},
        filter_fields={"company_id": Item.company_id, "item_type": Item.item_type, "status": Item.status},
        cache_enabled=True, cache_ttl=900, cache_scope="COMPANY",
    ),


}

# Register into the global registry so your ListRepository can resolve it
register_list_configs("inventory", INVENTORY_LIST_CONFIGS)
