# seed_data/navigation_workspace/data.py

WORKSPACES: list[dict] = [

    # === SELLING ===
    {
        "slug": "selling",
        "title": "Selling",
        "icon": "shopping-bag",
        "description": "Sales & delivery",
        "order_index": 10,

        # Transactions as root links for quick access
        "root_links": [
            {
              "label": "Customer", "path": "/selling/customer/list", "icon": "user",
                 "perm": "Customer:READ"},
            {"label": "Quotation", "path": "/selling/sales-quotation/list", "icon": "file-badge",
             "perm": "Sales Quotation:READ"},



            {"label": "Delivery Note", "path": "/selling/delivery-note/list", "icon": "truck",
             "perm": "Delivery Note:READ"},
            {"label": "Sales Invoice", "path": "/selling/sales-invoice/list", "icon": "receipt",
             "perm": "Sales Invoice:READ"}

        ],

        "sections": [],
    },

    # === BUYING ===
    {
        "slug": "buying",
        "title": "Buying",
        "icon": "shopping-cart",
        "description": "Procurement & receipts",
        "order_index": 20,

        "root_links": [
            {"label": "Supplier", "path": "/buying/supplier/list", "icon": "user-round",
             "perm": "Supplier:READ"},
            {"label": "Quotation", "path": "/buying/purchase-quotation/list", "icon": "quote",
             "perm": "Purchase Quotation:READ"},

            {"label": "Purchase Receipt", "path": "/buying/purchase-receipt/list", "icon": "package",
             "perm": "Purchase Receipt:READ"},
            {"label": "Purchase Invoice", "path": "/buying/purchase-invoice/list", "icon": "receipt",
             "perm": "Purchase Invoice:READ"},

        ],

        "sections": [],
    },

    # === INVENTORY ===
    {
        "slug": "inventory",
        "title": "Inventory",
        "icon": "boxes",
        "description": "Items, warehouses, stock",
        "order_index": 30,
        "root_links": [
            {"label": "Item", "path": "/inventory/item/list", "icon": "box", "perm": "Item:READ"},
            {"label": "Brand", "path": "/inventory/brand/list", "icon": "badge", "perm": "Brand:READ"},
            {"label": "UOM", "path": "/inventory/uom/list", "icon": "ruler", "perm": "UOM:READ"},
            # ✅ Singular, matches DocType + RBAC
            {"label": "UOM Conversion", "path": "/inventory/uom-conversion/list", "icon": "sync",
             "perm": "UOM Conversion:READ"},
            {"label": "Item Price", "path": "/inventory/item-price/list", "icon": "tag", "perm": "Item Price:READ"},
        ],
    },

    # === STOCK ===
    {
        "slug": "stock",
        "title": "Stock",
        "icon": "archive",
        "description": "Stock management",
        "order_index": 35,
        "root_links": [
            {"label": "Stock Entry", "path": "/stock/stock-entry/list", "icon": "arrows-left-right",
             "perm": "Stock Entry:READ"},
            {"label": "Stock Reconciliation", "path": "/stock/stock-reconciliation/list", "icon": "scale",
             "perm": "Stock Reconciliation:READ"},
            {"label": "Bin", "path": "/stock/bin/list", "icon": "cubes", "perm": "Bin:READ"},
            {"label": "Warehouse", "path": "/stock/warehouse/list", "icon": "warehouse", "perm": "Warehouse:READ"},
        ],
    },

    # === ACCOUNTS ===
    {
        "slug": "accounting",
        "title": "Accounting",
        "icon": "banknote",
        "description": "Finance, accounting & reports",
        "order_index": 40,
        "root_links": [
            {"label": "Chart of Accounts", "path": "/accounts/chart-of-accounts/list", "icon": "tree-pine",
             "perm": "Chart of Accounts:READ"},
            {"label": "Cost Center", "path": "/accounts/cost-center/list", "icon": "layout-grid",
             "perm": "Cost Center:READ"},
            {"label": "Bank Account", "path": "/accounts/bank-account/list", "icon": "credit-card",
             "perm": "Bank Account:READ"},
            {"label": "Mode of Payment", "path": "/accounts/mode-of-payment/list", "icon": "wallet",
             "perm": "Mode of Payment:READ"},
            {"label": "Payment Terms", "path": "/accounts/payment-terms/list", "icon": "list-checks",
             "perm": "Payment Terms:READ"},
            {"label": "Fiscal Year", "path": "/accounts/fiscal-year/list", "icon": "calendar",
             "perm": "Fiscal Year:READ"},
        ],
        "sections": [
            {
                "label": "Transactions",
                "order_index": 20,
                "links": [
                    {"label": "Journal Entry", "path": "/accounts/journal-entry/list", "icon": "book-open",
                     "perm": "Journal Entry:READ"},
                    {"label": "Payment Entry", "path": "/accounts/payment-entry/list", "icon": "wallet",
                     "perm": "Payment Entry:READ"},
                    {"label": "Expense Claim", "path": "/accounts/expense-claim/list", "icon": "receipt",
                     "perm": "Expense Claim:READ"},
                ],
            },
        ],
    },

    # === REPORTS ===
    {
        "slug": "reports",
        "title": "Reports",
        "icon": "trending-up",
        "description": "Financial statements & reports",
        "order_index": 45,
        "root_links": [
            # ✅ Matches RBAC: "General Ledger Report" doc with READ
            {"label": "General Ledger", "path": "/accounts/report/gl", "icon": "book-marked",
             "perm": "General Ledger Report:READ"},
            {"label": "Trial Balance", "path": "/accounts/report/trial-balance", "icon": "scale",
             "perm": "Trial Balance Report:READ"},
            {"label": "Balance Sheet", "path": "/accounts/report/balance-sheet", "icon": "landmark",
             "perm": "Balance Sheet Report:READ"},
            {"label": "Profit and Loss", "path": "/accounts/report/profit-and-loss", "icon": "trending-up",
             "perm": "Profit and Loss Report:READ"},
            {"label": "Cash Flow Statement", "path": "/accounts/report/cash-flow", "icon": "activity",
             "perm": "Cash Flow Report:READ"},
            {"label": "Gross Profit", "path": "/accounts/report/gross-profit", "icon": "percent",
             "perm": "Gross Profit Report:READ"},
            {"label": "Accounts Receivable", "path": "/accounts/report/accounts-receivable", "icon": "user-plus",
             "perm": "Accounts Receivable Report:READ"},
            {"label": "Accounts Payable", "path": "/accounts/report/accounts-payable", "icon": "user-minus",
             "perm": "Accounts Payable Report:READ"},
        ],
        "sections": [],
    },

    # === PARTIES ===
    # {
    #     "slug": "parties",
    #     "title": "Parties",
    #     "icon": "users",
    #     "description": "Shared customers/suppliers/partners",
    #     "order_index": 50,
    #     "root_links": [
    #         {"label": "Party", "path": "/parties/party/list", "icon": "users", "perm": "Party:READ"},
    #     ],
    #     "sections": [],
    # },

    # === HR ===
    {
        "slug": "hr",
        "title": "HR",
        "icon": "id-card",
        "description": "People & payroll",
        "order_index": 60,
        "root_links": [
            {"label": "Employee", "path": "/hr/employee/list", "icon": "user-round", "perm": "Employee:READ"},
            # Branch lives in System module but useful shortcut here
            {"label": "Branch", "path": "/hr/branch/list", "icon": "git-fork", "perm": "Branch:READ"},
            {"label": "Department", "path": "/hr/department/list", "icon": "building-2", "perm": "Department:READ"},
        ],
        "sections": [
            {
                "label": "Masters",
                "order_index": 10,
                "links": [
                    {"label": "Shift Type", "path": "/hr/shift-type/list", "icon": "clock",
                     "perm": "Shift Type:READ"},
                    {"label": "Holiday List", "path": "/hr/holiday-list/list", "icon": "calendar-range",
                     "perm": "Holiday List:READ"},
                    {"label": "Leave Type", "path": "/hr/leave-type/list", "icon": "ticket",
                     "perm": "Leave Type:READ"},
                ],
            },
            {
                "label": "Operations",
                "order_index": 20,
                "links": [
                    {"label": "Shift Assignment", "path": "/hr/shift-assignment/list", "icon": "calendar-plus",
                     "perm": "Shift Assignment:READ"},
                    {"label": "Staff Attendance", "path": "/hr/staff-attendance/list", "icon": "calendar-check-2",
                     "perm": "Staff Attendance:READ"},
                    {"label": "Leave Application", "path": "/hr/leave-application/list", "icon": "file-pen",
                     "perm": "Leave Application:READ"},
                ],
            },
            {
                "label": "Payroll",
                "order_index": 30,
                "links": [
                    {"label": "Salary Structure", "path": "/hr/salary-structure/list", "icon": "file-cog",
                     "perm": "Salary Structure:READ"},
                    {"label": "Payroll Entry", "path": "/hr/payroll-entry/list", "icon": "file-dollar-sign",
                     "perm": "Payroll Entry:READ"},
                    {"label": "Salary Slip", "path": "/hr/salary-slip/list", "icon": "file-text",
                     "perm": "Salary Slip:READ"},
                ],
            },
        ],
    },

    # === SYSTEM ===
    # {
    #     "slug": "system",
    #     "title": "System",
    #     "icon": "settings",
    #     "description": "Company setup & system configuration",
    #     "order_index": 90,
    #     "root_links": [
    #         {"label": "Organization", "path": "/system/organization/list", "icon": "building",
    #          "perm": "Organization:READ"},
    #         {"label": "Branch", "path": "/system/branch/list", "icon": "git-branch", "perm": "Branch:READ"},
    #         {"label": "System Settings", "path": "/system/system-settings/list", "icon": "settings-2",
    #          "perm": "System Settings:READ"},
    #     ],
    #     "sections": [],
    # },

    # === PLATFORM HOST ADMIN (SYSTEM ADMIN ONLY) ===
    {
        "slug": "platform-admin",
        "title": "Platform Host Admin",
        "icon": "server-cog",
        "description": "Multi-tenant/client provisioning, subscriptions, and host-level integrations.",
        "order_index": 92,  # ← placed between System (90) and Access Control (95)
        "admin_only": True,  # critical: restricted to System Admin at nav layer
        "root_links": [
            {"label": "Tenants (SaaS Accounts)", "path": "/platform-admin/tenant/list", "icon": "building-2",
             "perm": "Tenant:READ"},
            {"label": "Organizations (Client Co.)", "path": "/platform-admin/organization/list", "icon": "building",
             "perm": "Organization:READ"},
            {"label": "Branches (Client Locations)", "path": "/platform-admin/branch/list", "icon": "git-branch",
             "perm": "Branch:READ"},
            {"label": "Subscription Plans", "path": "/platform-admin/subscription-plan/list", "icon": "dollar-sign",
             "perm": "Subscription Plan:READ"},
        ],
        "sections": [
            {
                "label": "Host Configuration",
                "order_index": 10,
                "links": [
                    {"label": "Platform Settings", "path": "/platform-admin/platform-settings/form",
                     "icon": "settings-2",
                     "perm": "Platform Settings:READ"},
                    {"label": "Integration Registry", "path": "/platform-admin/integration/list", "icon": "plug-zap",
                     "perm": "Integration:READ"},
                ],
            },
            {
                "label": "Gateways",
                "order_index": 20,
                "links": [
                    {"label": "Email Gateway", "path": "/platform-admin/email-gateway/list", "icon": "mail",
                     "perm": "Email Gateway:READ"},
                    {"label": "SMS Gateway", "path": "/platform-admin/sms-gateway/list", "icon": "message-square-text",
                     "perm": "SMS Gateway:READ"},
                    {"label": "Storage Connection", "path": "/platform-admin/storage-connection/list", "icon": "cloud",
                     "perm": "Storage Connection:READ"},
                ],
            },

        ],
    },

    # === DATA MANAGEMENT (SYSTEM ADMIN ONLY) ===
    {
        "slug": "data",
        "title": "Data Management",
        "icon": "hard-drive",
        "description": "Import templates and import jobs across domains",
        "order_index": 93,  # just after Platform Admin, before Access Control
        "admin_only": True,  # restrict initial visibility; can relax later
        "root_links": [
            {"label": "Import Templates", "path": "/data/import-template/list", "icon": "file-spreadsheet",
             "perm": "Import Template:READ"},
            {"label": "Import Jobs", "path": "/data/import-job/list", "icon": "upload",
             "perm": "Import Job:READ"},
            {"label": "Export Jobs", "path": "/data/export-job/list", "icon": "download",
             "perm": "Export Job:READ"},
        ],
        "sections": [],

    },
    {
        "slug": "doctype-directory",
        "title": "DocTypes",
        "icon": "files",  # any lucide name you already use
        "description": "Browse all document types and entry points",
        "order_index": 94,  # place it where you want in the menu
        "admin_only": False,  # set True if only System Admin must see the module
        "root_links": [
            {
                "label": "Open Directory",
                "path": "/system/doctype-directory",
                "icon": "files",
                # Permission that gates the module (choose one):
                # Show to anyone who can READ any doctype:
                "perm": "DocType:READ",
                # OR use a custom, narrow permission you assign to select roles:
                # "perm": "Directory:VIEW",
            },
        ],
        "sections": [],
    },
    # === ACCESS CONTROL ===
    {
        "slug": "access-control",
        "title": "Access Control",
        "icon": "shield-check",
        "description": "Users, roles & permissions",
        "order_index": 95,

        "root_links": [
            {"label": "User", "path": "/system/user/list", "icon": "user", "perm": "User:READ"},
        ],

        "sections": [
            {
                "label": "Roles & Permissions",
                "order_index": 20,
                "links": [
                    {"label": "Role", "path": "/system/role/list", "icon": "shield-half", "perm": "Role:READ"},
                    {"label": "DocType", "path": "/system/doctype/list", "icon": "files", "perm": "DocType:READ"},
                    {"label": "Action", "path": "/system/action/list", "icon": "flashlight", "perm": "Action:READ"},
                    {"label": "Permission", "path": "/system/permission/list", "icon": "key",
                     "perm": "Permission:READ"},
                    {"label": "Role Permission", "path": "/system/role-permission/list", "icon": "shield-check",
                     "perm": "Role Permission:READ"},
                    {"label": "User Role", "path": "/system/user-role/list", "icon": "shield",
                     "perm": "User Role:READ"},
                    {"label": "Permission Override", "path": "/system/permission-override/list", "icon": "lock-keyhole",
                     "perm": "Permission Override:READ"},
                    {"label": "User Constraint", "path": "/system/user-constraint/list", "icon": "scan-line",
                     "perm": "User Constraint:READ"},
                ],
            },
        ],
    },

]
