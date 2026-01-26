# seed_data/coa/data.py
from typing import List, Dict, Any

# Placeholder for dynamic root; the seeder replaces this with the actual root code
ROOT_PLACEHOLDER = "__ROOT__"

# Parent rows MUST appear before their children.
DEFAULT_ACCOUNTS: List[Dict[str, Any]] = [
    # ---------- Top-level groups ----------
    {"code": "1000", "name": "Assets",      "is_group": True, "parent_code": ROOT_PLACEHOLDER, "account_type": "ASSET"},
    {"code": "2000", "name": "Liabilities", "is_group": True, "parent_code": ROOT_PLACEHOLDER, "account_type": "LIABILITY"},
    {"code": "3000", "name": "Equity",      "is_group": True, "parent_code": ROOT_PLACEHOLDER, "account_type": "EQUITY"},
    {"code": "4000", "name": "Income",      "is_group": True, "parent_code": ROOT_PLACEHOLDER, "account_type": "INCOME"},
    {"code": "5000", "name": "Expenses",    "is_group": True, "parent_code": ROOT_PLACEHOLDER, "account_type": "EXPENSE"},

    # ========== 1) ASSETS ==========
    {"code": "1100", "name": "Current Assets", "is_group": True, "parent_code": "1000", "account_type": "ASSET"},

    # Cash (generic)
    {"code": "1110", "name": "Cash in Hand", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1111", "name": "Cash", "is_group": False, "parent_code": "1110", "account_type": "ASSET"},

    # Bank (group only - tenant will create banks later)
    {"code": "1120", "name": "Bank Accounts", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},

    # Receivable (Frappe-style: Debtors only)
    {"code": "1130", "name": "Accounts Receivable", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1131", "name": "Debtors", "is_group": False, "parent_code": "1130", "account_type": "ASSET"},

    # Inventory
    {"code": "1140", "name": "Inventory Assets", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1141", "name": "Stocks in Hand", "is_group": False, "parent_code": "1140", "account_type": "ASSET"},

    # Loans & Advances
    {"code": "1150", "name": "Loans and Advances (Assets)", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1151", "name": "Employee Advances", "is_group": False, "parent_code": "1150", "account_type": "ASSET"},
    {"code": "1152", "name": "Loans to Shareholders", "is_group": False, "parent_code": "1150", "account_type": "ASSET"},

    # Investments
    {"code": "1160", "name": "Investments", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1161", "name": "Equity Investments", "is_group": False, "parent_code": "1160", "account_type": "ASSET"},

    # Other Current Assets
    {"code": "1170", "name": "Other Current Assets", "is_group": True, "parent_code": "1100", "account_type": "ASSET"},
    {"code": "1171", "name": "Earnest Money", "is_group": False, "parent_code": "1170", "account_type": "ASSET"},
    {"code": "1172", "name": "Temporary Opening", "is_group": False, "parent_code": "1170", "account_type": "ASSET"},

    # Fixed Assets
    {"code": "1200", "name": "Fixed Assets", "is_group": True, "parent_code": "1000", "account_type": "ASSET"},
    {"code": "1210", "name": "Tangible Assets", "is_group": True, "parent_code": "1200", "account_type": "ASSET"},
    {"code": "1211", "name": "Capital Assets", "is_group": False, "parent_code": "1210", "account_type": "ASSET"},
    {"code": "1212", "name": "Office Equipment", "is_group": False, "parent_code": "1210", "account_type": "ASSET"},
    {"code": "1213", "name": "Furniture & Fixtures", "is_group": False, "parent_code": "1210", "account_type": "ASSET"},
    {"code": "1214", "name": "Vehicles", "is_group": False, "parent_code": "1210", "account_type": "ASSET"},
    {"code": "1215", "name": "Lands", "is_group": False, "parent_code": "1210", "account_type": "ASSET"},

    {"code": "1220", "name": "Intangible Assets", "is_group": True, "parent_code": "1200", "account_type": "ASSET"},
    {"code": "1221", "name": "Software", "is_group": False, "parent_code": "1220", "account_type": "ASSET"},
    {"code": "1222", "name": "Brands & Trademarks", "is_group": False, "parent_code": "1220", "account_type": "ASSET"},

    {"code": "1230", "name": "Accumulated Depreciation", "is_group": False, "parent_code": "1200", "account_type": "ASSET"},

    # ========== 2) LIABILITIES ==========
    {"code": "2100", "name": "Current Liabilities", "is_group": True, "parent_code": "2000", "account_type": "LIABILITY"},

    {"code": "2110", "name": "Accounts Payable", "is_group": True, "parent_code": "2100", "account_type": "LIABILITY"},
    {"code": "2111", "name": "Creditors", "is_group": False, "parent_code": "2110", "account_type": "LIABILITY"},

    {"code": "2112", "name": "Taxes Payable", "is_group": False, "parent_code": "2100", "account_type": "LIABILITY"},
    {"code": "2113", "name": "Accrued Expenses", "is_group": False, "parent_code": "2100", "account_type": "LIABILITY"},
    {"code": "2120", "name": "Payroll Payable", "is_group": False, "parent_code": "2100", "account_type": "LIABILITY"},
    {"code": "2130", "name": "Unearned Revenue", "is_group": False, "parent_code": "2100", "account_type": "LIABILITY"},

    {"code": "2200", "name": "Stock Liabilities", "is_group": True, "parent_code": "2000", "account_type": "LIABILITY"},
    {"code": "2210", "name": "Stock Received but Not Billed", "is_group": False, "parent_code": "2200", "account_type": "LIABILITY"},
    {"code": "2211", "name": "Asset Received but Not Billed", "is_group": False, "parent_code": "2200", "account_type": "LIABILITY"},

    {"code": "2300", "name": "Duties and Taxes", "is_group": True, "parent_code": "2000", "account_type": "LIABILITY"},
    {"code": "2310", "name": "TDS Payable", "is_group": False, "parent_code": "2300", "account_type": "LIABILITY"},
    {"code": "2311", "name": "VAT", "is_group": False, "parent_code": "2300", "account_type": "LIABILITY"},
    {"code": "2312", "name": "Other Government Taxes", "is_group": False, "parent_code": "2300", "account_type": "LIABILITY"},

    {"code": "2400", "name": "Loans", "is_group": True, "parent_code": "2000", "account_type": "LIABILITY"},
    {"code": "2410", "name": "Short-term Loan", "is_group": False, "parent_code": "2400", "account_type": "LIABILITY"},
    {"code": "2420", "name": "Long-term Loan", "is_group": False, "parent_code": "2400", "account_type": "LIABILITY"},
    {"code": "2430", "name": "Bank Overdraft", "is_group": False, "parent_code": "2400", "account_type": "LIABILITY"},

    # ========== 3) EQUITY ==========
    {"code": "3001", "name": "Share Capital", "is_group": False, "parent_code": "3000", "account_type": "EQUITY"},
    {"code": "3004", "name": "Opening Balance Equity", "is_group": False, "parent_code": "3000", "account_type": "EQUITY"},
    {"code": "3005", "name": "Retained Earnings", "is_group": False, "parent_code": "3000", "account_type": "EQUITY"},

    # ========== 4) INCOME ==========
    {"code": "4100", "name": "Direct Income", "is_group": True, "parent_code": "4000", "account_type": "INCOME"},
    {"code": "4101", "name": "Sales Income", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},
    {"code": "4102", "name": "Service Income", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},

    {"code": "4104", "name": "Tuition Fees", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},
    {"code": "4105", "name": "Admission Fees", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},
    {"code": "4106", "name": "Exam Fees", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},
    {"code": "4109", "name": "Other Direct Income", "is_group": False, "parent_code": "4100", "account_type": "INCOME"},

    {"code": "4150", "name": "Indirect Income", "is_group": True, "parent_code": "4000", "account_type": "INCOME"},
    {"code": "4151", "name": "Delivery Income", "is_group": False, "parent_code": "4150", "account_type": "INCOME"},
    {"code": "4152", "name": "Bad Debt Recovery", "is_group": False, "parent_code": "4150", "account_type": "INCOME"},
    {"code": "4153", "name": "Round Off Income", "is_group": False, "parent_code": "4150", "account_type": "INCOME"},

    # ========== 5) EXPENSES ==========
    {"code": "5010", "name": "Direct Expenses", "is_group": True, "parent_code": "5000", "account_type": "EXPENSE"},
    {"code": "5011", "name": "Cost of Goods Sold (COGS)", "is_group": False, "parent_code": "5010", "account_type": "EXPENSE"},
    {"code": "5013", "name": "Customs & Duties", "is_group": False, "parent_code": "5010", "account_type": "EXPENSE"},
    {"code": "5014", "name": "Other Direct Costs", "is_group": False, "parent_code": "5010", "account_type": "EXPENSE"},
    {"code": "5015", "name": "Stock Adjustments", "is_group": False, "parent_code": "5010", "account_type": "EXPENSE"},

    {"code": "5100", "name": "Indirect Expenses", "is_group": True, "parent_code": "5000", "account_type": "EXPENSE"},
    {"code": "5106", "name": "Salaries Expense", "is_group": False, "parent_code": "5100", "account_type": "EXPENSE"},
    {"code": "5109", "name": "Rent Expense", "is_group": False, "parent_code": "5100", "account_type": "EXPENSE"},

    {"code": "5108", "name": "Utilities", "is_group": True, "parent_code": "5100", "account_type": "EXPENSE"},
    {"code": "51081", "name": "Electricity Expense", "is_group": False, "parent_code": "5108",
     "account_type": "EXPENSE"},
    {"code": "51082", "name": "Water Expense", "is_group": False, "parent_code": "5108", "account_type": "EXPENSE"},
    {"code": "51083", "name": "Internet & Telecom Expense", "is_group": False, "parent_code": "5108",
     "account_type": "EXPENSE"},

    {"code": "5107", "name": "Repairs & Maintenance", "is_group": False, "parent_code": "5100",
     "account_type": "EXPENSE"},
    {"code": "5114", "name": "Miscellaneous Expenses", "is_group": False, "parent_code": "5100",
     "account_type": "EXPENSE"},
    {"code": "5119", "name": "Depreciation Expense", "is_group": False, "parent_code": "5100",
     "account_type": "EXPENSE"},
    {"code": "5120", "name": "Bank Charges & Fees", "is_group": False, "parent_code": "5100",
     "account_type": "EXPENSE"},
]
