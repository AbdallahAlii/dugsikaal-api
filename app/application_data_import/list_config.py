# app/application_data_import/list_config.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_data_import.models import DataImport
from app.application_data_import.query_builders.data_import_list_builders import (
    build_data_imports_list_query,
)
from app.application_org.models.company import Company
from app.application_org.models.company import Branch  # if you want in search_fields


DATA_IMPORT_LIST_CONFIGS = {
    "data_imports": ListConfig(
        permission_tag="DataImport",  # RBAC tag for this module
        query_builder=build_data_imports_list_query,
        search_fields=[
            DataImport.code,
            DataImport.reference_doctype,
            Company.name,
        ],
        sort_fields={
            "id": DataImport.id,
            "code": DataImport.code,
            "reference_doctype": DataImport.reference_doctype,
            "created_at": DataImport.created_at,
            "status": DataImport.status,
        },
        filter_fields={
            "company_id": DataImport.company_id,
            "branch_id": DataImport.branch_id,
            "reference_doctype": DataImport.reference_doctype,
            "import_type": DataImport.import_type,
            "file_type": DataImport.file_type,
            "status": DataImport.status,
        },
        cache_enabled=False,
    ),
}


def register_module_lists() -> None:
    register_list_configs("data_import", DATA_IMPORT_LIST_CONFIGS)
