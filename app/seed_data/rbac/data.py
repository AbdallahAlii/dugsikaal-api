# seed_data/rbac/data.py
from app.application_rbac.rbac_models import RoleScopeEnum  # keep import as-is (even if unused)
from typing import Dict, List, Tuple

# --- ERP-Specific Constants ---
WILDCARD_DOCTYPE_NAME = "*"
WILDCARD_ACTION_NAME = "*"

# --- Default Actions (what you can do) ---
# NOTE: MANAGE = CRUD only (Create/Read/Update/Delete).
# Workflow/output actions (SUBMIT, CANCEL, PRINT, etc.) are separate.
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
    ("MANAGE", "CRUD = READ, CREATE, UPDATE, DELETE"),  # expanded to CRUD at seed time
    ("ASSIGN", "Assign roles or permissions"),
    (WILDCARD_ACTION_NAME, "Unrestricted access to all actions within a resource."),
]

# --- DocType Module Names (for grouping) ---
DEFAULT_DOCTYPE_MODULES = [
    "Core",
    "System",
    "Access Control",
    "Accounts",
    "Inventory",
    "Stock",
    "Buying",
    "Sales",
    "CRM",
    "Reporting",
    "Geo",
    "Printing",
    "HR",
    "Parties",
    "Platform",  # System-wide multi-tenant admin console (admin_only workspace will gate it)
    "Data Management",  # Centralized imports/exports & data pipelines
]

# --- DocType Mappings (logical grouping) ---
DEFAULT_DOCTYPE_MAPPINGS: Dict[str, List[str]] = {
    # System & Setup
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

    # Access Control
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

    # Accounts & Finance
    # Single source of truth: "Chart of Accounts" (no separate "Account" doctype)
    "Accounts": [
        "Chart of Accounts",
        "Cost Center",
        "General Ledger Entry",
        "Journal Entry",
        "Bank Account",
        "Mode of Payment",
        "Payment Entry",
        "Payment Terms",
        "Expense Claim",
        "Fiscal Year",
        "Accounts Settings",
    ],

    # Inventory (masters)
    "Inventory": [
        "Item",
        "Brand",
        "UOM",
        "Item Price",
        "UOM Conversion",
    ],

    # Stock (warehouses & movements)
    "Stock": [
        "Warehouse",
        "Bin",
        "Stock Entry",
        "Stock Reconciliation",
        "Landed Cost Voucher",
        "Stock Ledger Entry",
    ],

    # Parties
    "Parties": [
        "Party",
    ],

    # Buying (AP)
    "Buying": [
        "Supplier",
        "Purchase Quotation",
        "Purchase Order",
        "Purchase Receipt",
        "Purchase Invoice",
        "Purchase Return",
    ],

    # Sales (AR)
    "Sales": [
        "Customer",
        "Sales Quotation",
        "Sales Order",
        "Delivery Note",
        "Sales Invoice",
        "Sales Return",
    ],

    # HR (company-managed)
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

    # Reporting (read-only report resources)
    # "General Ledger Report" relies on "General Ledger Entry:READ"
    "Reporting": [
        "General Ledger Report",
        "Trial Balance Report",
        "Balance Sheet Report",
        "Profit and Loss Report",
        "Cash Flow Report",
        "Gross Profit Report",
        "Accounts Receivable Report",
        "Accounts Receivable Summary Report",
        "Accounts Payable Report",
        "Accounts Payable Summary Report",
        "Total Stock Summary Report",
        "Stock Balance Report",
        "Stock Ledger Report",
    ],

    # NEW: Platform (system-wide, modern ERP naming) ─────────────────
    # The single primary object is "Account" (your tenant). Owner/contact lives inside it.
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

    # NEW: Data Management (imports/exports across domains) ─────────
    "Data Management": [
        "Data Import",
        "Data Import Log",
        "Import Template",
        "Import Job",
        "Export Job",
    ],


}

# -------------------------------------------------------------------
# Minimal, ERP-style role set
# Scopes: "SYSTEM" | "COMPANY" | "BRANCH"
# -------------------------------------------------------------------
DEFAULT_ROLES = [
    {"name": "System Admin",        "scope": "SYSTEM",  "description": "Full access to the entire system."},
    {"name": "Super Admin",         "scope": "COMPANY", "description": "Full access within the assigned company."},

    {"name": "Operations Manager",  "scope": "COMPANY", "description": "Oversees sales, buying, and stock operations across all branches."},
    {"name": "Inventory Manager",   "scope": "COMPANY", "description": "Owns inventory masters (Item/UOM/Brand/Price/Conversions) and Warehouses."},
    {"name": "Accounts Manager",    "scope": "COMPANY", "description": "Company-wide finance configuration and approvals."},
    {"name": "HR Manager",          "scope": "COMPANY", "description": "Company-wide HR, leave, attendance, and payroll."},

    {"name": "Sales User",          "scope": "BRANCH",  "description": "Handles sales docs (SO, DN, SI, Returns) and customers for their branch."},
    {"name": "Buying User",         "scope": "BRANCH",  "description": "Handles buying docs (PO, PR, PI, Returns) and suppliers for their branch."},
    {"name": "Inventory User",      "scope": "BRANCH",  "description": "Executes stock operations (stock entries, reconciliations) for their branch."},
    {"name": "Accounts User",       "scope": "BRANCH",  "description": "Daily accounting: journals, payments, expense claims at branch level."},
]

# -------------------------------------------------------------------
# Role → Permission map
# - "*:*" stays a SINGLE Permission row (DocType="*", Action="*")
# - "MANAGE" is expanded to CRUD at seeding (READ/CREATE/UPDATE/DELETE)
# - Workflow/output actions (SUBMIT/CANCEL/PRINT) included only where needed
# - Company vs Branch visibility is enforced by your service layer (scope)
# -------------------------------------------------------------------
ROLE_PERMISSION_MAP: Dict[str, List[str]] = {
    # Global / Company admins
    "System Admin": [
        f"{WILDCARD_DOCTYPE_NAME}:{WILDCARD_ACTION_NAME}",

        # Explicit (future-proof) grants for the new admin modules:
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
        "Import Template:MANAGE", "Import Template:EXPORT", "Import Template:IMPORT",
        "Import Job:MANAGE", "Import Job:EXPORT", "Import Job:IMPORT",
        "Export Job:MANAGE", "Export Job:EXPORT",
    ],

    "Super Admin":  [f"{WILDCARD_DOCTYPE_NAME}:{WILDCARD_ACTION_NAME}"],  # company scope enforced by service layer

    # Company-wide Ops lead (focus on transactions; read masters)
    "Operations Manager": [
        # Parties
        "Party:MANAGE",

        # Sales (transactions)
        "Customer:READ",
        "Sales Quotation:MANAGE",
        "Sales Order:MANAGE",      "Sales Order:SUBMIT",
        "Delivery Note:MANAGE",    "Delivery Note:SUBMIT",
        "Sales Invoice:MANAGE",    "Sales Invoice:SUBMIT", "Sales Invoice:PRINT",
        "Sales Return:MANAGE",     "Sales Return:SUBMIT",

        # Buying (transactions)
        "Supplier:READ",
        "Purchase Quotation:MANAGE",
        "Purchase Order:MANAGE",   "Purchase Order:SUBMIT",
        "Purchase Receipt:MANAGE", "Purchase Receipt:SUBMIT",
        "Purchase Invoice:MANAGE", "Purchase Invoice:SUBMIT",
        "Purchase Return:MANAGE",  "Purchase Return:SUBMIT",

        # Stock (transactions & visibility)
        "Item:READ", "Brand:READ", "UOM:READ", "UOM Conversion:READ", "Item Price:READ",
        "Warehouse:READ", "Bin:READ",
        "Stock Entry:MANAGE",           "Stock Entry:SUBMIT",
        "Stock Reconciliation:MANAGE",  "Stock Reconciliation:SUBMIT",
        "Stock Ledger Entry:READ",
        "Landed Cost Voucher:MANAGE",

        # Ops-focused reports
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Accounts Payable Report:READ",
        "Accounts Payable Summary Report:READ",
        "Gross Profit Report:READ",
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
    ],

    # Company-wide master data owner for Inventory + Warehouses
    "Inventory Manager": [
        # Masters
        "Item:MANAGE", "Brand:MANAGE", "UOM:MANAGE", "UOM Conversion:MANAGE", "Item Price:MANAGE",
        # Warehouses & stock setup
        "Warehouse:MANAGE", "Bin:MANAGE",
        # Oversight on stock movements
        "Stock Entry:READ", "Stock Reconciliation:READ", "Stock Ledger Entry:READ",
        # Stock reports
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",
    ],

    # Company-wide accounting (centralized)
    "Accounts Manager": [
        "Chart of Accounts:MANAGE", "Cost Center:MANAGE",
        "Journal Entry:MANAGE",      "Journal Entry:SUBMIT",
        "General Ledger Entry:READ",
        "Payment Entry:MANAGE",      "Payment Entry:SUBMIT",
        "Mode of Payment:MANAGE", "Bank Account:MANAGE",
        "Payment Terms:MANAGE",
        "Expense Claim:MANAGE",      "Expense Claim:SUBMIT",
        "Fiscal Year:MANAGE",        "Accounts Settings:MANAGE",
        # Optional read on AP/AR invoices for reconciliation
        "Sales Invoice:READ", "Purchase Invoice:READ",
        # Accounting reports (read-only)
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
    ],

    # Company-wide HR (all branches share HR)
    "HR Manager": [
        "Employee:MANAGE", "Employment Type:MANAGE",
        "Department:MANAGE",

        # Time & Attendance
        "Shift Type:MANAGE",
        "Shift Assignment:MANAGE",
        "Holiday List:MANAGE", "Holiday:MANAGE",
        "Employee Checkin:READ",         # checkin logs mainly read-only
        "Attendance:MANAGE",

        # Leave
        "Leave Type:MANAGE",
        "Leave Application:MANAGE",

        # Payroll
        "Salary Structure:MANAGE",
        "Payroll Period:MANAGE",
        "Employee Salary Assignment:MANAGE",
        "Salary Slip:MANAGE", "Salary Slip:PRINT",

        # Devices
        "Biometric Device:MANAGE",
    ],

    # Branch roles (day-to-day ops)
    "Sales User": [
        # Parties (unified Party model)
        "Party:MANAGE",

        # Sales docs
        "Customer:READ",  # UI views; underlying model is Party
        "Sales Quotation:CREATE", "Sales Quotation:READ",
        "Sales Order:CREATE", "Sales Order:READ", "Sales Order:SUBMIT",
        "Delivery Note:CREATE", "Delivery Note:READ", "Delivery Note:SUBMIT",
        "Sales Invoice:CREATE", "Sales Invoice:READ", "Sales Invoice:SUBMIT", "Sales Invoice:PRINT",
        "Sales Return:CREATE", "Sales Return:READ", "Sales Return:SUBMIT",

        # lookups & stock visibility
        "Item:MANAGE",              # can create/edit items
        "Brand:READ", "UOM:READ",
        "Item Price:READ",
        "Warehouse:READ", "Bin:READ",
        "Stock Ledger Entry:READ",

        # stock reports (for selling decisions)
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",

        # branch-focused receivables visibility
        "Accounts Receivable Report:READ",
        "Accounts Receivable Summary Report:READ",
        "Gross Profit Report:READ",
    ],

    "Buying User": [
        # Unified Party model
        "Party:MANAGE",

        # Supplier docs (views over Party)
        "Supplier:READ",

        # Buying docs
        "Purchase Quotation:CREATE", "Purchase Quotation:READ",
        "Purchase Order:CREATE", "Purchase Order:READ", "Purchase Order:SUBMIT",
        "Purchase Receipt:CREATE", "Purchase Receipt:READ", "Purchase Receipt:SUBMIT",
        "Purchase Invoice:CREATE", "Purchase Invoice:READ", "Purchase Invoice:SUBMIT",
        "Purchase Return:CREATE", "Purchase Return:READ", "Purchase Return:SUBMIT",

        # lookups & stock visibility
        "Item:READ",
        "Brand:READ", "UOM:READ", "UOM Conversion:READ",
        "Warehouse:READ", "Bin:READ",
        "Stock Ledger Entry:READ",

        # stock reports (for purchasing decisions)
        "Total Stock Summary Report:READ",
        "Stock Balance Report:READ",
        "Stock Ledger Report:READ",

        # branch-focused payables visibility
        "Accounts Payable Report:READ",
        "Accounts Payable Summary Report:READ",
        "Gross Profit Report:READ",
    ],

    # Branch-level daily finance ops
    "Accounts User": [
        "Journal Entry:CREATE", "Journal Entry:READ", "Journal Entry:SUBMIT",
        "Payment Entry:CREATE", "Payment Entry:READ", "Payment Entry:SUBMIT",
        "Expense Claim:CREATE", "Expense Claim:READ", "Expense Claim:SUBMIT",
        # read-only master/ledger visibility needed at branch
        "Chart of Accounts:READ", "Cost Center:READ", "General Ledger Entry:READ",
        "Mode of Payment:READ", "Bank Account:READ",
        # accounting reports (read-only)
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
        # optional: read/print branch sales invoices (counter support)
        "Sales Invoice:READ", "Sales Invoice:PRINT",
    ],
}
