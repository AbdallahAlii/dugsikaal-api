# application_data_import/registry/doctype_registry.py
from __future__ import annotations
import importlib
from typing import Any, Callable, Dict

from werkzeug.exceptions import NotFound

REGISTRY: Dict[str, Dict[str, Any]] = {
    # ======================================================================
    # ITEM
    # ======================================================================
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

    # ======================================================================
    # STOCK RECONCILIATION
    # ======================================================================
    "StockReconciliation": {
        "model": "app.application_stock.stock_models:StockReconciliation",
        "module": "stock",
        "import_enabled": True,
        # we could support UPDATE later using id; for now we focus on INSERT
        "identity": {"for_update": "id"},
        "template": {
            # Fields we NEVER allow the user to insert directly on the header
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "doc_status",
                "created_at",
                "updated_at",
            ],
            # Treat 'code' as computed/auto-managed -> not required from Excel
            # and safe to drop if the user sends it.
            "computed_fields": ["code"],
            # Default columns to always show in template (header + line fields)
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
            # For Stock Reconciliation we allow `submit_after_import=True`
            # (used for Opening Stock and Stock Reconciliation imports).
            "submit_after_import_allowed": True,
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
            "update_by": {},
        },
    },

    # ======================================================================
    # EMPLOYEE
    # ======================================================================
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
            # Minimal required columns in Excel:
            #   - Full Name
            #   - Date of Joining
            # Branch comes from DataImport.branch_id, not the file.
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
        # You can still support advanced patterns later (assignments[].branch_id etc).
        "resolvers": {
            "assignments[].branch_id": {
                "by": "name",
                "source": "Branch",
                "scope": "company",
            },
        },
        "handlers": {
            # Use adapter for Data Import (row → EmployeeCreate → HrService.create_employee)
            "create": "app.application_hr.services.adapters.create_employee_via_import",
            "update_by": {
                # Adapters for UPDATE imports
                "code": "app.application_hr.services.adapters.update_employee_by_code",
                "id": "app.application_hr.services.adapters.update_employee_by_id",
            },
        },
    },


    # ======================================================================
    # CUSTOMER  (Party with role = CUSTOMER)
    # ======================================================================
    "Customer": {
        # Same underlying model as Supplier: Party
        "model": "app.application_parties.parties_models:Party",
        "module": "parties",
        "import_enabled": True,
        # If you add UPDATE later, you can use "code" as identity
        "identity": {"for_update": "code"},
        "template": {
            # Fields we NEVER want the user to import directly
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "status",
                "role",           # role is fixed to CUSTOMER in adapter
                "code",           # code generated by service if missing
                "is_cash_party",  # handled by default (False) in service
                "img_key",
            ],
            "computed_fields": [
                # you could also put "code" here, but exclude_on_insert is enough
            ],
            # Columns that must exist in the file for INSERT imports
            "always_include": [
                "name",    # Customer Name
                "phone",   # Phone
                "nature",  # Customer Type (Organization / Individual)
            ],
            "labels": {
                "code": "Customer Code",
                "name": "Customer Name",
                "nature": "Customer Type",   # maps Excel header -> Party.nature
                "phone": "Phone",
                "email": "Email",
                "address_line1": "Address",
                # You can add more mappings later (City, Notes, etc.)
            },
        },
        "policies": {
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        # No link resolvers yet (city can be added later if you want name->id)
        "resolvers": {
            # e.g. "city_id": { "by": "name", "source": "City", "scope": "company" }
        },
        "conditional_required": [
            # If you want row-level conditional rules later, put them here.
            # For now, header-level required: name / phone / nature handled by always_include.
        ],
        "handlers": {
            "create": "app.application_parties.import_adapters.create_customer_via_import",
            # no UPDATE via import for now; keep empty dict so UPDATE ImportType fails cleanly
            "update_by": {},
        },
    },

    # ======================================================================
    # SUPPLIER  (Party with role = SUPPLIER)
    # ======================================================================
    "Supplier": {
        "model": "app.application_parties.parties_models:Party",
        "module": "parties",
        "import_enabled": True,
        "identity": {"for_update": "code"},
        "template": {
            "exclude_fields_on_insert": [
                "id",
                "company_id",
                "branch_id",
                "created_by_id",
                "status",
                "role",           # fixed to SUPPLIER in adapter
                "code",
                "is_cash_party",
                "img_key",
            ],
            "computed_fields": [],
            "always_include": [
                "name",    # Supplier Name
                "phone",   # Phone
                "nature",  # Supplier Type
            ],
            "labels": {
                "code": "Supplier Code",
                "name": "Supplier Name",
                "nature": "Supplier Type",   # maps header -> Party.nature
                "phone": "Phone",
                "email": "Email",
                "address_line1": "Address",
            },
        },
        "policies": {
            "submit_after_import_allowed": False,
            "mute_emails_supported": True,
        },
        "resolvers": {
            # e.g. "city_id": { "by": "name", "source": "City", "scope": "company" }
        },
        "conditional_required": [],
        "handlers": {
            "create": "app.application_parties.import_adapters.create_supplier_via_import",
            "update_by": {},
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
