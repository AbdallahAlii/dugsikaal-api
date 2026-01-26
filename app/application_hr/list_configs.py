from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_hr.models.hr import (
    Employee,
    EmployeeAssignment,
    HolidayList,
    ShiftType,
    PayrollPeriod,
)
from app.application_org.models.company import Branch, Department
from app.application_hr.query_builders.build_employees_query import (
    build_employees_query,
    build_holiday_lists_query,
    build_shift_types_query,
    build_payroll_periods_query,
)

# ─────────────────────────────────────────
# HR List Configs (ERP-style, RBAC-aligned)
# ─────────────────────────────────────────

HR_LIST_CONFIGS = {
    # ------------------------------------------------------
    # Employee list
    # - permission_tag MUST match RBAC: "Employee"
    # ------------------------------------------------------
    "employees": ListConfig(
        permission_tag="Employee",
        query_builder=build_employees_query,
        # Search across name, code, and branch name
        search_fields=[Employee.full_name, Employee.code, Branch.name],
        # Sortable columns
        sort_fields={
            "full_name": Employee.full_name,
            "code": Employee.code,
            "status": Employee.status,
            "branch": Branch.name,  # via join expr in query builder
            "id": Employee.id,
        },
        # Filterable columns
        filter_fields={
            "company_id": Employee.company_id,
            "status": Employee.status,
            "code": Employee.code,
            # current primary assignment (EmployeeAssignment is joined in query_builder)
            "branch_id": EmployeeAssignment.branch_id,
            "dept_id": EmployeeAssignment.department_id,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),

    # ------------------------------------------------------
    # Holiday List
    # - permission_tag MUST match RBAC: "Holiday List"
    # - Columns: Name / From Date / To Date / Total Holidays
    # ------------------------------------------------------
    "holiday_lists": ListConfig(
        permission_tag="Holiday List",
        query_builder=build_holiday_lists_query,
        # Search by holiday list name
        search_fields=[HolidayList.name],
        # Sort options for list view
        sort_fields={
            "name": HolidayList.name,
            "from_date": HolidayList.from_date,
            "to_date": HolidayList.to_date,
            "id": HolidayList.id,
        },
        # Filters available in the UI
        filter_fields={
            "company_id": HolidayList.company_id,
            "is_default": HolidayList.is_default,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),

    # ------------------------------------------------------
    # Shift Type
    # - permission_tag MUST match RBAC: "Shift Type"
    # - Columns: Name / Start Time / End Time
    # ------------------------------------------------------
    "shift_types": ListConfig(
        permission_tag="Shift Type",
        query_builder=build_shift_types_query,
        # Search by shift type name
        search_fields=[ShiftType.name],
        # Sort by logical shift columns
        sort_fields={
            "name": ShiftType.name,
            "start_time": ShiftType.start_time,
            "end_time": ShiftType.end_time,
            "id": ShiftType.id,
        },
        # Filters (company + common flags)
        filter_fields={
            "company_id": ShiftType.company_id,
            "enable_auto_attendance": ShiftType.enable_auto_attendance,
            "is_night_shift": ShiftType.is_night_shift,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),

    # ------------------------------------------------------
    # Payroll Period
    # - permission_tag MUST match RBAC: "Payroll Period"
    # - Columns: Name / Start Date / End Date (+ is_closed)
    # ------------------------------------------------------
    "payroll_periods": ListConfig(
        permission_tag="Payroll Period",
        query_builder=build_payroll_periods_query,
        # Search by period name
        search_fields=[PayrollPeriod.name],
        # Sort by name and dates
        sort_fields={
            "name": PayrollPeriod.name,
            "start_date": PayrollPeriod.start_date,
            "end_date": PayrollPeriod.end_date,
            "id": PayrollPeriod.id,
        },
        # Filters: company + open/closed status
        filter_fields={
            "company_id": PayrollPeriod.company_id,
            "is_closed": PayrollPeriod.is_closed,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
}


def register_module_lists() -> None:
    """
    Register HR list configurations under the "hr" module key.
    """
    register_list_configs("hr", HR_LIST_CONFIGS)
