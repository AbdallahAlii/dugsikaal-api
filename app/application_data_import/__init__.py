# application_data_import/__init__.py
from __future__ import annotations
from app.application_data_import.list_config import DATA_IMPORT_LIST_CONFIGS
from app.application_doctypes.core_lists.config import register_list_configs
from app.application_data_import.detail_config import (
    register_data_import_detail_configs,
)


def register_module_lists() -> None:
    """Register list configs for Data Import."""
    register_list_configs("data_import", DATA_IMPORT_LIST_CONFIGS)


def register_module_details() -> None:
    """Register detail configs for Data Import."""
    register_data_import_detail_configs()
# Kept minimal on purpose. The app factory in app/__init__.py registers blueprints.
# This package exposes only the registry-loader convenience for early imports.

def ready() -> bool:
    return True
