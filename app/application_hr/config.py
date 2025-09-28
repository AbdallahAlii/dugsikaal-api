
# app/application_hr/config.py

from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig
from app.application_hr.models.hr import Employee
# Corrected import path
from app.application_hr.query_builders.build_employees_query import build_employees_query
from app.application_org.models.company import Company, Branch

HR_LIST_CONFIGS = {
    "employees": ListConfig(
        permission_tag="Employee",
        query_builder=build_employees_query,
        search_fields=[Employee.full_name, Employee.code, Company.name, Branch.name],
        sort_fields={
            "full_name": Employee.full_name,
            "code": Employee.code,
            "company_name": Company.name,
            "branch_name": Branch.name,
            "date_of_joining": Employee.date_of_joining,
        },
        # cache_enabled=False,  # This list will NEVER be cached.
        filter_fields={
            "company_id": Company.id,
            "branch_id": Branch.id,
            "status": Employee.status,
        },
    ),
}