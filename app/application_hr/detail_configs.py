from __future__ import annotations
from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_hr.query_builders.employee_detail_builders import (
    resolve_id_strict, resolve_employee_by_code, load_employee_detail
)

HR_DETAIL_CONFIGS = {
    "employees": DetailConfig(
        permission_tag="Employee",
        loader=load_employee_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_employee_by_code,
        },
        cache_enabled=True,
        cache_ttl=900,          # employee details change infrequently
        default_by="code",
    ),
}

def register_hr_detail_configs() -> None:
    register_detail_configs("hr", HR_DETAIL_CONFIGS)
