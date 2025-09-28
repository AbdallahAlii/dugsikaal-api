from __future__ import annotations

from app.application_buying.detail_configs import register_buying_detail_configs
from app.application_doctypes.core_lists.config import register_list_configs
from app.application_buying.list_configs import BUYING_LIST_CONFIGS


def register_module_lists() -> None:
    """Register the list configurations for the Buying module."""
    register_list_configs("buying", BUYING_LIST_CONFIGS)
def register_module_details() -> None:
    """Register the detail configurations for the Buying module."""
    register_buying_detail_configs()