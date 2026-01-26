# app/application_data_import/detail_config.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import (
    DetailConfig,
    register_detail_configs,
)

from app.application_data_import.query_builders.data_import_detail_builders import (
    load_data_import_detail,
    resolve_data_import_by_code,
)

DATA_IMPORT_DETAIL_CONFIGS = {
    "data_imports": DetailConfig(
        permission_tag="DataImport",
        loader=load_data_import_detail,
        # e.g. /api/details/data_import/data_imports?code=DIMP-2025-00001
        resolver_map={"code": resolve_data_import_by_code},
        cache_enabled=False,
    ),
}


def register_data_import_detail_configs() -> None:
    register_detail_configs("data_import", DATA_IMPORT_DETAIL_CONFIGS)
