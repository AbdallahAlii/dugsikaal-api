# app/application_org/__init__.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import register_list_configs
from app.application_org.detail_config import register_org_detail_configs
from app.application_org.list_config import ORG_LIST_CONFIGS


def register_module_lists() -> None:
    """Register list configs for Org (companies, branches)."""
    register_list_configs("org", ORG_LIST_CONFIGS)


def register_module_details() -> None:
    """Register detail configs for Org (companies, branches)."""
    register_org_detail_configs()



def register_module_dropdowns() -> None:
    from app.application_org.dropdown.dropdown_configs import register_org_dropdowns
    register_org_dropdowns()

