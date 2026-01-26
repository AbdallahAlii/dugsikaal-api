from __future__ import annotations

from app.application_accounting.detail_configs import register_accounting_detail_configs
from app.application_accounting.dropdown_configs import register_accounting_dropdowns
from app.application_doctypes.core_lists.config import register_list_configs
from app.application_accounting.list_configs import ACCOUNTING_LIST_CONFIGS
from app.application_accounting.print_configs import register_accounting_print_configs


def register_module_lists() -> None:
    """Register the list configurations for the Accounting module."""
    register_list_configs("accounting", ACCOUNTING_LIST_CONFIGS)

def register_module_details() -> None:
    """Register the detail configurations for the Accounting module."""
    register_accounting_detail_configs()



def register_module_dropdowns() -> None:
    register_accounting_dropdowns()



def register_module_prints() -> None:
    """Register print configurations for the Accounting module."""
    register_accounting_print_configs()