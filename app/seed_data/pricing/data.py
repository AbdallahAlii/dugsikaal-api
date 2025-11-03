# seed_data/pricing/data.py
from __future__ import annotations
from typing import List, Dict, Any

# Two defaults per company, ERP-style
DEFAULT_PRICE_LISTS: List[Dict[str, Any]] = [
    {
        "name": "Standard Buying",
        "list_type": "Buying",                 # enum as string; mapped in seeder
        "price_not_uom_dependent": False,      # you asked both to be False
        "is_active": True,
    },
    {
        "name": "Standard Selling",
        "list_type": "Selling",
        "price_not_uom_dependent": False,
        "is_active": True,
    },
]
