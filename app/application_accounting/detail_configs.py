from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_accounting.query_builders.detail_builders import (
    # resolvers
    resolve_mop_by_name,
    resolve_fiscal_year_by_name,
    resolve_cost_center_by_name,
    resolve_account_by_name,
    # loaders
    load_mode_of_payment,
    load_fiscal_year,
    load_cost_center,
    load_account,
)

ACCOUNTING_DETAIL_CONFIGS = {
    "modes_of_payment": DetailConfig(
        permission_tag="Mode of Payment",
        loader=load_mode_of_payment,
        resolver_map={"name": resolve_mop_by_name},
        cache_enabled=True,
        cache_ttl=3600,
    ),
    "fiscal_years": DetailConfig(
        permission_tag="Fiscal Year",
        loader=load_fiscal_year,
        resolver_map={"name": resolve_fiscal_year_by_name},
        cache_enabled=True,
        cache_ttl=86400,
    ),
    "cost_centers": DetailConfig(
        permission_tag="Cost Center",
        loader=load_cost_center,
        resolver_map={"name": resolve_cost_center_by_name},
        cache_enabled=True,
        cache_ttl=1800,
    ),
    "accounts": DetailConfig(
        permission_tag="Account",
        loader=load_account,
        resolver_map={"name": resolve_account_by_name},
        cache_enabled=True,
        cache_ttl=7200,
    ),
}

def register_accounting_detail_configs() -> None:
    register_detail_configs("accounting", ACCOUNTING_DETAIL_CONFIGS)
