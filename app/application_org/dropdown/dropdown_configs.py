from __future__ import annotations
from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope
from app.application_org.dropdown.dropdown_builders import build_companies_dropdown, build_branches_dropdown, \
    build_departments_dropdown

from app.application_org.models.company import Company, Branch, Department

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
}

def register_org_dropdowns() -> None:
    register_dropdown_configs("org", ORG_DROPDOWN_CONFIGS)
