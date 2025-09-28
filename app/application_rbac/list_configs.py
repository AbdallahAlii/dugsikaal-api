
# app/application_rbac/list_configs.py
from __future__ import annotations

from sqlalchemy import func

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs

# Models for field expressions
from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_org.models.company import Branch
from app.auth.models.users import User, UserType, UserAffiliation
from app.application_rbac.rbac_models import Role

# Query builders
from app.application_rbac.query_builders.build_users_query import build_users_query
from app.application_rbac.query_builders.build_roles_query import build_roles_query


# Company-scoped RBAC lists
RBAC_LIST_CONFIGS = {
    # =========================
    # Users list (existing)
    # =========================
    "users": ListConfig(
        permission_tag="User",                     # reuse your RBAC permission tag
        query_builder=build_users_query,
        # Searchable columns
        search_fields=[
            User.username,
            Employee.full_name,
            Branch.name,
            UserType.name,
        ],
        # Sortable columns
        sort_fields={
            "username":   User.username,
            "full_name":  func.coalesce(Employee.full_name, User.username),
            "user_type":  UserType.name,
            "branch":     Branch.name,
            "status":     User.status,
            "last_login": User.last_login,
            "id":         User.id,
        },
        # Filterable columns (simple equality)
        filter_fields={
            "company_id":           UserAffiliation.company_id,       # explicit tenant filter passthrough
            "branch_id":            UserAffiliation.branch_id,        # by affiliation branch
            "assignment_branch_id": EmployeeAssignment.branch_id,     # by current assignment branch
            "user_type_id":         UserAffiliation.user_type_id,
            "status":               User.status,
            "username":             User.username,
        },
        cache_enabled=True, cache_ttl=600, cache_scope="COMPANY",
    ),

    # =========================
    # Roles list (new)
    # =========================
    "roles": ListConfig(
        permission_tag="Role",
        query_builder=build_roles_query,   # <- imported from query_builders/build_roles_query.py
        # Searchable
        search_fields=[Role.name],
        # Sortable
        sort_fields={
            "name":              Role.name,
            "scope":             Role.scope,
            "is_system_defined": Role.is_system_defined,

            "company_id":        Role.company_id,
            "id":                Role.id,
        },
        # Filterable
        filter_fields={
            "name":              Role.name,
            "scope":             Role.scope,            # e.g. 'GLOBAL' | 'COMPANY' ...
            "company_id":        Role.company_id,
            "is_system_defined": Role.is_system_defined,

            "id":                Role.id,
        },
        cache_enabled=True, cache_ttl=600, cache_scope="COMPANY",
    ),
}

# Register under "rbac" so the ListRepository can resolve it
register_list_configs("rbac", RBAC_LIST_CONFIGS)
