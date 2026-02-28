from __future__ import annotations


def register_module_lists() -> None:
    from app.application_education.programs.list_configs import register_module_lists as _reg
    _reg()


def register_module_details() -> None:
    from app.application_education.programs.detail_configs import register_module_details as _reg
    _reg()


def register_module_dropdowns() -> None:
    from app.application_education.programs.dropdown_configs import register_module_dropdowns as _reg
    _reg()
