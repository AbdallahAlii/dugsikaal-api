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


            #
            # {"label": "Delivery Note", "path": "/selling/delivery-note/list", "icon": "truck",
            #  "perm": "Delivery Note:READ"},
            {"label": "Sales Invoice", "path": "/selling/sales-invoice/list", "icon": "receipt",
             "perm": "Sales Invoice:READ"}

        ],

        "sections": [
            {
                "label": "Reports",
                "order_index": 30,
                "links": [

                    {"label": "Accounts Receivable", "path": "/accounts/report/accounts-receivable", "icon": "user-plus",
                     "perm": "Accounts Receivable Report:READ"},
                    {"label": "Accounts Receivable Summary","path": "/accounts/report/accounts-receivable-summary", "icon": "users",
                     "perm": "Accounts Receivable Summary Report:READ"},
                    {"label": "Sales Item Report", "path": "/accounts/report/gross-profit", "icon": "percent",
                     "perm": "Gross Profit Report:READ"},
                ],
            },
        ],
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

        "sections": [
            {
                "label": "Reports",
                "order_index": 30,
                "links": [

                    {"label": "Accounts Payable", "path": "/accounts/report/accounts-payable", "icon": "user-minus",
                     "perm": "Accounts Payable Report:READ"},
                    {"label": "Accounts Payable Summary", "path": "/accounts/report/accounts-payable-summary",
                     "icon": "users",
                     "perm": "Accounts Payable Summary Report:READ"},
                ],
            },
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
            {"label": "Item", "path": "/stock/item/list", "icon": "box", "perm": "Item:READ"},
            {"label": "Stock Entry", "path": "/stock/stock-entry/list", "icon": "arrows-left-right",
             "perm": "Stock Entry:READ"},
            {"label": "Stock Reconciliation", "path": "/stock/stock-reconciliation/list", "icon": "scale",
             "perm": "Stock Reconciliation:READ"},
            {"label": "Bin", "path": "/stock/bin/list", "icon": "cubes", "perm": "Bin:READ"},
            {"label": "Warehouse", "path": "/stock/warehouse/list", "icon": "warehouse", "perm": "Warehouse:READ"},
        ],
        "sections": [
            {
                "label": "Reports",
                "order_index": 30,
                "links": [
                    {"label": "Total Stock Summary", "path": "/stock/report/total-stock-summary", "icon": "archive",
                     "perm": "Total Stock Summary Report:READ"},
                    {"label": "Stock Balance", "path": "/stock/report/stock-balance", "icon": "scale"},
                    {"label": "Stock Ledger", "path": "/stock/report/stock-ledger", "icon": "book-open",
                     "perm": "Stock Ledger Report:READ"}
                ],
            },
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
            {"label": "Mode of Payment", "path": "/accounts/mode-of-payment/list", "icon": "wallet",
             "perm": "Mode of Payment:READ"},
            {"label": "Journal Entry", "path": "/accounts/journal-entry/list", "icon": "book-open",
             "perm": "Journal Entry:READ"},
            {"label": "Payment Entry", "path": "/accounts/payment-entry/list", "icon": "wallet",
             "perm": "Payment Entry:READ"},
            {"label": "Expense Claim", "path": "/accounts/expense-claim/list", "icon": "receipt",
             "perm": "Expense Claim:READ"},
        ],
        "sections": [
            {
                "label": "Reports",
                "order_index": 50, # Placed after core transactions
                "links": [
                    # Primary Financial Statements (most important for owner)
                    {"label": "Profit and Loss", "path": "/accounts/report/profit-and-loss", "icon": "trending-up",
                     "perm": "Profit and Loss Report:READ"},
                    {"label": "Balance Sheet", "path": "/accounts/report/balance-sheet", "icon": "landmark",
                     "perm": "Balance Sheet Report:READ"},
                    {"label": "Cash Flow Statement", "path": "/accounts/report/cash-flow", "icon": "activity",
                     "perm": "Cash Flow Report:READ"},

                    # Audit & Control Reports
                    {"label": "General Ledger", "path": "/accounts/report/gl", "icon": "book-marked",
                     "perm": "General Ledger Report:READ"},
                    {"label": "Trial Balance", "path": "/accounts/report/trial-balance", "icon": "scale",
                     "perm": "Trial Balance Report:READ"},

                    # Operational Overviews
                    {"label": "Accounts Receivable", "path": "/accounts/report/accounts-receivable", "icon": "user-plus",
                     "perm": "Accounts Receivable Report:READ"},
                    {"label": "Accounts Payable", "path": "/accounts/report/accounts-payable", "icon": "user-minus",
                     "perm": "Accounts Payable Report:READ"},
                    {"label": "Gross Profit", "path": "/accounts/report/gross-profit", "icon": "percent",
                     "perm": "Gross Profit Report:READ"},
                ],
            },
        ],
    },


    # === HR ===
    {
        "slug": "hr",
        "title": "HR & People",
        "icon": "id-card",
        "description": "Employee records and basics.",
        "order_index": 60,

        # Minimal daily-use links only
        "root_links": [
            {"label": "Employee", "path": "/hr/employee/list", "icon": "user-round",
             "perm": "Employee:READ"},
            {"label": "Employee Checkin", "path": "/hr/employee-checkin/list", "icon": "log-in",
             "perm": "Employee Checkin:READ"},
            {"label": "Shift Type", "path": "/hr/shift-type/list", "icon": "clock",
             "perm": "Shift Type:READ"},
            {"label": "Employee Group", "path": "/hr/employee-group/list", "icon": "users",
             "perm": "Employee Group:READ"},
            {"label": "Employee Health Insurance", "path": "/hr/employee-health-insurance/list", "icon": "heart-pulse",
             "perm": "Employee Health Insurance:READ"},
        ],

        # keep empty—everything else via DocTypes directory
        "sections": [],
    },




    # === HOST ADMINISTRATION (SYSTEM ADMIN ONLY) ===
    {
        "slug": "host-admin",
        "title": "Host Administration",
        "icon": "server-cog",
        "description": "Client companies and subscription management",
        "order_index": 92,
        "admin_only": True,

        "root_links": [
            # Client Management
            {"label": "Clients", "path": "/host-admin/tenant/list", "icon": "building-2",
             "perm": "Tenant:READ"},
            {"label": "Companies", "path": "/host-admin/company/list", "icon": "building",
             "perm": "Company:READ"},

            # Branch & Navigation Management
            {"label": "Branches", "path": "/host-admin/branch/list", "icon": "git-branch",
             "perm": "Branch:READ"},
            {"label": "Workspace Setup", "path": "/host-admin/workspace/list", "icon": "layout-dashboard",
             "perm": "Workspace:READ"},

            # Subscription Management
            {"label": "Subscription Plans", "path": "/host-admin/subscription-plan/list", "icon": "dollar-sign",
             "perm": "Subscription Plan:READ"},
            {"label": "Active Subscriptions", "path": "/host-admin/subscription/list", "icon": "credit-card",
             "perm": "Subscription:READ"},
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
