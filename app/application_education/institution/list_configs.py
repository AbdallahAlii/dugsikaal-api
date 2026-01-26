from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs

from app.application_education.institution.academic_model import AcademicYear, AcademicTerm
from app.application_education.institution.query_builders.build_academic_queries import (
    build_academic_years_query,
    build_academic_terms_query,
)

ACADEMIC_LIST_CONFIGS = {
    "academic_years": ListConfig(
        permission_tag="Academic Year",
        query_builder=build_academic_years_query,
        search_fields=[
            AcademicYear.name,
        ],
        sort_fields={
            "name": AcademicYear.name,
            "start_date": AcademicYear.start_date,
            "end_date": AcademicYear.end_date,
            "status": AcademicYear.status,
            "id": AcademicYear.id,
        },
        filter_fields={
            "company_id": AcademicYear.company_id,
            "status": AcademicYear.status,
            "is_current": AcademicYear.is_current,
            "start_date": AcademicYear.start_date,
            "end_date": AcademicYear.end_date,
            "name": AcademicYear.name,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
    "academic_terms": ListConfig(
        permission_tag="Academic Term",
        query_builder=build_academic_terms_query,
        search_fields=[
            AcademicTerm.name,
        ],
        sort_fields={
            "name": AcademicTerm.name,
            "start_date": AcademicTerm.start_date,
            "end_date": AcademicTerm.end_date,
            "status": AcademicTerm.status,
            "id": AcademicTerm.id,
        },
        filter_fields={
            "company_id": AcademicTerm.company_id,
            "academic_year_id": AcademicTerm.academic_year_id,
            "status": AcademicTerm.status,
            "start_date": AcademicTerm.start_date,
            "end_date": AcademicTerm.end_date,
            "name": AcademicTerm.name,
        },
        cache_enabled=True,
        cache_ttl=600,
        cache_scope="COMPANY",
    ),
}


def register_module_lists() -> None:
    register_list_configs("education_academic", ACADEMIC_LIST_CONFIGS)
