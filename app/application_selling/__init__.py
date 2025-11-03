# app/application_selling/__init__.py
from __future__ import annotations
from app.application_selling.dropdown_configs import register_selling_dropdowns

from app.application_selling.detail_configs import register_selling_detail_configs
from app.application_doctypes.core_lists.config import register_list_configs
from app.application_selling.list_configs import SELLING_LIST_CONFIGS

def register_module_lists() -> None:
    """Register list configs for Selling."""
    register_list_configs("selling", SELLING_LIST_CONFIGS)

def register_module_details() -> None:
    """Register detail configs for Selling."""
    register_selling_detail_configs()

def register_module_dropdowns() -> None:
    register_selling_dropdowns()

