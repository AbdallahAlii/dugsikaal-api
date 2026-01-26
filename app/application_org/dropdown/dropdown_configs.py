from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope
from app.application_org.dropdown.dropdown_builders import build_companies_dropdown, build_branches_dropdown, \
    build_departments_dropdown

from app.application_org.models.company import Company, Branch, Department
from app.application_org.query_builders.dropdown_builders_platform import build_companies_platform_dropdown, \
    build_platform_branches_dropdown, build_company_branches_dependent_dropdown

# Dropdown configurations for the geo module (Companies, Branches, Departments)
ORG_DROPDOWN_CONFIGS = {
    "companies": DropdownConfig(
        permission_tag="Company",
        query_builder=build_companies_dropdown,
        search_fields=[Company.name],
        filter_fields={"status": Company.status},
        cache_enabled=True,
        cache_ttl=3600,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
    ),
    "branches": DropdownConfig(
        permission_tag="Branch",
        query_builder=build_branches_dropdown,
        search_fields=[Branch.name],
        filter_fields={"company_id": Branch.company_id},
        cache_enabled=True,
        cache_ttl=3600,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
    ),
    "departments": DropdownConfig(
        permission_tag="Department",
        query_builder=build_departments_dropdown,
        search_fields=[Department.name],
        filter_fields={"is_system_defined": Department.is_system_defined, "company_id": Department.company_id},
        cache_enabled=True,
        cache_ttl=3600,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
    ),
    "companies_platform": DropdownConfig(
        permission_tag="Company",  # RBAC + _has_platform_admin_scope guard
        query_builder=build_companies_platform_dropdown,
        search_fields=[Company.name, Company.prefix],
        filter_fields={
            "status": Company.status,
            "city_id": Company.city_id,
        },
        cache_enabled=True,
        cache_ttl=900,  # 15 minutes
        cache_scope=CacheScope.GLOBAL,
        default_limit=50,
        max_limit=200,
        window_when_empty=200,
    ),
    "branches_platform": DropdownConfig(
        permission_tag="Branch",
        query_builder=build_platform_branches_dropdown,
        search_fields=[Branch.name, Branch.code],
        filter_fields={
            "company_id": Branch.company_id,
            "status": Branch.status,
            "is_hq": Branch.is_hq,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.GLOBAL,
        default_limit=50,
        max_limit=200,
        window_when_empty=200,
    ),
    # 🔹 NEW: Dependent branches for a given company
    "company_branches": DropdownConfig(
        permission_tag="Branch",
        query_builder=build_company_branches_dependent_dropdown,
        search_fields=[Branch.name, Branch.code],
        filter_fields={
            "company_id": Branch.company_id,  # enforce dependency
            "status": Branch.status,
            "is_hq": Branch.is_hq,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=0,  # do NOT query until company_id is provided
    ),

}

def register_org_dropdowns() -> None:
    register_dropdown_configs("org", ORG_DROPDOWN_CONFIGS)
