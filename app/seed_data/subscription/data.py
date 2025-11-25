# app/seed_data/subscriptions/data.py
from typing import List, Dict

# Default company → package subscriptions to set up at seeding time.
# You can add more entries later if you want other companies to get packages.
DEFAULT_COMPANY_PACKAGE_SUBSCRIPTIONS: List[Dict[str, str]] = [
    {
        "company_name": "Haji Technologies",
        "package_slug": "full_suite",   # must match ModulePackage.slug
    },
    # Example if you ever want NETCAM to also get full suite:
    # {
    #     "company_name": "NETCAM TECHNOLOGIES SERVICES",
    #     "package_slug": "full_suite",
    # },
]
