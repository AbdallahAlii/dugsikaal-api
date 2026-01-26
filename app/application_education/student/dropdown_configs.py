from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_education.student.models import Student, Guardian
from app.application_education.student.query_builders.student_dropdowns import (
    build_students_dropdown,
    build_guardians_dropdown,
)

STUDENT_DROPDOWN_CONFIGS = {
    "students": DropdownConfig(
        permission_tag="Student",
        query_builder=build_students_dropdown,
        search_fields=[
            Student.full_name,
            Student.student_code,
            Student.student_mobile_number,
        ],
        filter_fields={
            "branch_id": Student.branch_id,
            "is_enabled": Student.is_enabled,
        },
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),

    "guardians": DropdownConfig(
        permission_tag="Guardian",
        query_builder=build_guardians_dropdown,
        search_fields=[
            Guardian.guardian_name,
            Guardian.guardian_code,
            Guardian.mobile_number,
        ],
        filter_fields={
            "branch_id": Guardian.branch_id,
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
    register_dropdown_configs("education_student", STUDENT_DROPDOWN_CONFIGS)
