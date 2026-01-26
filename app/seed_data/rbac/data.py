# seed_data/rbac/data.py
from app.application_rbac.rbac_models import RoleScopeEnum  # keep import as-is (even if unused)
from typing import Dict, List, Tuple

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
WILDCARD_DOCTYPE_NAME = "*"
WILDCARD_ACTION_NAME = "*"

# ─────────────────────────────────────────────────────────────
# Default Actions
# ─────────────────────────────────────────────────────────────
# NOTE:
# - MANAGE expands to CRUD at seed time (READ, CREATE, UPDATE, DELETE).
# - For branch roles, avoid MANAGE on sensitive transactional docs to prevent DELETE.
DEFAULT_ACTIONS: List[Tuple[str, str]] = [
    ("READ",   "View a resource"),
    ("CREATE", "Create a new resource"),
    ("UPDATE", "Modify a resource"),
    ("DELETE", "Permanently remove a resource"),

    ("SUBMIT", "Move a document to submitted/posted state"),
    ("CANCEL", "Cancel a submitted document"),
    ("AMEND",  "Amend a submitted document"),

    ("PRINT",  "Generate a printable version"),
    ("EXPORT", "Export data"),
    ("IMPORT", "Import bulk data"),

    ("MANAGE", "CRUD = READ, CREATE, UPDATE, DELETE"),
    ("ASSIGN", "Assign roles or permissions"),

    (WILDCARD_ACTION_NAME, "Unrestricted access to all actions within a resource."),
]

# ─────────────────────────────────────────────────────────────
# Modules (UI grouping)
# ─────────────────────────────────────────────────────────────
DEFAULT_DOCTYPE_MODULES = [
    "System",
    "Core",
    "Platform",
    "Access Control",
    "Data Management",

    # Education Domain
    "Education",
    "Exams",
    "Fees",

    # ERP Domain
    "Accounts",
    "Selling",
    "Buying",
    "Inventory",
    "Stock",

    # HR Domain
    "HR",

    # Communication
    "Communication",

    # Reporting
    "Reporting",
]

# ─────────────────────────────────────────────────────────────
# DocType mappings
# IMPORTANT:
# - DocType names here MUST match your DocType registry exactly.
# - This version uses ERP-style human readable names with spaces.
# ─────────────────────────────────────────────────────────────
DEFAULT_DOCTYPE_MAPPINGS: Dict[str, List[str]] = {
    "System": [
        "Organization",
        "Branch",
        "System Settings",
    ],
    # Core platform utilities
    "Core": [
        "Data Import",
        "Data Export",
        "File",
        "Error Log",
        "Activity Log",
        "Scheduled Job Log",
        "Notification",
        "SMS",
    ],

    "Access Control": [
        "DocType",
        "Action",
        "Permission",
        "Role",
        "User",
        "Role Permission",
        "User Role",
        "Permission Override",
        "User Constraint",
    ],

    # System-wide SaaS console (admin_only workspace should gate it)
    "Platform": [
        "Tenant",  # the SaaS account (client)
        "Organization",  # **ALSO mapped here for Sys Admin Provisioning**
        "Branch",

        "Subscription Plan",  # plans/catalog (configuration)
        "Platform Settings",  # global SaaS settings (system-level)
        # System integrations (system-level, not per company)
        "Integration",
        "Email Gateway",
        "SMS Gateway",
        "Storage Connection",
    ],

    "Data Management": [
        "Data Import",
        "Data Import Log",
        "Import Template",
        "Import Job",
        "Export Job",
    ],

    # ───────── Education
    "Education": [
        "Student",
        "Guardian",
        "Instructor",
        "Student Group",
        "Student Category",

        "Program",
        "Course",
        "Subject",
        "Class",

        "Academic Year",
        "Academic Term",
        "Batch",
        "Program Progression Rule",
        "Education Settings",

        "Program Enrollment",
        "Course Enrollment",

        "School Session",
        "Time Slot",
        "Classroom",
        "Course Assignment",
        "Course Schedule Slot",

        "Student Attendance",
        "Student Attendance Row",
    ],

    # ───────── Exams
    "Exams": [
        "Grading Scale",
        "Grading Scale Breakpoint",

        "Assessment Scheme",
        "Assessment Component",
        "Assessment Component Rule",

        "Assessment Event",
        "Assessment Mark",
        "Assessment Criterion",
        "Assessment Mark Item",

        "Student Course Grade",
        "Student Annual Result",
        "Student Result Hold",
        "Grade Recalc Job",
    ],

    # ───────── Fees
    "Fees": [
        "Fee Category",
        "Fee Structure",
        "Fee Structure Component",
        "Fee Schedule",
        "Fee Schedule Component",
        "Student Fee Adjustment",
        "Fees",
        "Fee Payment",
    ],


    # ───────── Selling (returns handled inside Sales Invoice via is_return/return_against)
    "Selling": [
        "Party",
        "Customer",          # optional UI view over Party
        "Sales Quotation",
        "Sales Invoice",
    ],

    # ───────── Buying (NO Purchase Order, NO Purchase Return)
    "Buying": [
        "Supplier",          # optional UI view over Party
        "Purchase Quotation",
        "Purchase Receipt",
        "Purchase Invoice",
    ],

    "Inventory": [
        "Item Group",
        "Item",
        "Brand",
        "UOM",
        "UOM Conversion",
        "Price List",
        "Item Price",
    ],

    "Stock": [
        "Document Type",
        "Warehouse",
        "Bin",
        "Stock Entry",
        "Stock Reconciliation",
        "Landed Cost Voucher",
        "Stock Ledger Entry",
    ],

    "Accounts": [
        "Chart of Accounts", "Account", "Cost Center", "General Ledger Entry",
        "Journal Entry", "Bank Account", "Mode of Payment", "Payment Entry",
        "Payment Terms", "Expense Claim", "Fiscal Year", "Accounts Settings"
    ],

    "HR": [
        "Employee",
        "Employment Type",
        "Department",
        "Shift Type",
        "Shift Assignment",
        "Holiday List",
        "Holiday",
        "Leave Type",
        "Leave Application",
        "Employee Checkin",
        "Attendance",
        "Salary Structure",
        "Payroll Period",
        "Employee Salary Assignment",
        "Salary Slip",
        "Biometric Device",
    ],

    "Communication": [
        "Notification",
        "SMS",
        # Gateways are managed in Platform (System Admin only)
    ],

    "Reporting": [
        # Education Reports
        "Fee Collection Report",
        "Student Ledger Report",
        "Student Attendance Report",
        "Student Performance Report",
        "Exam Results Report",
        "Teacher Load Report",
        "Class Timetable Report",

        # Financial Reports
        "Aging Report",
        "Accounts Receivable Report",
        "Accounts Receivable Summary Report",
        "Accounts Payable Report",
        "Accounts Payable Summary Report",
        "General Ledger Report",
        "Trial Balance Report",
        "Balance Sheet Report",
        "Profit and Loss Report",
        "Cash Flow Report",
        "Gross Profit Report",

        # Stock Reports
        "Total Stock Summary Report",
        "Stock Balance Report",
        "Stock Ledger Report",
        "Stock Ageing Report",

        # HR Reports
        "Payroll Register",
        "Employee Leave Balance",
        "Attendance Sheet",
    ],

}

# ─────────────────────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────────────────────
DEFAULT_ROLES = [
    {"name": "System Admin", "scope": "SYSTEM",  "description": "Platform owner. Full access across all tenants."},
    {"name": "Super Admin",  "scope": "COMPANY", "description": "Tenant owner. Full access within the company."},

    # Company HQ Roles
    {"name": "Education Manager",  "scope": "COMPANY", "description": "Academic Head: Curricula, Fees setup, and Enrolment rules."},
    {"name": "HR Manager",         "scope": "COMPANY", "description": "Central HR: Payroll, Staffing, and Leave management."},
    {"name": "Finance Manager", "scope": "COMPANY",
     "description": "Finance Head: Accounting, Billing, Payments, and Financial Reporting."},
    {"name": "Operations Manager", "scope": "COMPANY", "description": "Supply Chain Head: Buying, Stock, and Inventory strategy."},
    {"name": "Fees Manager", "scope": "COMPANY",
     "description": "Fees Head: Fee structures, schedules, and fee policy."},
    # Branch Level Roles
    {"name": "Branch Manager",     "scope": "BRANCH", "description": "Principal/Manager: Oversight of branch operations."},
    {"name": "Branch Accountant",  "scope": "BRANCH", "description": "Branch Finance: Billing, Fee collection, and Petty cash."},
    {"name": "Teacher",            "scope": "BRANCH", "description": "Academic Staff: Attendance and Assessment entry."},
    {"name": "Student",            "scope": "BRANCH", "description": "Portal user: Access to own grades, fees, and attendance."},
    {"name": "Guardian",           "scope": "BRANCH", "description": "Portal user: Access to wards' data."},

    # Staff / Functional Roles
    {"name": "Sales User",         "scope": "BRANCH", "description": "Branch Front-desk: Invoicing and Fee collection."},
    {"name": "Buying User",        "scope": "BRANCH", "description": "Procurement Staff: Buying and Supplier payments."},
    {"name": "Inventory User",     "scope": "BRANCH", "description": "Warehouse Staff: Stock movements and Lookups."},
]

# ─────────────────────────────────────────────────────────────
# Role → Permissions
# NOTES:
# - Keep gateway MANAGE restricted to System Admin.
# - Avoid MANAGE on branch transactional docs (prevents DELETE).
# - Scope (SYSTEM/COMPANY/BRANCH) enforced by service layer.
# ─────────────────────────────────────────────────────────────
ROLE_PERMISSION_MAP: Dict[str, List[str]] = {
    # ───────── SYSTEM
    "System Admin": [
        f"{WILDCARD_DOCTYPE_NAME}:{WILDCARD_ACTION_NAME}",

        # Explicit (future-proof) grants for admin modules:
        "Organization:MANAGE",
        "Branch:MANAGE",

        # Platform
        "Tenant:MANAGE",
        "Subscription Plan:MANAGE",
        "Platform Settings:MANAGE",
        "Integration:MANAGE",
        "Email Gateway:MANAGE",
        "SMS Gateway:MANAGE",
        "Storage Connection:MANAGE",

        # Data Management (only System Admin)
        "Data Import:MANAGE", "Data Import:IMPORT", "Data Import:EXPORT",
        "Data Import Log:MANAGE", "Data Import Log:EXPORT",
        "Import Template:MANAGE", "Import Template:IMPORT", "Import Template:EXPORT",
        "Import Job:MANAGE", "Import Job:IMPORT", "Import Job:EXPORT",
        "Export Job:MANAGE", "Export Job:EXPORT",
    ],

    # ───────── COMPANY OWNER
    "Super Admin": [
        f"{WILDCARD_DOCTYPE_NAME}:{WILDCARD_ACTION_NAME}",
    ],

    # ───────── COMPANY DOMAIN ROLES
    "Education Manager": [
        # Student & Guardian Management
        "Student:MANAGE",
        "Guardian:MANAGE",
        "Instructor:MANAGE",
        "Student Group:MANAGE",
        "Student Category:MANAGE",

        # Academic Structure
        "Program:MANAGE",
        "Course:MANAGE",
        "Subject:MANAGE",
        "Class:MANAGE",
        "Academic Year:MANAGE",
        "Academic Term:MANAGE",
        "Batch:MANAGE",
        "Program Progression Rule:MANAGE",
        "Education Settings:MANAGE",

        # Enrollment
        "Program Enrollment:MANAGE",
        "Course Enrollment:MANAGE",
        # Timetable & Scheduling
        "School Session:MANAGE",
        "Time Slot:MANAGE",
        "Classroom:MANAGE",
        "Course Assignment:MANAGE",
        "Course Schedule Slot:MANAGE",

        # Attendance
        "Student Attendance:MANAGE",
        "Student Attendance Row:MANAGE",
        # Exams Management
        "Grading Scale:MANAGE",
        "Grading Scale Breakpoint:MANAGE",
        "Assessment Scheme:MANAGE",
        "Assessment Component:MANAGE",
        "Assessment Component Rule:MANAGE",
        "Assessment Event:MANAGE",
        "Assessment Mark:MANAGE",
        "Assessment Criterion:MANAGE",
        "Assessment Mark Item:MANAGE",
        "Student Course Grade:MANAGE",
        "Student Annual Result:MANAGE",
        "Student Result Hold:MANAGE",
        "Grade Recalc Job:MANAGE",

        # Fees Setup (Structure only)
        "Fee Category:MANAGE",
        "Fee Structure:MANAGE",
        "Fee Structure Component:MANAGE",
        "Fee Schedule:MANAGE",
        "Fee Schedule Component:MANAGE",
        "Student Fee Adjustment:MANAGE",

        # Education Reports
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
        "Student Attendance Report:READ",
        "Student Performance Report:READ",
        "Exam Results Report:READ",
        "Teacher Load Report:READ",
        "Class Timetable Report:READ",
    ],

    "Fees Manager": [
        # Fees Setup (COMPANY LEVEL - Structure only)
        "Fee Category:MANAGE",
        "Fee Structure:MANAGE",
        "Fee Structure Component:MANAGE",
        "Fee Schedule:MANAGE",
        "Fee Schedule Component:MANAGE",
        "Student Fee Adjustment:MANAGE",

        # Fee Reports
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
    ],

    "Exam Manager": [
        "Grading Scale:MANAGE", "Grading Scale Breakpoint:MANAGE",

        "Assessment Scheme:MANAGE",
        "Assessment Component:MANAGE",
        "Assessment Component Rule:MANAGE",

        "Assessment Event:MANAGE",
        "Assessment Mark:MANAGE",
        "Assessment Criterion:MANAGE",
        "Assessment Mark Item:MANAGE",

        "Student Course Grade:MANAGE",
        "Student Annual Result:MANAGE",
        "Student Result Hold:MANAGE",
        "Grade Recalc Job:MANAGE",

        # Context reads
        "Program:READ", "Course:READ",
        "Academic Year:READ", "Academic Term:READ",
        "Student Group:READ", "Student:READ", "Instructor:READ",
    ],

    "HR Manager": [
        "Employee:MANAGE",
        "Employment Type:MANAGE",
        "Department:MANAGE",
        "Designation:MANAGE",

        "Shift Type:MANAGE",
        "Shift Assignment:MANAGE",

        "Holiday List:MANAGE",
        "Holiday:MANAGE",

        "Leave Type:MANAGE",
        "Leave Application:MANAGE",

        "Employee Checkin:READ",
        "Attendance:MANAGE",

        "Salary Structure:MANAGE",
        "Payroll Period:MANAGE",
        "Employee Salary Assignment:MANAGE",
        "Salary Slip:MANAGE",
        "Salary Slip:SUBMIT",
        "Salary Slip:PRINT",

        "Biometric Device:MANAGE",

        "User:READ",

        # HR Reports
        "Payroll Register:READ",
        "Employee Leave Balance:READ",
        "Attendance Sheet:READ",
    ],

    "Finance Manager": [
        # Accounts Setup
        "Chart of Accounts:MANAGE",
        "Account:MANAGE",
        "Cost Center:MANAGE",
        "Fiscal Year:MANAGE",
        "Accounts Settings:MANAGE",

        # Banking & Payments
        "Bank Account:MANAGE",
        "Mode of Payment:MANAGE",
        "Payment Terms:MANAGE",
        "Period Closing Voucher:MANAGE",

        # Core Financial Transactions
        "Journal Entry:MANAGE",
        "Journal Entry:SUBMIT",
        "Journal Entry:POST",
        "Payment Entry:MANAGE",
        "Payment Entry:SUBMIT",
        "Payment Entry:PRINT",
        "Expense Claim:MANAGE",
        "Expense Claim:SUBMIT",

        # Ledger & Shareholders
        "General Ledger Entry:READ",
        "Shareholder:MANAGE",
        "Share Type:MANAGE",
        "Share Ledger Entry:MANAGE",

        # Billing & Collections Oversight
        "Party:MANAGE",
        "Customer:READ",
        "Supplier:READ",
        "Sales Invoice:MANAGE",
        "Sales Invoice:SUBMIT",
        "Sales Invoice:PRINT",
        "Purchase Invoice:MANAGE",
        "Purchase Invoice:SUBMIT",

        # Fees Oversight (Financial aspects only)
        "Fee Category:READ",
        "Fee Structure:READ",
        "Fee Schedule:READ",
        "Fees:READ",
        "Fees:PRINT",
        "Fee Payment:READ",

        # Financial Reports (All)
        "General Ledger Report:READ",
        "Trial Balance Report:READ",
        "Balance Sheet Report:READ",
        "Profit and Loss Report:READ",
        "Cash Flow Report:READ",
        "Gross Profit Report:READ",
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Accounts Payable Report:READ",
        "Accounts Payable Summary Report:READ",
        "Aging Report:READ",
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
    ],

    "Inventory Manager": [
        # Masters
        "Item Group:MANAGE",
        "Item:MANAGE",
        "Brand:MANAGE",
        "UOM:MANAGE",
        "UOM Conversion:MANAGE",
        "Price List:MANAGE",
        "Item Price:MANAGE",

        # Warehouses / stock setup
        "Warehouse:MANAGE",
        "Document Type:MANAGE",
        "Bin:MANAGE",

        # Oversight on stock movements (read)
        "Stock Entry:READ",
        "Stock Reconciliation:READ",
        "Landed Cost Voucher:READ",
        "Stock Ledger Entry:READ",

        # Reports
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
    ],


    "Operations Manager": [
        # Party & Supplier Management
        "Party:MANAGE",
        "Customer:READ",
        "Supplier:READ",

        # Sales Operations
        "Sales Quotation:MANAGE",
        "Sales Invoice:MANAGE",
        "Sales Invoice:SUBMIT",
        "Sales Invoice:PRINT",

        # Purchase Operations
        "Purchase Quotation:MANAGE",
        "Purchase Receipt:MANAGE",
        "Purchase Receipt:SUBMIT",
        "Purchase Invoice:MANAGE",
        "Purchase Invoice:SUBMIT",

        # Inventory Management
        "Item Group:MANAGE",
        "Item:MANAGE",
        "Brand:MANAGE",
        "UOM:MANAGE",
        "UOM Conversion:MANAGE",
        "Price List:MANAGE",
        "Item Price:MANAGE",

        # Stock Management
        "Warehouse:MANAGE",
        "Bin:MANAGE",
        "Document Type:MANAGE",
        "Stock Entry:MANAGE",
        "Stock Entry:SUBMIT",
        "Stock Reconciliation:MANAGE",
        "Stock Reconciliation:SUBMIT",
        "Landed Cost Voucher:MANAGE",

        # Stock Reports
        "Stock Ledger Entry:READ",
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
        "Stock Ageing Report:READ",

        # Financial Reports (Operational view)
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Accounts Payable Report:READ",
        "Accounts Payable Summary Report:READ",
        "Aging Report:READ",
        "Gross Profit Report:READ",
    ],

    # ───────── BRANCH ROLES (avoid MANAGE on sensitive docs where you don't want DELETE)
    "Branch Manager": [
        # Student Management
        "Student:MANAGE",
        "Guardian:MANAGE",
        "Student Group:MANAGE",
        # Enrollment (MANAGE to handle admissions)
        "Program Enrollment:MANAGE",
        "Course Enrollment:MANAGE",

        # Academic Operations
        "Course Assignment:MANAGE",
        "Course Schedule Slot:MANAGE",
        "School Session:READ",
        "Time Slot:READ",
        "Classroom:READ",
        "Instructor:READ",
        "Class:READ",
        "Academic Year:READ",
        "Academic Term:READ",
        "Batch:READ",

        # Attendance
        "Student Attendance:MANAGE",
        "Student Attendance Row:MANAGE",

        # Exams (Limited access)
        "Assessment Event:MANAGE",
        "Assessment Mark:MANAGE",

        "Student Course Grade:MANAGE",
        "Student Annual Result:MANAGE",

        # Fees (MANAGE for fee collection)
        "Fee Schedule:READ",
        "Fees:MANAGE",
        "Fees:SUBMIT",
        "Fees:PRINT",
        "Fee Payment:MANAGE",
        "Fee Payment:SUBMIT",
        "Fee Payment:PRINT",

        # Billing & Collections (MANAGE for handling payments)
        "Party:MANAGE",  # Can create customers
        "Customer:READ",
        "Sales Invoice:MANAGE",
        "Sales Invoice:SUBMIT",
        "Sales Invoice:PRINT",
        "Payment Entry:MANAGE",
        "Payment Entry:SUBMIT",
        "Payment Entry:PRINT",

        # Basic Accounting (for backup when accountant is missing)
        "Journal Entry:CREATE",
        "Journal Entry:READ",
        "Journal Entry:UPDATE",
        "Journal Entry:SUBMIT",
        "Expense Claim:CREATE",
        "Expense Claim:READ",
        "Expense Claim:UPDATE",
        "Expense Claim:SUBMIT",
        "Bank Account:READ",
        "Mode of Payment:READ",

        # Staff Management
        "Employee:READ",
        "Attendance:READ",

        # Communication
        "Notification:MANAGE",
        "SMS:MANAGE",

        # Stock Visibility
        "Item:READ",
        "Warehouse:READ",
        "Stock Ledger Entry:READ",

        # Branch Reports
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
        "Student Attendance Report:READ",
        "Student Performance Report:READ",
        "Accounts Receivable Report:READ",
        "Aging Report:READ",
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
    ],
    "Assistant Branch Manager": [
        # Education daily ops
        "Student:MANAGE",
        "Guardian:MANAGE",
        "Student Group:MANAGE",
        "Program Enrollment:MANAGE",
        "Course Enrollment:MANAGE",
        "Student Category:MANAGE",
        "Education Settings:READ",

        "Instructor:READ", "Classroom:READ",
        # Exams backup (DO NOT use MANAGE if you want to prevent DELETE; use explicit)
        "Assessment Event:READ",
        "Assessment Mark:CREATE", "Assessment Mark:READ", "Assessment Mark:UPDATE",
        "Assessment Mark Item:CREATE", "Assessment Mark Item:READ", "Assessment Mark Item:UPDATE",
        "Student Course Grade:READ",
        "Student Annual Result:READ",


        # Read-only finance visibility
        "Fee Schedule:READ",
        "Fees:READ", "Fees:PRINT",
        "Sales Invoice:READ", "Sales Invoice:PRINT",

        # Reports
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
        # Reports - Full Branch Oversight
        "Teacher Load Report:READ",
        "Class Timetable Report:READ",
        "Student Ledger Report:READ",
    ],

    "Branch Accountant": [
        # Student & Party Access
        "Student:MANAGE",
        "Guardian:READ",
        "Party:MANAGE",  # Can create/update parties
        "Customer:READ",

        # Billing (Sales & Fees) - FULL CONTROL
        "Sales Invoice:MANAGE",
        "Sales Invoice:SUBMIT",
        "Sales Invoice:PRINT",
        "Sales Quotation:MANAGE",


        # Fees Management - FULL CONTROL
        "Fee Schedule:READ",
        "Student Fee Adjustment:READ",
        "Fees:MANAGE",
        "Fees:SUBMIT",
        "Fees:PRINT",
        "Fee Payment:MANAGE",
        "Fee Payment:SUBMIT",
        "Fee Payment:PRINT",

        # Payments & Receipts - FULL CONTROL
        "Payment Entry:MANAGE",
        "Payment Entry:SUBMIT",
        "Payment Entry:PRINT",
        "Mode of Payment:READ",
        "Bank Account:READ",

        # Expense Management
        "Expense Claim:MANAGE",
        "Expense Claim:SUBMIT",
        "Journal Entry:MANAGE",
        "Journal Entry:SUBMIT",
        # Accounting Basics
        "Chart of Accounts:READ",
        "Account:READ",
        "Cost Center:READ",
        "General Ledger Entry:READ",
        "Period Closing Voucher:READ",
        # Financial Reports (Branch level)
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Aging Report:READ",
        "General Ledger Report:READ",
        "Trial Balance Report:READ",
    ],

    "Teacher": [
        # Academic Context
        "Instructor:READ",
        "Student:READ",
        "Student Group:READ",
        "Program:READ",
        "Course:READ",
        "Academic Year:READ",
        "Academic Term:READ",
        "Course Enrollment:READ",

        # Timetable
        "Classroom:READ",
        "School Session:READ",
        "Time Slot:READ",
        "Course Assignment:READ",
        "Course Schedule Slot:READ",

        # Attendance Entry - CREATE, READ, UPDATE, SUBMIT (but not DELETE)
        "Student Attendance:CREATE",
        "Student Attendance:READ",
        "Student Attendance:UPDATE",
        "Student Attendance:SUBMIT",
        "Student Attendance Row:CREATE",
        "Student Attendance Row:READ",
        "Student Attendance Row:UPDATE",
        "Student Attendance Row:SUBMIT",

        # Assessment Entry - CREATE, READ, UPDATE, SUBMIT (but not DELETE)
        "Assessment Event:READ",
        "Assessment Mark:CREATE",
        "Assessment Mark:READ",
        "Assessment Mark:UPDATE",
        "Assessment Mark:SUBMIT",
        "Assessment Mark Item:CREATE",
        "Assessment Mark Item:READ",
        "Assessment Mark Item:UPDATE",
        "Assessment Mark Item:SUBMIT",
        "Student Course Grade:READ",
        "Student Annual Result:READ",

        # Self-Service
        "Attendance:READ",
        "Leave Application:CREATE",
        "Leave Application:READ",
        "Leave Application:UPDATE",
        "Leave Application:SUBMIT",
        "Salary Slip:READ",

        # Communication
        "Notification:READ",
    ],

    "Student": [
        "Student:READ",
        "Guardian:READ",
        "Program Enrollment:READ",
        "Course Enrollment:READ",
        "Student Group:READ",
        "Course Schedule Slot:READ",
        "Student Attendance:READ",
        "Student Attendance Row:READ",
        "Assessment Mark:READ",
        "Student Course Grade:READ",
        "Student Annual Result:READ",
        "Fees:READ",
        "Fees:PRINT",
        "Fee Payment:READ",
        "Sales Invoice:READ",
        "Sales Invoice:PRINT",
        "Payment Entry:READ",
        "Notification:READ",
    ],

    "Guardian": [
        "Student:READ",
        "Program Enrollment:READ",
        "Course Enrollment:READ",
        "Student Group:READ",
        "Course Schedule Slot:READ",
        "Student Attendance:READ",
        "Student Attendance Row:READ",
        "Assessment Mark:READ",
        "Student Course Grade:READ",
        "Student Annual Result:READ",
        "Fees:READ",
        "Fees:PRINT",
        "Fee Payment:READ",
        "Sales Invoice:READ",
        "Sales Invoice:PRINT",
        "Payment Entry:READ",
        "Notification:READ",
    ],

    # ───────── ERP branch ops roles (explicit actions to avoid DELETE)
    "Sales User": [
        # Party & Customer Management
        "Party:CREATE",
        "Party:READ",
        "Party:UPDATE",
        "Customer:READ",
        "Student:READ",  # Important: To select students as customers

        # Sales Operations
        "Sales Quotation:CREATE",
        "Sales Quotation:READ",
        "Sales Quotation:UPDATE",
        "Sales Invoice:CREATE",
        "Sales Invoice:READ",
        "Sales Invoice:UPDATE",
        "Sales Invoice:SUBMIT",
        "Sales Invoice:PRINT",

        # Fees Management (for student billing)
        "Fee Schedule:READ",
        "Fees:CREATE",
        "Fees:READ",
        "Fees:UPDATE",
        "Fees:SUBMIT",
        "Fees:PRINT",
        "Fee Payment:CREATE",
        "Fee Payment:READ",
        "Fee Payment:UPDATE",
        "Fee Payment:SUBMIT",
        "Fee Payment:PRINT",

        # Payments Collection (CRITICAL)
        "Payment Entry:CREATE",
        "Payment Entry:READ",
        "Payment Entry:UPDATE",
        "Payment Entry:SUBMIT",
        "Payment Entry:PRINT",
        "Mode of Payment:READ",
        "Bank Account:READ",

        # Product/Service Lookup
        "Item:READ",
        "Item Price:READ",
        "UOM:READ",
        # reports
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Fee Collection Report:READ",
        "Student Ledger Report:READ",

        "Gross Profit Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",

    ],

    "Buying User": [
        # Supplier Management
        "Party:CREATE",
        "Party:READ",
        "Party:UPDATE",
        "Supplier:READ",

        # Purchase Operations
        "Purchase Quotation:CREATE",
        "Purchase Quotation:READ",
        "Purchase Quotation:UPDATE",
        "Purchase Receipt:CREATE",
        "Purchase Receipt:READ",
        "Purchase Receipt:UPDATE",
        "Purchase Receipt:SUBMIT",
        "Purchase Invoice:CREATE",
        "Purchase Invoice:READ",
        "Purchase Invoice:UPDATE",
        "Purchase Invoice:SUBMIT",

        # Supplier Payments
        "Payment Entry:CREATE",
        "Payment Entry:READ",
        "Payment Entry:UPDATE",
        "Payment Entry:SUBMIT",
        "Payment Entry:PRINT",
        "Bank Account:READ",
        "Mode of Payment:READ",

        # Inventory Lookup
        "Item:READ",
        "UOM:READ",
        "UOM Conversion:READ",
        "Warehouse:READ",
        "Bin:READ",

        # Reports
        "Accounts Payable Report:READ",
        "Accounts Payable Summary Report:READ",
        "Aging Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
        "Total Stock Summary Report:READ",
    ],

    "Inventory User": [
        # Stock Operations
        "Warehouse:READ",
        "Bin:READ",
        "Stock Entry:CREATE",
        "Stock Entry:READ",
        "Stock Entry:UPDATE",
        "Stock Entry:SUBMIT",
        "Stock Reconciliation:CREATE",
        "Stock Reconciliation:READ",
        "Stock Reconciliation:UPDATE",
        "Stock Reconciliation:SUBMIT",
        "Stock Transfer:CREATE",
        "Stock Transfer:READ",
        "Stock Transfer:UPDATE",
        "Stock Transfer:SUBMIT",

        # Item Lookup
        "Item:READ",
        "UOM:READ",
        "Brand:READ",

        # Stock Reports
        "Stock Ledger Entry:READ",
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
    ],


}
