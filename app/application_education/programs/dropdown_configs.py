from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_education.programs.models.program_models import Program, Course
from app.application_education.programs.query_builders.program_dropdowns import (
    build_programs_dropdown,
    build_courses_dropdown,
)

PROGRAM_DROPDOWN_CONFIGS = {
    "programs": DropdownConfig(
        permission_tag="Program",
        query_builder=build_programs_dropdown,
        search_fields=[Program.name],
        filter_fields={
            "program_type": Program.program_type,
            "is_enabled": Program.is_enabled,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "courses": DropdownConfig(
        permission_tag="Course",
        query_builder=build_courses_dropdown,
        search_fields=[Course.name],
        filter_fields={
            "course_type": Course.course_type,
            "is_enabled": Course.is_enabled,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
}


def register_module_dropdowns() -> None:
    register_dropdown_configs("education_program", PROGRAM_DROPDOWN_CONFIGS)
