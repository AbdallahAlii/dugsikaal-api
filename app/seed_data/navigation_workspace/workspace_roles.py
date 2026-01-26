# seed_data/navigation_workspace/workspace_roles.py
"""
Workspace → Roles mapping (NAV VISIBILITY ONLY)

✅ Controls which roles can SEE each workspace in the UI.
❌ Does NOT grant CRUD permissions (RBAC does that).

Rule of thumb:
- Show a workspace only to roles responsible for that business area.
- If a role only needs context (read-only), keep that in RBAC and DO NOT show the workspace.
"""

WORKSPACE_ROLES = {
    # ==========================================================
    # EDUCATION DOMAIN (Back-office)
    # ==========================================================
    "admission": [
        # Owners
        "Education Manager",

        # Branch oversight
        "Branch Manager",
        "Assistant Branch Manager",

        # Branch billing team often needs student records
        "Branch Accountant",
        "Sales User",

        # Tenant owner
        "Super Admin",
    ],

    "academics": [
        # Owners
        "Education Manager",

        # Branch oversight
        "Branch Manager",
        "Assistant Branch Manager",

        # Accounting staff may need academic structure (class/program) for fees context
        "Branch Accountant",
        "Finance Manager",

        # Tenant owner
        "Super Admin",
    ],

    "timetable": [
        # Owners
        "Education Manager",

        # Branch oversight
        "Branch Manager",
        "Assistant Branch Manager",

        # Tenant owner
        "Super Admin",
    ],

    "attendance": [
        # Owners / oversight
        "Education Manager",
        "Branch Manager",
        "Assistant Branch Manager",

        # Tenant owner
        "Super Admin",
    ],

    "exams": [
        # Owners
        "Education Manager",
        "Exam Manager",

        # Branch oversight
        "Branch Manager",
        "Assistant Branch Manager",

        # Tenant owner
        "Super Admin",
    ],

    "fees": [
        # Owners
        "Fees Manager",
        "Finance Manager",

        # Branch billing team
        "Branch Accountant",
        "Sales User",

        # Branch oversight
        "Branch Manager",
        "Assistant Branch Manager",

        # Tenant owner
        "Super Admin",
    ],

    # ==========================================================
    # PORTALS (Portal-only workspaces)
    # ==========================================================
    "student-portal": [
        "Student",
    ],
    "teacher-portal": [
        "Teacher",
    ],
    "guardian-portal": [
        "Guardian",
    ],

    # ==========================================================
    # ERP DOMAIN (Operations)
    # ==========================================================
    "buying": [
        "Buying User",
        "Operations Manager",
        "Super Admin",
    ],

    "inventory": [
        "Inventory User",
        "Operations Manager",
        "Super Admin",
    ],

    "accounting": [
        # Owners
        "Finance Manager",

        # Branch accounting staff
        "Branch Accountant",

        # Tenant owner
        "Super Admin",
    ],

    # ==========================================================
    # ADMIN / PLATFORM
    # ==========================================================
    "access-control": [
        # Tenant owner
        "Super Admin",

        # Company managers who onboard staff + assign access
        "HR Manager",


    ],

    "host-admin": [
        # Host-only (SaaS console)
        "System Admin",
    ],

    # If you later enable HR workspace in navigation_workspace/data.py:
    # "hr": [
    #     "HR Manager",
    #     "Super Admin",
    # ],
}
