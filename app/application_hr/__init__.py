from __future__ import annotations

def register_module_lists() -> None:
    from app.application_hr.list_configs import register_module_lists as _reg_lists
    _reg_lists()

def register_module_details() -> None:
    from app.application_hr.detail_configs import register_hr_detail_configs
    register_hr_detail_configs()

def register_module_dropdowns() -> None:
    # none for HR right now
    pass
