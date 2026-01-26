from typing import List, Dict

# ------------------------------------------------------------
# Lean, reusable departments (KEEP AS-IS)
# ------------------------------------------------------------

DEFAULT_DEPARTMENTS: List[str] = [
    "Administration",
    "Finance",
    "Sales",
    "Purchasing",
    "Logistics",
    "Operations",
    "Human Resources",
    "IT",
    "Customer Service",
    "Warehouse",
]

# ------------------------------------------------------------
# User types seeded first
# ------------------------------------------------------------

DEFAULT_USER_TYPES: List[str] = [
    "Owner",
    "System User",
    "System Administrator",
]

# ------------------------------------------------------------
# System-level owners (users only, no affiliations)
# ------------------------------------------------------------

SYSTEM_OWNER_USERS: List[Dict] = [
    {"username": "sys_owner1", "password": "ChangeMe!123"},
    {"username": "sys_owner2", "password": "ChangeMe!123"},
]

# ❌ INITIAL_COMPANIES REMOVED (intentionally)
