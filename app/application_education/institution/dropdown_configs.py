from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_education.institution.academic_model import AcademicYear, AcademicTerm
from app.application_education.institution.query_builders.academic_dropdowns import (
    build_academic_years_dropdown,
    build_academic_terms_dropdown,
)

ACADEMIC_DROPDOWN_CONFIGS = {
    "academic_years": DropdownConfig(
        permission_tag="Academic Year",
        query_builder=build_academic_years_dropdown,
        search_fields=[AcademicYear.name],
        filter_fields={"status": AcademicYear.status, "is_current": AcademicYear.is_current},
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
    "academic_terms": DropdownConfig(
        permission_tag="Academic Term",
        query_builder=build_academic_terms_dropdown,
        search_fields=[AcademicTerm.name],
        filter_fields={"status": AcademicTerm.status, "academic_year_id": AcademicTerm.academic_year_id},
        cache_enabled=True,
        cache_ttl=900,
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),
}


def register_module_dropdowns() -> None:
    register_dropdown_configs("education_academic", ACADEMIC_DROPDOWN_CONFIGS)
