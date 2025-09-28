from __future__ import annotations

# DO NOT import register_list_configs or list configs at module import time.
# Import them *inside* the functions to avoid circular imports.

def register_module_lists() -> None:
    """Register the list configurations for the RBAC module."""
    from app.application_doctypes.core_lists.config import register_list_configs
    from app.application_rbac.list_configs import RBAC_LIST_CONFIGS
    register_list_configs("rbac", RBAC_LIST_CONFIGS )

def register_module_details() -> None:
    from app.application_rbac.detail_configs import register_rbac_detail_configs
    register_rbac_detail_configs()
def register_module_dropdowns() -> None:
    """RBAC currently has no dropdown configs to register."""
    # keep empty (and avoid any imports here)
    pass
