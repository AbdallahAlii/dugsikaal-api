# app/seed_data/education_fees_defaults/data.py
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Any

# ---------------------------------------------------------------------------
# COA account CODES (from seed_data/coa/data.py)
# ---------------------------------------------------------------------------
COA_CODE_TUITION_INCOME = "4104"     # Tuition Fees
COA_CODE_ADMISSION_INCOME = "4105"   # Admission Fees
COA_CODE_EXAM_INCOME = "4106"        # Exam Fees
COA_CODE_SERVICE_EXPENSE = "5014"    # Other Direct Costs (service expense)

# ---------------------------------------------------------------------------
# Fee Item Group Tree (under existing ALL-ITEMS)
# ---------------------------------------------------------------------------
FEE_ITEM_GROUP_PARENT = dict(
    code="FEE-ALL",
    name="All Fee Items",
    is_group=True,
    parent_code="ALL-ITEMS",
    default_income_code=None,
    default_expense_code=None,
    default_inventory_code=None,
)

FEE_ITEM_GROUPS: List[Dict[str, Any]] = [
    # Tuition
    dict(
        code="FEE-COMP",
        name="Tuition Fees",
        is_group=False,
        parent_code="FEE-ALL",
        default_income_code=COA_CODE_TUITION_INCOME,
        default_expense_code=COA_CODE_SERVICE_EXPENSE,
        default_inventory_code=None,
    ),
    # Exams
    dict(
        code="EXAM-COMP",
        name="Exam Fees",
        is_group=False,
        parent_code="FEE-ALL",
        default_income_code=COA_CODE_EXAM_INCOME,
        default_expense_code=COA_CODE_SERVICE_EXPENSE,
        default_inventory_code=None,
    ),
    # Admission
    dict(
        code="ADM-COMP",
        name="Admission Fees",
        is_group=False,
        parent_code="FEE-ALL",
        default_income_code=COA_CODE_ADMISSION_INCOME,
        default_expense_code=COA_CODE_SERVICE_EXPENSE,
        default_inventory_code=None,
    ),
]

# ---------------------------------------------------------------------------
# Service Items (non-stock)
# ---------------------------------------------------------------------------
FEE_SERVICE_ITEMS: List[Dict[str, Any]] = [
    # Tuition
    dict(name="Tuition Fee", sku="TUITION", item_group_code="FEE-COMP"),
    # Admission
    dict(name="Admission Fee", sku="ADMISSION", item_group_code="ADM-COMP"),
    # Exams
    dict(name="Exam Fee - Monthly 1", sku="EXAM_M1", item_group_code="EXAM-COMP"),
    dict(name="Exam Fee - Monthly 2", sku="EXAM_M2", item_group_code="EXAM-COMP"),
    dict(name="Exam Fee - Midterm",   sku="EXAM_MID", item_group_code="EXAM-COMP"),
    dict(name="Exam Fee - Final",     sku="EXAM_FIN", item_group_code="EXAM-COMP"),
]

# ---------------------------------------------------------------------------
# Selling Price Lists (grade tiers)
# ---------------------------------------------------------------------------
SELLING_PRICE_LISTS: List[Dict[str, Any]] = [
    dict(name="PL - Grade 1",     list_type="SELLING", is_default=False),
    dict(name="PL - Grade 6",     list_type="SELLING", is_default=False),
    dict(name="PL - Grade 9-12", list_type="SELLING", is_default=False),
]

# Grade → tier mapping (ERP-style tiers)
# - Grades 1-5   => PL - Grade 1 (Selling)
# - Grades 6-9   => PL - Grade 6 (Selling)
# - Grades 10-12 => PL - Grade 10-12 (Selling)
GRADE_TIER_PRICE_LIST: Dict[int, str] = {
    **{g: "PL - Grade 1" for g in range(1, 6)},
    **{g: "PL - Grade 6" for g in range(6, 10)},
    **{g: "PL - Grade 9-12" for g in range(10, 13)},
}

# Tuition price by tier
TUITION_PRICES: Dict[str, Decimal] = {
    "PL - Grade 1": Decimal("8.00"),
    "PL - Grade 6": Decimal("10.00"),
    "PL - Grade 9-12": Decimal("15.00"),
}

# ---------------------------------------------------------------------------
# Fee Categories (Education labels mapped to Items)
# ---------------------------------------------------------------------------
FEE_CATEGORIES: List[Dict[str, Any]] = [
    dict(name="Tuition", item_sku="TUITION"),
    dict(name="Admission", item_sku="ADMISSION"),
    dict(name="Exam - Monthly 1", item_sku="EXAM_M1"),
    dict(name="Exam - Monthly 2", item_sku="EXAM_M2"),
    dict(name="Exam - Midterm",   item_sku="EXAM_MID"),
    dict(name="Exam - Final",     item_sku="EXAM_FIN"),
]
