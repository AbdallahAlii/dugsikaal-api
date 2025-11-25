# seed_data/navigation_workspace/subscription/packages.py
# -*- coding: utf-8 -*-

# Each package lists workspaces by slug.
MODULE_PACKAGES = [
    {
        "slug": "inventory",
        "name": "Inventory",
        "description": "Stock, warehouses, and movements",
        "workspaces": ["stock", "hr"],
        "is_enabled": True,
    },
    {
        "slug": "buying",
        "name": "Buying",
        "description": "Procurement & receipts",
        "workspaces": ["buying", "hr"],
        "is_enabled": True,
    },
    {
        "slug": "selling",
        "name": "Selling",
        "description": "Sales & delivery",
        "workspaces": ["selling", "hr"],
        "is_enabled": True,
    },
    {
        "slug": "accounting",
        "name": "Accounting",
        "description": "Finance & accounting",
        "workspaces": ["accounting", "hr"],
        "is_enabled": True,
    },
    {
        "slug": "full_suite",
        "name": "Full Suite",
        "description": "All business modules",
        "workspaces": [
            "stock",
            "accounting",
            "buying",
            "selling",
            "hr",
            "access-control",
            "doctype-directory",
            # host-admin is system-only; do not bundle by default
        ],
        "is_enabled": True,
    },
]
