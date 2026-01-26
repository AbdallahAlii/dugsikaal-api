# app/application_hr/hr_detail_configs.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_hr.query_builders.employee_detail_builders import (
    resolve_id_strict,
    resolve_employee_by_code,
    load_employee_detail,
    resolve_holiday_list_by_name,
    load_holiday_list_detail,
    resolve_shift_type_by_name,
    load_shift_type_detail,
    resolve_payroll_period_by_name,
    load_payroll_period_detail,
)

# NOTE: permission_tag values MUST match seed_data/rbac/data.py
#   - "Employee"
#   - "Holiday List"
#   - "Shift Type"
#   - "Payroll Period"


HR_DETAIL_CONFIGS = {
    # ---------------------------------
    # Employee
    # ---------------------------------
    "employees": DetailConfig(
        permission_tag="Employee",
        loader=load_employee_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_employee_by_code,
        },
        cache_enabled=False,   # employee details can change; always fresh
        cache_ttl=900,
        default_by="code",
    ),

    # ---------------------------------
    # Holiday List
    # ---------------------------------
    "holiday_lists": DetailConfig(
        permission_tag="Holiday List",
        loader=load_holiday_list_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_holiday_list_by_name,
        },
        cache_enabled=False,
        cache_ttl=900,
        default_by="name",
    ),

    # ---------------------------------
    # Shift Type
    # ---------------------------------
    "shift_types": DetailConfig(
        permission_tag="Shift Type",
        loader=load_shift_type_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_shift_type_by_name,
        },
        cache_enabled=False,
        cache_ttl=900,
        default_by="name",
    ),

    # ---------------------------------
    # Payroll Period
    # ---------------------------------
    "payroll_periods": DetailConfig(
        permission_tag="Payroll Period",
        loader=load_payroll_period_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_payroll_period_by_name,
        },
        cache_enabled=False,
        cache_ttl=900,
        default_by="name",
    ),
}


def register_hr_detail_configs() -> None:
    register_detail_configs("hr", HR_DETAIL_CONFIGS)
