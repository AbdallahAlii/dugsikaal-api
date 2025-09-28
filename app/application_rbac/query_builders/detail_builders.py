from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext

from app.auth.models.users import User, UserAffiliation, UserType
from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_org.models.company import Branch, Company
from app.application_rbac.rbac_models import (
    Role, UserRole, Permission, RolePermission, DocType, Action, PermissionOverride
)

# --------------------------
# helpers / tiny validations
# --------------------------
def _ensure_company(ctx: AffiliationContext, company_id: Optional[int]):
    """System Admin: allow everywhere. Else require affiliation with company_id."""
    if getattr(ctx, "is_system_admin", False):
        return
    if not company_id:
        raise Forbidden("Out of scope.")
    if not any(a.company_id == company_id for a in (ctx.affiliations or [])):
        raise Forbidden("Out of scope.")


def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)

# --------------------
# resolvers (by=...)
# --------------------
def resolve_user_by_username(s: Session, ctx: AffiliationContext, username: str) -> int:
    """
    Resolve user PK by username; then if caller has company_id, ensure the user belongs to it
    via primary affiliation OR HR employee/company OR assignment.company_id.
    """
    urow = s.execute(select(User.id).where(User.username == username)).first()
    if not urow:
        raise NotFound("User not found.")
    user_id = int(urow.id)

    co_id = getattr(ctx, "company_id", None)
    if co_id and not getattr(ctx, "is_system_admin", False):
        # any of these links the user to caller's company
        aff = s.execute(
            select(UserAffiliation.id).where(
                and_(UserAffiliation.user_id == user_id, UserAffiliation.company_id == co_id)
            )
        ).first()
        if aff:
            return user_id

        emp = s.execute(
            select(Employee.id).where(and_(Employee.user_id == user_id, Employee.company_id == co_id))
        ).first()
        if emp:
            return user_id

        assign = s.execute(
            select(EmployeeAssignment.id)
            .join(Employee, EmployeeAssignment.employee_id == Employee.id)
            .where(and_(Employee.user_id == user_id, EmployeeAssignment.company_id == co_id))
        ).first()
        if assign:
            return user_id

        raise Forbidden("Out of scope.")

    return user_id


# --------------------
# loader (id -> JSON)
# --------------------
def _status_to_slug(v) -> str:
    # convert enum-ish to lowercase slug like 'active' | 'inactive'
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return s.lower() or "inactive"


def load_user_detail(s: Session, ctx: AffiliationContext, user_id: int) -> Dict[str, Any]:
    """
    Return detail in your legacy FastAPI shape:

    {
      user_id, username, status, created_at, last_login,
      full_name, phone, user_type, campus_branch,
      assigned_roles: [{role_id, role_name}],
      allowed_modules: [str],
      allowed_doctypes: [{module, doctype, actions: [str]}]
    }

    - campus_branch: prefer current primary assignment branch name,
      else primary affiliation branch name, else company name (if resolvable).
    - scope: if ctx.company_id is present (and not sysadmin), user must belong to that company.
    """
    co_id = getattr(ctx, "company_id", None)

    base = (
        select(
            User.id.label("id"),
            User.username,
            User.status,
            User.created_at,
            User.last_login,
            func.coalesce(Employee.full_name, User.username).label("full_name"),
            Employee.phone_number.label("phone"),

            # primary assignment (current)
            EmployeeAssignment.branch_id.label("assign_branch_id"),
            EmployeeAssignment.company_id.label("assign_company_id"),

            # primary affiliation
            UserAffiliation.company_id.label("aff_company_id"),
            UserAffiliation.branch_id.label("aff_branch_id"),
            UserAffiliation.user_type_id,
            UserType.name.label("user_type"),
        )
        .select_from(User)
        .outerjoin(Employee, Employee.user_id == User.id)
        .outerjoin(
            EmployeeAssignment,
            and_(
                EmployeeAssignment.employee_id == Employee.id,
                EmployeeAssignment.is_primary.is_(True),
                EmployeeAssignment.to_date.is_(None),
            ),
        )
        .outerjoin(
            UserAffiliation,
            and_(UserAffiliation.user_id == User.id, UserAffiliation.is_primary.is_(True)),
        )
        .outerjoin(UserType, UserType.id == UserAffiliation.user_type_id)
        .where(User.id == user_id)
    )

    row = s.execute(base).mappings().first()
    if not row:
        raise NotFound("User not found.")

    # Scope check (company)
    if co_id and not getattr(ctx, "is_system_admin", False):
        links = 0
        if row.aff_company_id == co_id:
            links += 1
        if row.assign_company_id == co_id:
            links += 1
        # also HR employee.company_id
        emp_count = s.execute(
            select(func.count()).select_from(Employee).where(
                and_(Employee.user_id == user_id, Employee.company_id == co_id)
            )
        ).scalar() or 0
        links += int(emp_count)
        if links == 0:
            raise Forbidden("Out of scope.")

    # Resolve campus_branch (assignment > affiliation > company)
    campus_branch = None
    assign_branch = None
    aff_branch = None

    if row.assign_branch_id:
        ab = s.execute(select(Branch.name).where(Branch.id == row.assign_branch_id)).scalar()
        if ab:
            assign_branch = {"id": int(row.assign_branch_id), "name": ab}
            campus_branch = ab

    if row.aff_branch_id:
        fb = s.execute(select(Branch.name).where(Branch.id == row.aff_branch_id)).scalar()
        if fb:
            aff_branch = {"id": int(row.aff_branch_id), "name": fb}
            if not campus_branch:
                campus_branch = fb

    if not campus_branch:
        # try to get company name for a friendlier fallback
        company_id = row.assign_company_id or row.aff_company_id or co_id
        if company_id:
            cname = s.execute(select(Company.name).where(Company.id == int(company_id))).scalar()
            campus_branch = cname

    # Assigned roles (active)
    assigned_roles_rows = s.execute(
        select(Role.id, Role.name)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(and_(UserRole.user_id == user_id, UserRole.is_active.is_(True)))
        .group_by(Role.id, Role.name)
    ).all()
    assigned_roles = [{"role_id": int(r.id), "role_name": r.name} for r in assigned_roles_rows]

    # Effective permissions:
    # 1) RolePermission where is_allowed=True
    rp_rows = s.execute(
        select(
            Permission.id.label("perm_id"),
            DocType.id.label("doctype_id"),
            DocType.module.label("module"),
            DocType.name.label("doctype"),
            Action.name.label("action"),
        )
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .join(DocType, DocType.id == Permission.doctype_id)
        .join(Action, Action.id == Permission.action_id)
        .where(and_(UserRole.user_id == user_id, RolePermission.is_allowed.is_(True)))
        .group_by(Permission.id, DocType.id, Action.id)
    ).mappings().all()

    # 2) Apply per-user overrides (force allow/deny)
    eff: dict[tuple[int, str], dict] = {(p["doctype_id"], p["action"]): dict(p) for p in rp_rows}

    ov_rows = s.execute(
        select(
            Permission.doctype_id,
            Action.name.label("action"),
            PermissionOverride.is_allowed,
        )
        .select_from(PermissionOverride)
        .join(Permission, PermissionOverride.permission_id == Permission.id)
        .join(Action, Action.id == Permission.action_id)
        .where(PermissionOverride.user_id == user_id)
    ).mappings().all()

    for ov in ov_rows:
        key = (int(ov["doctype_id"]), ov["action"])
        if ov["is_allowed"]:
            if key not in eff:
                dt = s.execute(select(DocType.module, DocType.name).where(DocType.id == ov["doctype_id"])).first()
                if dt:
                    eff[key] = {
                        "perm_id": None,
                        "doctype_id": int(ov["doctype_id"]),
                        "module": dt.module,
                        "doctype": dt.name,
                        "action": ov["action"],
                    }
        else:
            eff.pop(key, None)

    # 3) Aggregate to FastAPI-style:
    #    allowed_modules: [module]
    #    allowed_doctypes: [{module, doctype, actions: [..]}]
    modules_set = set()
    by_doctype: dict[tuple[str, str], set] = defaultdict(set)
    for p in eff.values():
        m = p["module"]; d = p["doctype"]; a = p["action"]
        modules_set.add(m)
        by_doctype[(m, d)].add(a)

    allowed_modules = sorted(modules_set)
    allowed_doctypes = [
        {"module": m, "doctype": d, "actions": sorted(list(actions))}
        for (m, d), actions in sorted(by_doctype.items(), key=lambda x: (x[0][0], x[0][1]))
    ]

    return {
        # FastAPI-shaped keys
        "user_id": int(row.id),
        "username": row.username,
        "status": _status_to_slug(row.status),  # "active" / "inactive"
        "created_at": row.created_at,
        "last_login": row.last_login,
        "full_name": row.full_name,
        "phone": row.phone,
        "user_type": row.user_type,
        "campus_branch": campus_branch,  # assignment > affiliation > company name
        "assigned_roles": assigned_roles,
        "allowed_modules": allowed_modules,
        "allowed_doctypes": allowed_doctypes,
        # (optional) keep detailed branches if you still want them for UI:
        # "branches": {"assignment": assign_branch, "affiliation": aff_branch},
    }
