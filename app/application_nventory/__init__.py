# app/application_inventory/__init__.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import register_list_configs
from app.application_nventory.detail_configs import register_inventory_detail_configs
from app.application_nventory.dropdown_configs import register_inventory_dropdowns
from app.application_nventory.list_configs import INVENTORY_LIST_CONFIGS


def register_module_lists() -> None:
    """Register the list configurations for the Inventory module."""
    register_list_configs("inventory", INVENTORY_LIST_CONFIGS)

def register_module_details() -> None:
    """Register detail configurations for the Inventory module."""
    register_inventory_detail_configs()


def register_module_dropdowns() -> None:
    register_inventory_dropdowns()
