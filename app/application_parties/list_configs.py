from __future__ import annotations

from sqlalchemy import func

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_org.models.company import City
from app.application_parties.parties_models import Party

from app.application_parties.query_builders.build_parties_query import (
    build_customers_query,
    build_suppliers_query,
)



PARTIES_LIST_CONFIGS = {
    "customers": ListConfig(
        permission_tag="Party",                 # reuse a general tag or make "Customer" if you split perms
        query_builder=build_customers_query,
        search_fields=[
            Party.code,
            Party.name,
            City.name,                          # search by territory (city)
        ],
        sort_fields={
            "code":           Party.code,
            "name":           Party.name,
            "status":         Party.status,
            "territory_name": City.name,
            "id":             Party.id,
        },
        filter_fields={
            "company_id":     Party.company_id,    # explicit company filter passthrough
            "branch_id":      Party.branch_id,     # filter to a branch (rarely needed)
            "status":         Party.status,
            "code":           Party.code,
            "name":           Party.name,
            "city_id":        Party.city_id,
        },
        cache_enabled=False, cache_ttl=600, cache_scope="COMPANY",
    ),
    "suppliers": ListConfig(
        permission_tag="Party",
        query_builder=build_suppliers_query,
        search_fields=[
            Party.code,
            Party.name,
            City.name,
        ],
        sort_fields={
            "code":           Party.code,
            "name":           Party.name,
            "status":         Party.status,
            "territory_name": City.name,
            "id":             Party.id,
        },
        filter_fields={
            "company_id":     Party.company_id,
            "branch_id":      Party.branch_id,
            "status":         Party.status,
            "code":           Party.code,
            "name":           Party.name,
            "city_id":        Party.city_id,
        },
        cache_enabled=True, cache_ttl=600, cache_scope="COMPANY",
    ),
}

# Expose a register function (same pattern as RBAC)
def register_module_lists() -> None:
    register_list_configs("parties", PARTIES_LIST_CONFIGS)
