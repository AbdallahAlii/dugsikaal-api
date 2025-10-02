# app/application_stock/__init__.py
from __future__ import annotations

__all__ = [
    "engine",
    "jobs",
]

def register_module_lists() -> None:
    from app.application_stock.list_configs import register_module_lists as _reg_lists
    _reg_lists()

def register_module_details() -> None:
    from app.application_stock.detail_configs import register_stock_detail_configs
    register_stock_detail_configs()

def register_module_dropdowns() -> None:
    from app.application_stock.dropdown_configs import register_stock_dropdowns
    register_stock_dropdowns()