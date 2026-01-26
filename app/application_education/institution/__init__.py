from __future__ import annotations

def register_module_lists() -> None:
    # local import to avoid circulars
    from app.application_education.institution.list_configs import register_module_lists as _reg
    _reg()

def register_module_details() -> None:
    from app.application_education.institution.detail_configs import register_module_details
    register_module_details()

def register_module_dropdowns() -> None:
    from app.application_education.institution.dropdown_configs import register_module_dropdowns
    register_module_dropdowns()
