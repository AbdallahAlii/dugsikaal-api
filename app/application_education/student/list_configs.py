from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs

from app.application_education.student.models import Student, Guardian
from app.application_education.student.query_builders.student_query_builders import (
    build_students_query,
    build_guardians_query,
)

STUDENT_LIST_CONFIGS = {
    "students": ListConfig(
        permission_tag="Student",
        query_builder=build_students_query,
        search_fields=[
            Student.full_name,
            Student.student_code,
        ],
        sort_fields={
            "name": Student.full_name,
            "code": Student.student_code,
            "is_enabled": Student.is_enabled,
            "branch_id": Student.branch_id,
            "id": Student.id,
            "created_at": Student.created_at,
        },
        filter_fields={
            "company_id": Student.company_id,
            "branch_id": Student.branch_id,
            "is_enabled": Student.is_enabled,
            "student_code": Student.student_code,
            "full_name": Student.full_name,
            "student_email": Student.student_email,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
    "guardians": ListConfig(
        permission_tag="Guardian",
        query_builder=build_guardians_query,
        search_fields=[
            Guardian.guardian_name,
            Guardian.guardian_code,
            Guardian.mobile_number,
        ],
        sort_fields={
            "name": Guardian.guardian_name,
            "code": Guardian.guardian_code,
            "mobile_number": Guardian.mobile_number,
            "branch_id": Guardian.branch_id,
            "id": Guardian.id,
            "created_at": Guardian.created_at,
        },
        filter_fields={
            "company_id": Guardian.company_id,
            "branch_id": Guardian.branch_id,
            "guardian_code": Guardian.guardian_code,
            "guardian_name": Guardian.guardian_name,
            "email_address": Guardian.email_address,
            "mobile_number": Guardian.mobile_number,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
}


def register_module_lists() -> None:
    register_list_configs("education_student", STUDENT_LIST_CONFIGS)
