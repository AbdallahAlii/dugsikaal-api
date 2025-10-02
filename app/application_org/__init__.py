from __future__ import annotations

def register_module_dropdowns() -> None:
    from app.application_org.dropdown.dropdown_configs import register_org_dropdowns
    register_org_dropdowns()

# Lists/details are not needed for Companies, Branches, and Departments right now
def register_module_lists() -> None:
    pass

def register_module_details() -> None:
    pass
