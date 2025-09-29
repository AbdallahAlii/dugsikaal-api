from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope  # you already import this elsewhere

from app.application_geo.dropdown_builders import build_cities_dropdown
from app.application_org.models.company import City

GEO_DROPDOWN_CONFIGS = {
    "cities": DropdownConfig(
        permission_tag="PUBLIC",                 # or "City" if you want to protect it
        query_builder=build_cities_dropdown,
        search_fields=[City.name, City.region],  # free-text search over these
        filter_fields={"region": City.region},   # allow exact region filtering
        cache_enabled=True,
        cache_ttl=3600,                          # 1 hour
        cache_scope=CacheScope.GLOBAL,          # ✅ switch to CacheScope.GLOBAL if your enum supports it
        default_limit=50,
        max_limit=200,
        window_when_empty=200,                   # return first 200 when no search provided (nice UX)
    ),
}

def register_geo_dropdowns() -> None:
    register_dropdown_configs("geo", GEO_DROPDOWN_CONFIGS)
