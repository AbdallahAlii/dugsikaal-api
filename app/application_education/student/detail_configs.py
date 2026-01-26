from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_education.student.query_builders.student_detail_builders import (
    resolve_id_strict,
    resolve_code_strict,
    resolve_id_or_code,
    load_student_detail,
    load_guardian_detail,
)

STUDENT_DETAIL_CONFIGS = {
    "students": DetailConfig(
        permission_tag="Student",
        loader=load_student_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_code_strict,     # ✅ primary identifier
            "name": resolve_id_or_code,      # optional backward compatibility
        },
        cache_enabled=True,
        cache_ttl=900,
        default_by="code",  # ✅ Student detail by code
    ),
    "guardians": DetailConfig(
        permission_tag="Guardian",
        loader=load_guardian_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_code_strict,     # ✅ primary identifier
            "name": resolve_id_or_code,      # optional backward compatibility
        },
        cache_enabled=False,

        default_by="code",  # ✅ Guardian detail by code
    ),
}


def register_module_details() -> None:
    register_detail_configs("education_student", STUDENT_DETAIL_CONFIGS)
