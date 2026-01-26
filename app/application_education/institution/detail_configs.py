from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_education.institution.query_builders.academic_detail_builders import (
    resolve_id_strict,
    resolve_id_or_name,  # New resolver for ID or name
    resolve_company_from_ctx,
    load_academic_year_detail,
    load_academic_term_detail,
    load_education_settings_detail,
)

ACADEMIC_DETAIL_CONFIGS = {
    "academic_years": DetailConfig(
        permission_tag="Academic Year",
        loader=load_academic_year_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_id_or_name,
        },
        cache_enabled=True,
        cache_ttl=900,
        # FIX: Change default_by to "name" so it accepts strings like "2025-2026"
        default_by="name",
    ),
    "academic_terms": DetailConfig(
        permission_tag="Academic Term",
        loader=load_academic_term_detail,
        resolver_map={
            "id": resolve_id_strict,
            "name": resolve_id_or_name,
        },
        cache_enabled=True,
        cache_ttl=900,
        # FIX: Change default_by to "name" so it accepts "Term One"
        default_by="name",
    ),
    # Settings = detail only (by company from ctx)
    "education_settings": DetailConfig(
        permission_tag="Education Settings",
        loader=load_education_settings_detail,
        resolver_map={
            "company": resolve_company_from_ctx,  # Uses session/token company_id
            "company_id": resolve_id_strict,  # Uses the ID from the URL
        },
        cache_enabled=False,
        cache_ttl=0,
        # CHANGE THIS to "company_id" so the URL works with the ID you provide
        default_by="company_id",
    ),
}


def register_module_details() -> None:
    register_detail_configs("education_academic", ACADEMIC_DETAIL_CONFIGS)