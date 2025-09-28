# app/application_hr/__init__.py
from __future__ import annotations

from app.application_doctypes.core_lists.config import register_list_configs
from app.application_hr.config import HR_LIST_CONFIGS


def register_module_lists() -> None:
    register_list_configs("hr", HR_LIST_CONFIGS)

