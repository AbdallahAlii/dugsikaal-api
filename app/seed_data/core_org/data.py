from __future__ import annotations
from datetime import time
from typing import List, Dict, Any

"""
Minimal core master data for a new company.

This is meant to be ERP-style, like ERPNext's setup wizard:
- A few practical UOMs
- A basic Item Group tree with default accounts
- Default Price Lists
- Cash Customer / Cash Supplier parties
- Default Fiscal Year naming template
- Default Holiday List / weekly off pattern
- Default Shift Type
- Default Cost Center naming template
"""

# ---------------------------------------------------------------------------
# Units of Measure
# ---------------------------------------------------------------------------
# "name"   "symbol"
DEFAULT_UOMS: List[Dict[str, Any]] = [
    {"name": "Nos",     "symbol": "nos"},   # generic "numbers"/pieces
    {"name": "Box",     "symbol": "box"},
    {"name": "Pieces",  "symbol": "pcs"},
    {"name": "Kg",      "symbol": "kg"},
]

# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
DEFAULT_BRANDS: List[Dict[str, Any]] = [
    {"name": "No Brand"},
]

# ---------------------------------------------------------------------------
# Item Groups
# ---------------------------------------------------------------------------
# All codes here are per-company. We also carry *account codes* that the
# seeder will map to Account IDs using the COA.
#
# default_*_code fields are optional; if the COA does not have that code,
# the seeder will log and leave the default_*_account_id as NULL.
#
# COA references (from your seed_data/coa/data.py):
# - Inventory:        1141 "Stocks in Hand"
# - Sales Income:     4101 "Sales Income"
# - Service Income:   4102 "Service Income"
# - COGS:             5011 "Cost of Goods Sold (COGS)"
# - Other Direct Cost:5014 "Other Direct Costs"
# - Fixed assets:     1211 "Capital Assets"
# - Depreciation Exp: 5119 "Depreciation Expense"
# - Other Direct Inc: 4109 "Other Direct Income"
DEFAULT_ITEM_GROUPS: List[Dict[str, Any]] = [
    # Root (tree parent only)
    dict(
        code="ALL-ITEMS",
        name="All Item Groups",
        is_group=True,
        parent_code=None,
        default_expense_code=None,
        default_income_code=None,
        default_inventory_code=None,
    ),

    # Leaf: Stock Items (inventory)
    dict(
        code="Products",
        name="Products",
        is_group=False,                # ✅ selectable leaf
        parent_code="ALL-ITEMS",
        default_expense_code="5011",   # COGS
        default_income_code="4101",    # Sales Income
        default_inventory_code="1141", # Stocks in Hand
    ),

    # Leaf: Services
    dict(
        code="SERVICES",
        name="Services",
        is_group=False,                # ✅ selectable leaf
        parent_code="ALL-ITEMS",
        default_expense_code="5014",   # Other Direct Costs
        default_income_code="4102",    # Service Income
        default_inventory_code=None,   # no inventory
    ),

    # Leaf: Fixed Assets (optional but ERP common)
    dict(
        code="FIXED-ASSETS",
        name="Fixed Assets",
        is_group=False,                # ✅ selectable leaf
        parent_code="ALL-ITEMS",
        default_expense_code="5119",   # Depreciation Expense
        default_income_code="4109",    # Other Direct Income
        default_inventory_code="1211", # Capital Assets
    ),
]

# ---------------------------------------------------------------------------
# Price Lists
# ---------------------------------------------------------------------------
DEFAULT_PRICE_LISTS: List[Dict[str, Any]] = [
    {
        "name": "Standard Selling",
        "list_type": "SELLING",   # PriceListType.SELLING
        "price_not_uom_dependent": True,
        "is_active": True,
    },
    {
        "name": "Standard Buying",
        "list_type": "BUYING",    # PriceListType.BUYING
        "price_not_uom_dependent": True,
        "is_active": True,
    },
]

# ---------------------------------------------------------------------------
# Cash Parties (Customer + Supplier)
# ---------------------------------------------------------------------------
# Both as INDIVIDUAL as per your request, and marked as is_cash_party=True.
DEFAULT_CASH_PARTIES: List[Dict[str, Any]] = [
    {
        "code": "CUST-0001",
        "name": "Cash Customer",
        "role": "CUSTOMER",          # PartyRoleEnum.CUSTOMER
        "nature": "INDIVIDUAL",      # PartyNatureEnum.INDIVIDUAL
    },
    {
        "code": "SUP-0001",
        "name": "Cash Supplier",
        "role": "SUPPLIER",          # PartyRoleEnum.SUPPLIER
        "nature": "INDIVIDUAL",      # PartyNatureEnum.INDIVIDUAL
    },
]

# ---------------------------------------------------------------------------
# Fiscal Year defaults
# ---------------------------------------------------------------------------
# Simple naming template: FY 2025, FY 2026, ...
FISCAL_YEAR_NAME_TEMPLATE: str = "FY {year}"

# If you ever want academic-style years (2024-2025), you can extend this later.

# ---------------------------------------------------------------------------
# Holiday List defaults
# ---------------------------------------------------------------------------

# Base name for seeded holiday list; we suffix by year.
DEFAULT_HOLIDAY_LIST_BASE_NAME: str = "Default Holiday List"

# Weekly off days (Python weekday(): Monday=0, Sunday=6)
# Somalia school weekend: Thursday (3) and Friday (4)
DEFAULT_WEEKLY_OFF_DAYS: List[int] = [3, 4]

# Short description used when auto-creating weekly off holidays
HOLIDAY_WEEKLY_OFF_DESCRIPTION_TEMPLATE: str = "Weekly Off ({weekday_name})"

# ---------------------------------------------------------------------------
# Shift Type defaults
# ---------------------------------------------------------------------------

# Default shift types for a new company.
# Times are local to the company's timezone.
DEFAULT_SHIFT_TYPES: List[Dict[str, Any]] = [
    {
        "name": "Day Shift",
        "start_time": time(7, 0),   # 07:00
        "end_time": time(17, 0),    # 17:00
        "enable_auto_attendance": False,
        "is_night_shift": False,
    },
]

# ---------------------------------------------------------------------------
# Cost Center defaults
# ---------------------------------------------------------------------------

# Default naming for a branch-level cost center
DEFAULT_COST_CENTER_NAME_TEMPLATE: str = "{branch_name} Cost Center"
