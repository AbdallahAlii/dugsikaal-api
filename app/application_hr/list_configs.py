from __future__ import annotations
from sqlalchemy import func

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_org.models.company import Branch, Department
from app.application_hr.query_builders.build_employees_query import build_employees_query

HR_LIST_CONFIGS = {
    "employees": ListConfig(
        permission_tag="Employee",
        query_builder=build_employees_query,
        # Search across name, code, branch
        search_fields=[Employee.full_name, Employee.code, Branch.name],
        # Sortable columns
        sort_fields={
            "full_name":  Employee.full_name,
            "code":       Employee.code,
            "status":     Employee.status,
            "branch":     Branch.name,  # via join expr in query builder
            "id":         Employee.id,
        },
        # Filterable columns
        filter_fields={
            "company_id": Employee.company_id,
            "status":     Employee.status,
            "code":       Employee.code,
            "branch_id":  EmployeeAssignment.branch_id,   # current primary assignment
            "dept_id":    EmployeeAssignment.department_id,
        },
        cache_enabled=True, cache_ttl=600, cache_scope="COMPANY",
    ),
}

def register_module_lists() -> None:
    register_list_configs("hr", HR_LIST_CONFIGS)
