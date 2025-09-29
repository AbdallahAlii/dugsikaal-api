from __future__ import annotations

def register_module_lists() -> None:
    # local import to avoid circulars
    from app.application_parties.list_configs import register_module_lists as _reg
    _reg()

def register_module_details() -> None:
    from app.application_parties.detail_configs import register_parties_detail_configs
    register_parties_detail_configs()

def register_module_dropdowns() -> None:
    # none for parties yet
    pass
