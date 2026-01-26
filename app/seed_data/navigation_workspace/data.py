# seed_data/navigation_workspace/data.py

WORKSPACES: list[dict] = [

    # =========================================================================
    # ADMISSIONS & RECORDS
    # =========================================================================
    {
        "slug": "admission",
        "title": "Admissions",
        "icon": "clipboard-list",
        "description": "Students, guardians, and enrollments",
        "order_index": 10,

        "root_links": [
            {"label": "Students", "path": "/education/student/list", "icon": "user", "perm": "Student:READ"},
            {"label": "Guardians", "path": "/education/guardian/list", "icon": "user-round", "perm": "Guardian:READ"},
            {"label": "Program Enrollment", "path": "/education/program-enrollment/list", "icon": "clipboard",
             "perm": "Program Enrollment:READ"},
            {"label": "Course Enrollment", "path": "/education/course-enrollment/list", "icon": "bookmark",
             "perm": "Course Enrollment:READ"},
        ],

        "sections": [
            {
                "label": "Student Groups",
                "order_index": 10,
                "links": [
                    {"label": "Student Group", "path": "/education/student-group/list", "icon": "layers",
                     "perm": "Student Group:READ"},
                    {"label": "Student Category", "path": "/education/student-category/list", "icon": "tag",
                     "perm": "Student Category:READ"},
                ],
            },
        ],
    },

    # =========================================================================
    # ACADEMICS
    # =========================================================================
    {
        "slug": "academics",
        "title": "Academics",
        "icon": "graduation-cap",
        "description": "Classes, subjects, instructors, and calendar",
        "order_index": 20,

        "root_links": [
            {"label": "Classes", "path": "/education/class/list", "icon": "school", "perm": "Class:READ"},
            {"label": "Subjects", "path": "/education/course/list", "icon": "book", "perm": "Course:READ"},
            {"label": "Programs", "path": "/education/program/list", "icon": "list", "perm": "Program:READ"},
            {"label": "Instructors", "path": "/education/instructor/list", "icon": "user-check",
             "perm": "Instructor:READ"},
        ],

        "sections": [
            {
                "label": "Academic Calendar",
                "order_index": 10,
                "links": [
                    {"label": "Academic Year", "path": "/education/academic-year/list", "icon": "calendar",
                     "perm": "Academic Year:READ"},
                    {"label": "Academic Term", "path": "/education/academic-term/list", "icon": "calendar-days",
                     "perm": "Academic Term:READ"},
                    {"label": "Batch", "path": "/education/batch/list", "icon": "layers", "perm": "Batch:READ"},
                ],
            },
            {
                "label": "Setup",
                "order_index": 20,
                "links": [
                    {"label": "Progression Rules", "path": "/education/program-progression-rule/list",
                     "icon": "git-branch", "perm": "Program Progression Rule:READ"},
                    {"label": "Education Settings", "path": "/education/education-settings/list", "icon": "settings",
                     "perm": "Education Settings:READ"},
                ],
            },
        ],
    },

    # =========================================================================
    # SCHEDULING  (Timetable + Attendance merged)
    # =========================================================================
    {
        "slug": "scheduling",
        "title": "Scheduling",
        "icon": "calendar-clock",
        "description": "Timetable setup and attendance oversight",
        "order_index": 40,

        # ✅ Root links: only the top 5 most-used (USING YOUR EXISTING LINKS/NAMES)
        "root_links": [
            {"label": "Course Schedule", "path": "/education/course-schedule-slot/list", "icon": "grid-2x2",
             "perm": "Course Schedule Slot:READ"},
            {"label": "Attendance Sheet", "path": "/education/student-attendance/list", "icon": "clipboard-check",
             "perm": "Student Attendance:READ"},
            {"label": "Course Assignment", "path": "/education/course-assignment/list", "icon": "link",
             "perm": "Course Assignment:READ"},
            {"label": "Time Slot", "path": "/education/time-slot/list", "icon": "clock",
             "perm": "Time Slot:READ"},
            {"label": "Classroom", "path": "/education/classroom/list", "icon": "building",
             "perm": "Classroom:READ"},
        ],

        "sections": [
            {
                "label": "Timetable",
                "order_index": 10,
                "links": [
                    {"label": "Course Assignment", "path": "/education/course-assignment/list", "icon": "link",
                     "perm": "Course Assignment:READ"},
                    {"label": "Course Schedule", "path": "/education/course-schedule-slot/list", "icon": "grid-2x2",
                     "perm": "Course Schedule Slot:READ"},
                    {"label": "School Session", "path": "/education/school-session/list", "icon": "sun",
                     "perm": "School Session:READ"},
                    {"label": "Time Slot", "path": "/education/time-slot/list", "icon": "clock",
                     "perm": "Time Slot:READ"},
                    {"label": "Classroom", "path": "/education/classroom/list", "icon": "building",
                     "perm": "Classroom:READ"},
                ],
            },
            {
                "label": "Attendance",
                "order_index": 20,
                "links": [
                    {"label": "Attendance Sheet", "path": "/education/student-attendance/list",
                     "icon": "clipboard-check",
                     "perm": "Student Attendance:READ"},
                    {"label": "Attendance Rows", "path": "/education/student-attendance-row/list",
                     "icon": "list-checks",
                     "perm": "Student Attendance Row:READ"},
                ],
            },
            {
                "label": "Reports",
                "order_index": 30,
                "links": [
                    {"label": "Teacher Load Report", "path": "/education/report/teacher-load", "icon": "user-check",
                     "perm": "Course Assignment:READ"},
                    {"label": "Class Timetable Report", "path": "/education/report/class-timetable",
                     "icon": "layout-grid",
                     "perm": "Course Schedule Slot:READ"},
                    {"label": "Daily Class Attendance", "path": "/education/report/daily-attendance",
                     "icon": "calendar-days",
                     "perm": "Student Attendance:READ"},
                    {"label": "Student Attendance Summary", "path": "/education/report/student-attendance-summary",
                     "icon": "bar-chart-3",
                     "perm": "Student Attendance Row:READ"},
                ],
            },
        ],
    },

    # =========================================================================
    # EXAMS
    # =========================================================================
    {
        "slug": "assessment",
        "title": "Assessment",
        "icon": "file-check",
        "description": "Assessment setup, marks, results",
        "order_index": 60,

        "root_links": [
            {"label": "Assessment Scheme", "path": "/exams/assessment-scheme/list", "icon": "layers",        "perm": "Assessment Scheme:READ"},
            {"label": "Assessment Event",  "path": "/exams/assessment-event/list",  "icon": "calendar-days", "perm": "Assessment Event:READ"},
            {"label": "Marks Entry",       "path": "/exams/assessment-mark/list",   "icon": "pencil",        "perm": "Assessment Mark:READ"},
        ],

        "sections": [
            {
                "label": "Setup",
                "order_index": 10,
                "links": [
                    {"label": "Grading Scale",        "path": "/exams/grading-scale/list",            "icon": "ruler",        "perm": "Grading Scale:READ"},
                    {"label": "Grade Breakpoints",    "path": "/exams/grading-scale-breakpoint/list", "icon": "split",        "perm": "Grading Scale Breakpoint:READ"},
                    {"label": "Assessment Components","path": "/exams/assessment-component/list",     "icon": "blocks",       "perm": "Assessment Component:READ"},
                    {"label": "Component Rules",      "path": "/exams/assessment-component-rule/list","icon": "settings",     "perm": "Assessment Component Rule:READ"},
                    {"label": "Assessment Criteria",  "path": "/exams/assessment-criterion/list",     "icon": "check-square", "perm": "Assessment Criterion:READ"},
                ],
            },
            {
                "label": "Results",
                "order_index": 20,
                "links": [
                    {"label": "Course Results",   "path": "/exams/student-course-grade/list",  "icon": "badge-check", "perm": "Student Course Grade:READ"},
                    {"label": "Annual Results",   "path": "/exams/student-annual-result/list", "icon": "award",       "perm": "Student Annual Result:READ"},
                    {"label": "Result Holds",     "path": "/exams/student-result-hold/list",   "icon": "pause",       "perm": "Student Result Hold:READ"},
                    {"label": "Grade Recalc Job", "path": "/exams/grade-recalc-job/list",      "icon": "refresh-cw",  "perm": "Grade Recalc Job:READ"},
                ],
            },
        ],
    },

    # =========================================================================
    # FEES
    # =========================================================================
    {
        "slug": "fees",
        "title": "Fees",
        "icon": "wallet",
        "description": "Billing, receipts, and fee setup",
        "order_index": 70,

        "root_links": [
            {"label": "Students", "path": "/education/student/list", "icon": "users", "perm": "Student:READ"},
            {"label": "Quotations", "path": "/selling/sales-quotation/list", "icon": "file-badge",
             "perm": "Sales Quotation:READ"},
            {"label": "Sales Invoice", "path": "/selling/sales-invoice/list", "icon": "receipt",
             "perm": "Sales Invoice:READ"},
            {"label": "Payment Entry", "path": "/accounts/payment-entry/list", "icon": "wallet",
             "perm": "Payment Entry:READ"},
            {"label": "Fee Schedule", "path": "/fees/fee-schedule/list", "icon": "calendar",
             "perm": "Fee Schedule:READ"},
        ],

        "sections": [
            {
                "label": "Setup",
                "order_index": 10,
                "links": [
                    {"label": "Fee Category", "path": "/fees/fee-category/list", "icon": "tag",
                     "perm": "Fee Category:READ"},
                    {"label": "Fee Structure", "path": "/fees/fee-structure/list", "icon": "layers",
                     "perm": "Fee Structure:READ"},
                    {"label": "Fee Adjustments", "path": "/fees/student-fee-adjustment/list", "icon": "sliders",
                     "perm": "Student Fee Adjustment:READ"},
                ],
            },
            {
                "label": "Reports",
                "order_index": 20,
                "links": [
                    {"label": "Class Fee Balance", "path": "/fees/report/class-fee-balance", "icon": "school",
                     "perm": "Fees:READ"},
                    {"label": "Accounts Receivable", "path": "/accounts/report/accounts-receivable",
                     "icon": "user-plus", "perm": "Accounts Receivable Report:READ"},
                    {"label": "Accounts Receivable Summary", "path": "/accounts/report/accounts-receivable-summary",
                     "icon": "users", "perm": "Accounts Receivable Summary Report:READ"},

                ],
            },
        ],
    },

    # =========================================================================
    # STUDENT PORTAL
    # =========================================================================
    {
        "slug": "student-portal",
        "title": "Student Portal",
        "icon": "user-circle",
        "description": "My class, schedule, exams, attendance, and receipts",
        "order_index": 75,
        "portal_only": True,

        "root_links": [
            {"label": "My Classes", "path": "/portal/student/my-classes", "icon": "school",
             "perm": "Course Enrollment:READ"},
            {"label": "My Timetable", "path": "/portal/student/my-schedule", "icon": "calendar-days",
             "perm": "Course Schedule Slot:READ"},
        ],

        "sections": [
            {
                "label": "Exams",
                "order_index": 10,
                "links": [
                    {"label": "Exam Results", "path": "/portal/student/results/exam", "icon": "file-search",
                     "perm": "Student Course Grade:READ"},
                    {"label": "Annual Report Card", "path": "/portal/student/results/yearly", "icon": "scroll",
                     "perm": "Student Annual Result:READ"},
                ],
            },
            {
                "label": "Attendance",
                "order_index": 20,
                "links": [
                    {"label": "Attendance Summary", "path": "/portal/student/attendance/summary", "icon": "bar-chart-3",   "perm": "Student Attendance:READ"},
                    {"label": "Attendance History", "path": "/portal/student/attendance/history", "icon": "calendar-check","perm": "Student Attendance:READ"},
                ],
            },
            {
                "label": "Finance",
                "order_index": 30,
                "links": [
                    {"label": "Fee Statement", "path": "/portal/student/fees/statement", "icon": "file-text",
                     "perm": "Student Ledger Report:READ"},
                    {"label": "Payment Receipts", "path": "/portal/student/payments/receipts", "icon": "receipt",
                     "perm": "Payment Entry:READ"},
                ],
            },
        ],
    },


    # =========================================================================
    # TEACHER PORTAL
    # =========================================================================

    {
        "slug": "teacher-portal",
        "title": "Teacher Portal",
        "icon": "presentation",
        "description": "My classes, attendance, lesson plans, and marks",
        "order_index": 76,
        "portal_only": True,

        "root_links": [
            {"label": "My Classes", "path": "/portal/teacher/my-classes", "icon": "users-round",
             "perm": "Course Assignment:READ"},
            {"label": "My Timetable", "path": "/portal/teacher/timetable", "icon": "calendar-days",
             "perm": "Course Schedule Slot:READ"},
        ],

        "sections": [
            {
                "label": "Attendance",
                "order_index": 10,
                "links": [
                    # Teacher selects: Date -> Class -> Subject -> Period -> then marks
                    {"label": "Take Attendance", "path": "/portal/teacher/attendance/take", "icon": "clipboard-check",
                     "perm": "Student Attendance:CREATE"},
                    # Teacher views what they already recorded for their own periods/subjects
                    {"label": "My Attendance Log", "path": "/portal/teacher/attendance/my-log", "icon": "list-checks",
                     "perm": "Student Attendance:READ"},
                    # Teacher report: filter by Class/Subject/Period/Date range
                    {"label": "Class Attendance Report", "path": "/portal/teacher/attendance/class-report",
                     "icon": "bar-chart-3", "perm": "Student Attendance Row:READ"},
                ],
            },
            {
                "label": "Lesson Plans",
                "order_index": 20,
                "links": [
                    {"label": "New Lesson Plan", "path": "/education/lesson-plan/new", "icon": "plus-circle",
                     "perm": "Course Assignment:UPDATE"},
                    {"label": "My Lesson Plans", "path": "/education/lesson-plan/list", "icon": "book-open",
                     "perm": "Course Assignment:READ"},
                ],
            },
            {
                "label": "Exams",
                "order_index": 30,
                "links": [
                    {"label": "Enter Marks", "path": "/portal/teacher/marks/entry", "icon": "pencil-line",
                     "perm": "Assessment Mark:CREATE"},
                    {"label": "Class Results", "path": "/portal/teacher/marks/view", "icon": "bar-chart-3",
                     "perm": "Student Course Grade:READ"},
                    {"label": "Exam Schedule", "path": "/exams/assessment-event/list", "icon": "calendar-clock",
                     "perm": "Assessment Event:READ"},
                ],
            },
        ],
    },

    # =========================================================================
    # GUARDIAN PORTAL
    # =========================================================================
    {
        "slug": "guardian-portal",
        "title": "Guardian Portal",
        "icon": "users",
        "description": "Children results, attendance, and receipts",
        "order_index": 76,
        "portal_only": True,

        "root_links": [
            {"label": "My Children", "path": "/portal/guardian/children", "icon": "users", "perm": "Student:READ"},
            {"label": "Schedule", "path": "/portal/guardian/schedule", "icon": "calendar-days",
             "perm": "Course Schedule Slot:READ"},
        ],

        "sections": [
            {
                "label": "Exams",
                "order_index": 10,
                "links": [
                    {"label": "Exam Results", "path": "/portal/guardian/exams/results", "icon": "file-text",
                     "perm": "Student Course Grade:READ"},
                    {"label": "Annual Report Card", "path": "/portal/guardian/exams/annual-report", "icon": "scroll",
                     "perm": "Student Annual Result:READ"},
                ],
            },
            {
                "label": "Attendance",
                "order_index": 20,
                "links": [
                    {"label": "Attendance Summary", "path": "/portal/guardian/attendance/summary",
                     "icon": "bar-chart-3", "perm": "Student Attendance:READ"},
                    {"label": "Attendance Log", "path": "/portal/guardian/attendance/history", "icon": "calendar-check",
                     "perm": "Student Attendance Row:READ"},
                ],
            },
            {
                "label": "Finance",
                "order_index": 30,
                "links": [
                    {"label": "Fee Statement", "path": "/portal/guardian/fees/statement", "icon": "book-open",
                     "perm": "Student Ledger Report:READ"},
                    {"label": "Payment Receipts", "path": "/portal/guardian/payments/receipts", "icon": "receipt",
                     "perm": "Payment Entry:READ"},
                    # Optional if you allow printing/downloading receipts:
                    # {"label": "Print Receipts", "path": "/portal/guardian/payments/print", "icon": "printer", "perm": "Payment Entry:PRINT"},
                ],
            },
        ],
    },

    # =========================================================================
    # PROCUREMENT  (Buying + Inventory merged)
    # =========================================================================
    {
        "slug": "procurement",
        "title": "Procurement",
        "icon": "shopping-cart",
        "description": "Purchasing and inventory management",
        "order_index": 80,

        "root_links": [
            {"label": "Supplier", "path": "/buying/supplier/list", "icon": "user-round", "perm": "Supplier:READ"},

            {"label": "Quotation", "path": "/buying/purchase-quotation/list", "icon": "quote",
             "perm": "Purchase Quotation:READ"},
            {"label": "Purchase Invoice", "path": "/buying/purchase-invoice/list", "icon": "receipt",
             "perm": "Purchase Invoice:READ"},
        ],

        "sections": [
            {
                "label": "Inventory",
                "order_index": 10,
                "links": [
                    {"label": "Item", "path": "/inventory/item/list", "icon": "box", "perm": "Item:READ"},
                    {"label": "Warehouse", "path": "/inventory/warehouse/list", "icon": "warehouse",
                     "perm": "Warehouse:READ"},
                    {"label": "Stock Entry", "path": "/inventory/stock-entry/list", "icon": "arrows-left-right",
                     "perm": "Stock Entry:READ"},
                    {"label": "Stock Adjustment", "path": "/inventory/stock-reconciliation/list", "icon": "scale",
                     "perm": "Stock Reconciliation:READ"},
                    {"label": "Stock Balance", "path": "/inventory/bin/list", "icon": "cubes",
                     "perm": "Bin:READ"},
                ],
            },
            {
                "label": "Reports",
                "order_index": 30,
                "links": [
                    {"label": "Accounts Payable", "path": "/accounts/report/accounts-payable", "icon": "user-minus",
                     "perm": "Accounts Payable Report:READ"},
                    {"label": "Accounts Payable Summary", "path": "/accounts/report/accounts-payable-summary", "icon": "users",
                     "perm": "Accounts Payable Summary Report:READ"},
                    {"label": "Total Stock Summary", "path": "/stock/report/total-stock-summary", "icon": "archive",
                     "perm": "Total Stock Summary Report:READ"},
                    {"label": "Stock Balance Report", "path": "/stock/report/stock-balance", "icon": "scale",
                     "perm": "Stock Balance Report:READ"},
                    {"label": "Stock Ledger", "path": "/stock/report/stock-ledger", "icon": "book-open",
                     "perm": "Stock Ledger Report:READ"},
                ],
            },
        ],
    },


    # =========================================================================
    # ACCOUNTING
    # =========================================================================

    {
        "slug": "accounting",
        "title": "Accounting",
        "icon": "banknote",
        "description": "Finance, accounting & reports",
        "order_index": 40,
        "root_links": [
            {
                "label": "Chart of Accounts",
                "path": "/accounts/chart-of-accounts/list",
                "icon": "tree-pine",
                "perm": "Chart of Accounts:READ",
            },

            {
                "label": "Journal Entry",
                "path": "/accounts/journal-entry/list",
                "icon": "book-open",
                "perm": "Journal Entry:READ",
            },
            {
                "label": "Payment Entry",
                "path": "/accounts/payment-entry/list",
                "icon": "wallet",
                "perm": "Payment Entry:READ",
            },
            {
                "label": "Expense Claim",
                "path": "/accounts/expense-claim/list",
                "icon": "receipt",
                "perm": "Expense Claim:READ",
            },
        ],
        "sections": [
            {
                "label": "Reports",
                "order_index": 50,  # Placed after core transactions
                "links": [
                    # Primary Financial Statements
                    {
                        "label": "Profit and Loss",
                        "path": "/accounts/report/profit-and-loss",
                        "icon": "trending-up",
                        "perm": "Profit and Loss Report:READ",
                    },
                    {
                        "label": "Balance Sheet",
                        "path": "/accounts/report/balance-sheet",
                        "icon": "landmark",
                        "perm": "Balance Sheet Report:READ",
                    },
                    {
                        "label": "Cash Flow",
                        "path": "/accounts/report/cash-flow",
                        "icon": "activity",
                        "perm": "Cash Flow Report:READ",
                    },

                    # Audit & Control Reports
                    {
                        "label": "General Ledger",
                        "path": "/accounts/report/general-ledger",
                        "icon": "book-marked",
                        "perm": "General Ledger Report:READ",
                    },
                    {
                        "label": "Trial Balance",
                        "path": "/accounts/report/trial-balance",
                        "icon": "scale",
                        "perm": "Trial Balance Report:READ",
                    },
                    {
                        "label": "Stock Ledger",
                        "path": "/stock/report/stock-ledger",
                        "icon": "book-open",
                        "perm": "Stock Ledger Report:READ",
                    },

                    # Operational Overviews
                    {
                        "label": "Accounts Receivable Detail",
                        "path": "/accounts/report/accounts-receivable-Detail",
                        "icon": "user-plus",
                        "perm": "Accounts Receivable Report:READ",
                    },
                    {
                        "label": "Accounts Receivable Summary",
                        "path": "/accounts/report/accounts-receivable-summary",
                        "icon": "users",
                        "perm": "Accounts Receivable Summary Report:READ",
                    },
                    {
                        "label": "Accounts Payable Detail",
                        "path": "/accounts/report/accounts-payable-Detail",
                        "icon": "user-minus",
                        "perm": "Accounts Payable Report:READ",
                    },
                    {
                        "label": "Accounts Payable Summary",
                        "path": "/accounts/report/accounts-payable-summary",
                        "icon": "users",
                        "perm": "Accounts Payable Summary Report:READ",
                    },

                ],
            },
            {
                "label": "Accounting Setup",
                "order_index": 10,
                "links": [
                    {
                        "label": "Fiscal Year",
                        "path": "/accounts/fiscal-year/list",
                        "icon": "calendar",
                        "perm": "Fiscal Year:READ",
                    },
                    {
                        "label": "Period Closing",
                        "path": "/accounts/period-closing-voucher/list",
                        "icon": "lock",
                        "perm": "Period Closing Voucher:READ",
                    },
                    {
                        "label": "Mode of Payment",
                        "path": "/accounts/mode-of-payment/list",
                        "icon": "credit-card",
                        "perm": "Mode of Payment:READ",
                    }
                ],
            },
        ],
    },
    # =========================================================================
    # ADMINISTRATION
    # =========================================================================
    {
        "slug": "administration",
        "title": "Administration",
        "icon": "shield-check",
        "description": "Users, employees, and access control",
        "order_index": 70,

        "root_links": [
            {"label": "User", "path": "/system/user/list", "icon": "user", "perm": "User:READ"},
            {"label": "Employee", "path": "/hr/employee/list", "icon": "user-round", "perm": "Employee:READ"},
        ],

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

            {"label": "Companies", "path": "/host-admin/company/list", "icon": "building", "perm": "Company:READ"},

            # Branch & Navigation Management
            {"label": "Branches", "path": "/host-admin/branch/list", "icon": "git-branch", "perm": "Branch:READ"},
            {
                "label": "Workspace Setup",
                "path": "/host-admin/workspace/list",
                "icon": "layout-dashboard",
                "perm": "Workspace:READ",
            },

            # Subscription Management
            {
                "label": "Subscription Plans",
                "path": "/host-admin/subscription-plan/list",
                "icon": "dollar-sign",
                "perm": "Subscription Plan:READ",
            },
            {
                "label": "Active Subscriptions",
                "path": "/host-admin/subscription/list",
                "icon": "credit-card",
                "perm": "Subscription:READ",
            },
        ],
        "sections": [
            {
                "label": "Data Management",
                "order_index": 40,
                "links": [
                    {
                        "label": "Data Import",
                        "path": "/host-admin/data-import/list",
                        "icon": "upload-cloud",
                        "perm": "Data Import:READ",
                    },

                ],
            },
        ],
    },


    # =========================================================================
    # HR
    # =========================================================================
    # {
    #     "slug": "hr",
    #     "title": "HR & People",
    #     "icon": "id-card",
    #     "description": "Employee records and management",
    #     "order_index": 110,
    #
    #     "root_links": [
    #         {"label": "Employee",        "path": "/hr/employee/list",          "icon": "user-round",     "perm": "Employee:READ"},
    #         {"label": "Shift Type",      "path": "/hr/shift-type/list",        "icon": "clock",          "perm": "Shift Type:READ"},
    #         {"label": "Attendance",      "path": "/hr/attendance/list",        "icon": "calendar-check", "perm": "Attendance:READ"},
    #         {"label": "Employee Checkin","path": "/hr/employee-checkin/list",  "icon": "log-in",         "perm": "Employee Checkin:READ"},
    #     ],
    #
    #     "sections": [
    #         {
    #             "label": "Payroll & Salary",
    #             "order_index": 10,
    #             "links": [
    #                 {"label": "Salary Structure", "path": "/hr/salary-structure/list", "icon": "file-text",      "perm": "Salary Structure:READ"},
    #                 {"label": "Payroll Period",   "path": "/hr/payroll-period/list",   "icon": "calendar-range", "perm": "Payroll Period:READ"},
    #                 {"label": "Salary Slip",      "path": "/hr/salary-slip/list",      "icon": "receipt",        "perm": "Salary Slip:READ"},
    #             ],
    #         },
    #         {
    #             "label": "Leave & Holidays",
    #             "order_index": 20,
    #             "links": [
    #                 {"label": "Shift Assignment", "path": "/hr/shift-assignment/list", "icon": "calendar",   "perm": "Shift Assignment:READ"},
    #                 {"label": "Holiday List",     "path": "/hr/holiday-list/list",     "icon": "calendar-x", "perm": "Holiday List:READ"},
    #                 {"label": "Holiday",          "path": "/hr/holiday/list",          "icon": "umbrella",   "perm": "Holiday:READ"},
    #                 {"label": "Leave Type",       "path": "/hr/leave-type/list",       "icon": "tag",        "perm": "Leave Type:READ"},
    #                 {"label": "Leave Application","path": "/hr/leave-application/list","icon": "file-text",  "perm": "Leave Application:READ"},
    #             ],
    #         },
    #     ],
    # },

]
