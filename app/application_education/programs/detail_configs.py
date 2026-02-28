from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_education.programs.query_builders.program_detail_builders import (
    resolve_id_strict,
    resolve_name_strict,
    resolve_id_or_name,
    load_program_detail,
    load_course_detail,
)

PROGRAM_DETAIL_CONFIGS = {
    "programs": DetailConfig(
        permission_tag="Program",
        loader=load_program_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_name_strict,   # ✅ primary identifier
            "code": resolve_id_or_name,    # optional backward compatibility
        },
        cache_enabled=True,
        cache_ttl=900,
        default_by="name",  # ✅ Program detail by name
    ),
    "courses": DetailConfig(
        permission_tag="Course",
        loader=load_course_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_name_strict,   # ✅ primary identifier
            "code": resolve_id_or_name,    # optional backward compatibility
        },
        cache_enabled=True,
        cache_ttl=900,
        default_by="name",  # ✅ Course detail by name
    ),
}


def register_module_details() -> None:
    register_detail_configs("education_program", PROGRAM_DETAIL_CONFIGS)
