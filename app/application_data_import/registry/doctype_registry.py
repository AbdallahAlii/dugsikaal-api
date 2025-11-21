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
        "identity": {"for_update": "id"},
        "template": {
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "status",
                "is_fixed_asset",
                "asset_category_id",
            ],
            "computed_fields": ["sku"],
            "always_include": ["name", "item_type"],
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
        "resolvers": {
            "item_group_id": {
                "by": "name",
                "source": "ItemGroup",
                "scope": "company",
            },
            "base_uom_id": {
                "by": "name",
                "source": "UnitOfMeasure",
                "scope": "company",
            },
            "brand_id": {
                "by": "name",
                "source": "Brand",
                "scope": "company",
                "optional": True,
            },
        },
        "conditional_required": [
            {"when": {"item_type": "Stock"}, "require": ["base_uom_id"]}
        ],
        "handlers": {
            "create": "app.application_nventory.services.create_item_via_import",
            "update_by": {
                "id": "app.application_nventory.services.update_item_by_id",
                "sku": "app.application_nventory.services.update_item_by_sku",
            },
        },
    },

    # ----------------------------------------------------------------------
    # NEW: StockReconciliation data import
    # ----------------------------------------------------------------------
    "StockReconciliation": {
        "model": "app.application_stock.stock_models:StockReconciliation",
        "module": "stock",
        "import_enabled": True,
        # we could support UPDATE later using id; for now we focus on INSERT
        "identity": {"for_update": "id"},
        "template": {
            # Fields we NEVER allow the user to insert directly
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "doc_status",
                "created_at",
                "updated_at",
            ],
            # No auto-stripped computed fields; we allow manual 'code'
            "computed_fields": [],
            # Default columns to always show in template
            "always_include": [
                "posting_date",
                "purpose",
                "notes",
                "difference_account_id",
                "item_id",
                "warehouse_id",
                "quantity",
                "valuation_rate",
            ],
            "labels": {
                "code": "Reconciliation Code",          # optional
                "posting_date": "Posting Date",
                "purpose": "Purpose",
                "notes": "Notes",
                "branch_id": "Branch",
                "difference_account_id": "Difference Account",
                "item_id": "Item",
                "warehouse_id": "Warehouse",
                "quantity": "Quantity",
                "valuation_rate": "Valuation Rate",
            },
        },
        "policies": {
            # after import you will manually submit from the UI / API
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        # How we resolve user-friendly labels to IDs
        "resolvers": {
            # Optional branch: if blank, DataImport.branch_id (current user's branch) is used.
            "branch_id": {
                "by": "name",
                "source": "Branch",
                "scope": "company",
                "optional": True,
            },
            # Item resolved by Item Name (per company)
            "item_id": {
                "by": "name",
                "source": "Item",
                "scope": "company",
            },
            # Warehouse resolved by Warehouse Name (per branch)
            "warehouse_id": {
                "by": "name",
                "source": "Warehouse",
                "scope": "branch",
            },
            # Difference Account resolved by Account Name (per company, optional)
            "difference_account_id": {
                "by": "name",
                "source": "Account",
                "scope": "company",
                "optional": True,
            },
        },
        # Hard requirements at row level
        "conditional_required": [
            # For every row: we need item, warehouse, quantity.
            {"when": {}, "require": ["item_id", "warehouse_id", "quantity"]},
        ],
        "handlers": {
            # Single-row handler: one document per row
            "create": "app.application_stock.services.adapters.create_stock_reconciliation_via_import",
            # no update handlers yet; can be added later
        },
    },

    "Employee": {
        "model": "app.application_hr.models.hr:Employee",
        "module": "hr",
        "import_enabled": True,
        "identity": {"for_update": "code"},
        "template": {
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "status",
                "code",
                "user_id",
                "username",
            ],
            "computed_fields": ["code", "user_id", "username"],
            "always_include": ["full_name", "sex", "date_of_joining"],
            "labels": {
                "code": "Employee Code",
                "full_name": "Full Name",
                "sex": "Gender",
                "date_of_joining": "Date of Joining",
            },
        },
        "policies": {
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        "resolvers": {
            "assignments[].branch_id": {
                "by": "name",
                "source": "Branch",
                "scope": "company",
            },
        },
        "handlers": {
            "create": "app.application_hr.services.services:HrService.create_employee",
            "update_by": {
                "code": "app.application_hr.services.adapters:update_employee_by_code",
                "id": "app.application_hr.services.services:HrService.update_employee",
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
    - 'pkg.mod.func'         -> free function
    - 'pkg.mod.Class:method' -> Class instance method (singleton)
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
