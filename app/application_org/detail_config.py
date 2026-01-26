# app/application_org/detail_config.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_org.query_builders.org_detail_builders import (
    # resolvers
    resolve_company_by_name,
    resolve_branch_by_name,
    # loaders
    load_company_detail,
    load_branch_detail,
)
from app.application_org.query_builders.org_subscription_detail_builders import (
    load_company_package_subscription_detail,

)

ORG_DETAIL_CONFIGS = {
    "companies": DetailConfig(
        permission_tag="Company",
        loader=load_company_detail,
        # optional resolver: /api/details/org/companies?name=Haji%20Technologies
        resolver_map={"name": resolve_company_by_name},
        cache_enabled=False,
    ),
    "branches": DetailConfig(
        permission_tag="Branch",
        loader=load_branch_detail,
        # optional resolver: /api/details/org/branches?name=HQ
        resolver_map={"name": resolve_branch_by_name},
        cache_enabled=False,
    ),
"company_package_subscriptions": DetailConfig(
    permission_tag="Company",
    loader=load_company_package_subscription_detail,
    identifier_field="id",   # ✅ required by your DetailConfig
    cache_enabled=False,
),



}


def register_org_detail_configs() -> None:
    register_detail_configs("org", ORG_DETAIL_CONFIGS)
