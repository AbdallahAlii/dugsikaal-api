from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import (
    DropdownConfig,
    register_dropdown_configs,
)
from app.application_doctypes.core_lists.config import CacheScope

from app.application_hr.models.hr import (
    Employee,
    HolidayList,
    ShiftType,
    SalaryStructure,
    PayrollPeriod,
    BiometricDevice,
)
from app.application_hr.dropdown_builders.hr_dropdowns import (
    build_employees_dropdown,
    build_holiday_lists_dropdown,
    build_shift_types_dropdown,
    build_salary_structures_dropdown,
    build_payroll_periods_dropdown,
    build_biometric_devices_dropdown,
)


HR_DROPDOWN_CONFIGS = {
    # Employees: used everywhere (assign employee, approver, etc.)
    "employees": DropdownConfig(
        permission_tag="Employee",     # your RBAC doctype name
        query_builder=build_employees_dropdown,
        search_fields=[Employee.full_name, Employee.code],
        filter_fields={
            "company_id": Employee.company_id,
            "status": Employee.status,
        },
        cache_enabled=True,
        cache_ttl=900,                # 15 minutes
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),

    # Holiday List dropdown
    "holiday_lists": DropdownConfig(
        permission_tag="HolidayList",
        query_builder=build_holiday_lists_dropdown,
        search_fields=[HolidayList.name],
        filter_fields={
            "company_id": HolidayList.company_id,
            "is_default": HolidayList.is_default,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),

    # Shift Type dropdown
    "shift_types": DropdownConfig(
        permission_tag="ShiftType",
        query_builder=build_shift_types_dropdown,
        search_fields=[ShiftType.name],
        filter_fields={
            "company_id": ShiftType.company_id,
            "is_night_shift": ShiftType.is_night_shift,
            "holiday_list_id": ShiftType.holiday_list_id,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),

    # Salary Structure dropdown
    "salary_structures": DropdownConfig(
        permission_tag="SalaryStructure",
        query_builder=build_salary_structures_dropdown,
        search_fields=[SalaryStructure.name],
        filter_fields={
            "company_id": SalaryStructure.company_id,
            "is_active": SalaryStructure.is_active,
            "payment_frequency": SalaryStructure.payment_frequency,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),

    # Payroll Period dropdown
    "payroll_periods": DropdownConfig(
        permission_tag="PayrollPeriod",
        query_builder=build_payroll_periods_dropdown,
        search_fields=[PayrollPeriod.name],
        filter_fields={
            "company_id": PayrollPeriod.company_id,
            "is_closed": PayrollPeriod.is_closed,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),

    # Biometric Device dropdown
    "biometric_devices": DropdownConfig(
        permission_tag="BiometricDevice",
        query_builder=build_biometric_devices_dropdown,
        search_fields=[BiometricDevice.name, BiometricDevice.code, BiometricDevice.ip_address],
        filter_fields={
            "company_id": BiometricDevice.company_id,
            "is_active": BiometricDevice.is_active,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),
}


def register_hr_dropdowns() -> None:
    register_dropdown_configs("hr", HR_DROPDOWN_CONFIGS)
