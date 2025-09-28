# seed_data/core/data.py
from typing import List, Dict

# Lean, reusable departments
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

# User types seeded first (names as you requested)
DEFAULT_USER_TYPES: List[str] = [
    "Owner",
    "System User",
    "System Administrator",
]

# System-level owners (users only, no affiliations)
SYSTEM_OWNER_USERS: List[Dict] = [
    {"username": "sys_owner1", "password": "ChangeMe!123"},
    {"username": "sys_owner2", "password": "ChangeMe!123"},
]

# Two companies to initialize your environment
INITIAL_COMPANIES: List[Dict] = [
    {
        "name": "NETCAM TECHNOLOGIES SERVICES",
        "headquarters_address": "Taleex, Mogadishu, Somalia",
        "contact_email": "info@netcam.so",
        "contact_phone": "252615992923",
        "prefix": "NTS",
        "hq_branch": {
            "name": "Head Office",
            "code": "NTC-HQ",
            "location": "Taleex, Mogadishu, Somalia",
            "is_hq": True,
        },
        "owner_user": {
            "username": "NTS-0001",      # owner login for this company
            "password": "ChangeMe!123",  # will be bcrypt-hashed
        },
    },
    {
        "name": "Haji Technologies",
        "headquarters_address": "KM4, Mogadishu, Somalia",
        "contact_email": "info@haji-tech.so",
        "contact_phone": "252616001122",
        "prefix": "HJI",
        "hq_branch": {
            "name": "Head Office",
            "code": "HAJI-HQ",
            "location": "KM4, Mogadishu, Somalia",
            "is_hq": True,
        },
        "owner_user": {
            "username": "HJI-0001",
            "password": "ChangeMe!123",
        },
    },
]
