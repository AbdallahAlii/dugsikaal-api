from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs

from app.application_education.programs.models.program_models import Program, Course
from app.application_education.programs.query_builders.program_query_builders import (
    build_programs_query,
    build_courses_query,
)

PROGRAM_LIST_CONFIGS = {
    "programs": ListConfig(
        permission_tag="Program",
        query_builder=build_programs_query,
        search_fields=[Program.name],
        sort_fields={
            "name": Program.name,
            "program_type": Program.program_type,
            "is_enabled": Program.is_enabled,
            "id": Program.id,
            "created_at": Program.created_at,
        },
        filter_fields={
            "company_id": Program.company_id,
            "program_type": Program.program_type,
            "is_enabled": Program.is_enabled,
            "name": Program.name,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
    "courses": ListConfig(
        permission_tag="Course",
        query_builder=build_courses_query,
        search_fields=[Course.name],
        sort_fields={
            "name": Course.name,
            "course_type": Course.course_type,
            "is_enabled": Course.is_enabled,
            "id": Course.id,
            "created_at": Course.created_at,
        },
        filter_fields={
            "company_id": Course.company_id,
            "course_type": Course.course_type,
            "is_enabled": Course.is_enabled,
            "name": Course.name,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
}


def register_module_lists() -> None:
    register_list_configs("education_program", PROGRAM_LIST_CONFIGS)
