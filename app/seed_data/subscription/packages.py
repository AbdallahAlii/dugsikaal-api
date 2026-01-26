# -*- coding: utf-8 -*-

"""
MODULE_PACKAGES defines the purchasable units of the software.
Each package activates specific Workspaces (seed_data/navigation_workspace/data.py).

Rules:
- School ERP must include the full education flow + finance + portals.
- Portals cannot be sold standalone (always bundled).
- Procurement can be included only as part of a bigger package (Full Suite).
"""

MODULE_PACKAGES = [
    # ==========================================================
    # SCHOOL ERP (Education + Fees + Accounting + Portals)
    # ==========================================================
    {
        "slug": "school_erp",
        "name": "School ERP",
        "description": "Complete school system: admissions, academics, scheduling, assessment, fees, accounting, and portals",
        "workspaces": [
            # Education Core
            "admission",
            "academics",
            "scheduling",
            "assessment",

            # Finance / Billing
            "fees",
            "accounting",

            # Portals (bundled)
            "student-portal",
            "teacher-portal",
            "guardian-portal",

            # Admin / user management
            "administration",
        ],
        "is_enabled": True,
    },

    # ==========================================================
    # FULL SUITE (School ERP + Procurement)
    # ==========================================================
    {
        "slug": "full_suite",
        "name": "Full Suite",
        "description": "School ERP plus procurement and inventory management",
        "workspaces": [
            # Everything in School ERP
            "admission",
            "academics",
            "scheduling",
            "assessment",
            "fees",
            "accounting",
            "student-portal",
            "teacher-portal",
            "guardian-portal",
            "administration",

            # Add operations
            "procurement",
        ],
        "is_enabled": True,
    },
]
