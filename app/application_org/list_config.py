# app/application_org/list_config.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_org.models.company import Company, Branch, City
from app.application_org.query_builders.org_list_builders import (
    build_companies_list_query,
    build_branches_list_query,
)
from app.application_org.query_builders.org_subscription_list_builders import (
     build_company_packages_matrix_list_query,
)
from app.navigation_workspace.models.subscription import CompanyPackageSubscription, ModulePackage

ORG_LIST_CONFIGS = {
    "companies": ListConfig(
        permission_tag="Company",  # permission tag in your RBAC
        query_builder=build_companies_list_query,
        search_fields=[Company.name, City.name],
        sort_fields={
            "name": Company.name,
            "id": Company.id,
            "status": Company.status,
            "timezone": Company.timezone,
        },
        filter_fields={
            "status": Company.status,
            "city_id": Company.city_id,
        },
        cache_enabled=False,
    ),
    "branches": ListConfig(
        permission_tag="Branch",
        query_builder=build_branches_list_query,
        search_fields=[Branch.name, Company.name],
        sort_fields={
            "name": Branch.name,
            "id": Branch.id,
            "status": Branch.status,
            "is_hq": Branch.is_hq,
        },
        filter_fields={
            "company_id": Branch.company_id,
            "status": Branch.status,
            "is_hq": Branch.is_hq,

        },
        cache_enabled=False,
    ),
    "company_packages_matrix": ListConfig(
        permission_tag="Company",   # System Admin gate is inside query_builder anyway
        query_builder=build_company_packages_matrix_list_query,
        search_fields=[Company.name],
        sort_fields={
            "company_name": Company.name,
            "company_id": Company.id,
            "company_status": Company.status,
        },
        filter_fields={
            "status": Company.status,
        },
        cache_enabled=False,
    ),


}


def register_module_lists() -> None:
    register_list_configs("org", ORG_LIST_CONFIGS)
