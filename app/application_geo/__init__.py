from __future__ import annotations

def register_module_dropdowns() -> None:
    from app.application_geo.dropdown_configs import register_geo_dropdowns
    register_geo_dropdowns()

# Lists/details are not needed for Cities right now
def register_module_lists() -> None:
    pass

def register_module_details() -> None:
    pass
