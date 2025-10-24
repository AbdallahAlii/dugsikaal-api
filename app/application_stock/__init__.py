from __future__ import annotations

__all__ = [
    "engine",
    "jobs",
]

def register_module_lists() -> None:
    """Register the list configurations for the Stock module."""
    from app.application_stock.list_configs import register_stock_lists
    register_stock_lists()  # FIXED: Call the renamed function

def register_module_details() -> None:
    """Register detail configurations for the Stock module."""
    from app.application_stock.detail_configs import register_stock_detail_configs
    register_stock_detail_configs()

def register_module_dropdowns() -> None:
    """Register dropdown configurations for the Stock module."""
    from app.application_stock.dropdown_configs import register_stock_dropdowns
    register_stock_dropdowns()