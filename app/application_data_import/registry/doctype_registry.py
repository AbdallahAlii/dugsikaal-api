# application_data_import/registry/doctype_registry.py
from __future__ import annotations
import importlib
from typing import Any, Callable, Dict

from werkzeug.exceptions import NotFound

REGISTRY: Dict[str, Dict[str, Any]] = {
    "Item": {
        "model": "app.application_nventory.inventory_models:Item",
        "module": "inventory",
        "import_enabled": True,
        # You can update by id (fast) or by sku; UI decides which identity to use
        "identity": {"for_update": "id"},
        "template": {
            # DB-only fields never shown to users in the template
            "exclude_fields_on_insert": [
                "id", "company_id", "branch_id", "created_by_id", "status",
                "is_fixed_asset", "asset_category_id",  # hide fixed-asset fields from import
            ],
            # System-generated fields
            "computed_fields": ["sku"],
            # For convenience, pin these into the selection dialog first
            "always_include": ["name", "item_type"],
            # ✅ Human labels users will see/pick; importer maps them to the fieldnames
            "labels": {
                "sku": "Item Code",
                "name": "Item Name",
                "description": "Description",
                "item_type": "Item Type",
                "item_group_id": "Item Group",
                "base_uom_id": "UOM",
                "brand_id": "Brand",
            },
        },
        "policies": {
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        # ✅ Name→ID resolvers (bulk) — the file can contain human names for these columns
        "resolvers": {
            "item_group_id": {"by": "name", "source": "ItemGroup", "scope": "company"},
            "base_uom_id":   {"by": "name", "source": "UnitOfMeasure", "scope": "company"},
            "brand_id":      {"by": "name", "source": "Brand", "scope": "company", "optional": True},
        },
        # ✅ Conditional required logic: if Item Type = Stock, require UOM
        "conditional_required": [
            {"when": {"item_type": "Stock"}, "require": ["base_uom_id"]}
        ],
        # ✅ Which backend callables the importer should call per row
        "handlers": {
            "create": "app.application_nventory.services.adapters:create_item_via_import",
            "update_by": {
                "id":  "app.application_nventory.services.adapters:update_item_by_id",
                "sku": "app.application_nventory.services.adapters:update_item_by_sku",
            },
        },
    },

    "Employee": {
        "model": "app.application_hr.models.hr:Employee",
        "module": "hr",
        "import_enabled": True,
        "identity": {"for_update": "code"},
        "template": {
            "exclude_fields_on_insert": [
                "id", "company_id", "branch_id", "created_by_id", "status",
                "code", "user_id", "username"
            ],
            "computed_fields": ["code", "user_id", "username"],
            "always_include": ["full_name", "sex", "date_of_joining"],
            "labels": {
                "code": "Employee Code",
                "full_name": "Full Name",
                "sex": "Gender",
                "date_of_joining": "Date of Joining",
                # child tables/assignments are handled separately if you expose them
            },
        },
        "policies": {
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        "resolvers": {
            # example if you allow a branch column label in template:
            "assignments[].branch_id": {"by": "name", "source": "Branch", "scope": "company"},
        },
        "handlers": {
            "create": "app.application_hr.services.services:HrService.create_employee",
            "update_by": {
                "code": "app.application_hr.services.adapters:update_employee_by_code",
                "id":   "app.application_hr.services.services:HrService.update_employee",
            },
        },
    },
}


def get_doctype_cfg(reference_doctype: str) -> Dict[str, Any]:
    cfg = REGISTRY.get(reference_doctype)
    if not cfg:
        raise NotFound(f"Unknown DocType '{reference_doctype}'.")
    return cfg


def import_callable(dotted: str) -> Callable[..., Any]:
    """
    "pkg.mod:Class.method" or "pkg.mod:function". Returns a bound callable.
    If Class.method, creates a singleton service instance and returns the bound method.
    """
    if ":" not in dotted:
        mod_path, func_name = dotted.rsplit(".", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, func_name)

    mod_cls, func_name = dotted.split(":")
    mod_path, cls_name = mod_cls.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    singleton = getattr(cls, "__di_singleton__", None)
    if singleton is None:
        singleton = cls()
        setattr(cls, "__di_singleton__", singleton)
    return getattr(singleton, func_name)
