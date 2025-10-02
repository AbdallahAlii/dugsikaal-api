# app/application_parties/dropdown_configs.py
from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_parties.parties_models import Party
from app.application_parties.dropdown_builders import (
    build_suppliers_dropdown,
    build_customers_dropdown,
    build_all_parties_dropdown,
    build_cash_parties_dropdown
)

# Parties module dropdown registrations
PARTIES_DROPDOWN_CONFIGS = {
    "suppliers": DropdownConfig(
        permission_tag="Party",
        query_builder=build_suppliers_dropdown,
        search_fields=[Party.name, Party.code, Party.email, Party.phone],
        filter_fields={"status": Party.status, "nature": Party.nature},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "customers": DropdownConfig(
        permission_tag="Party",
        query_builder=build_customers_dropdown,
        search_fields=[Party.name, Party.code, Party.email, Party.phone],
        filter_fields={"status": Party.status, "nature": Party.nature},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "all_parties": DropdownConfig(
        permission_tag="Party",
        query_builder=build_all_parties_dropdown,
        search_fields=[Party.name, Party.code, Party.email, Party.phone],
        filter_fields={"status": Party.status, "nature": Party.nature, "role": Party.role},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "cash_parties": DropdownConfig(
        permission_tag="Party",
        query_builder=build_cash_parties_dropdown,
        search_fields=[Party.name, Party.code],
        filter_fields={"status": Party.status, "role": Party.role},
        cache_enabled=True,
        cache_ttl=1800,
        cache_scope=CacheScope.COMPANY,
        default_limit=20,
        max_limit=100,
        window_when_empty=50,
    ),
}

def register_parties_dropdowns() -> None:
    register_dropdown_configs("parties", PARTIES_DROPDOWN_CONFIGS)