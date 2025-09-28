from __future__ import annotations
from typing import Optional

from sqlalchemy import select, and_, or_, func, false
from sqlalchemy.orm import Session, aliased

from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_org.models.company import Branch
from app.auth.models.users import User, UserAffiliation, UserType
from app.security.rbac_effective import AffiliationContext

from app.application_nventory.inventory_models import Brand  # not used; keep imports clean
from app.common.models.base import StatusEnum  # for typing clarity



def build_users_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of users with key columns:

      id, username, status, user_type, full_name, branch_name, last_login

    Scoping rules (fast and simple):
      - If caller has company_id -> users tied to that company via:
          * primary UserAffiliation.company_id == company_id  OR
          * Employee.company_id == company_id                 OR
          * EmployeeAssignment.company_id == company_id
      - If caller has branch_ids -> prefer assignment branch name; fall back to affiliation branch.

    Notes:
      - Uses COALESCE for full_name and branch_name.
      - Search/sort/filter fields will be wired from ListConfig.
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        # No tenant in context → empty result
        return select(User.id).where(false())

    # Aliases (explicit helps readability)
    u = User
    ua = UserAffiliation
    ut = UserType
    e = Employee
    ea = EmployeeAssignment
    b_assign = aliased(Branch, name="b_assign")
    b_aff    = aliased(Branch, name="b_aff")

    # Expressions
    full_name_expr   = func.coalesce(e.full_name, u.username).label("full_name")
    user_type_expr   = ut.name.label("user_type")
    branch_name_expr = func.coalesce(b_assign.name, b_aff.name).label("branch_name")

    q = (
        select(
            u.id.label("id"),
            u.username.label("username"),
            u.status.label("status"),
            user_type_expr,
            full_name_expr,
            branch_name_expr,
            u.last_login.label("last_login"),
        )
        .select_from(u)
        # HR side: employee + current/primary assignment (company mirrored on EA)
        .outerjoin(e, and_(e.user_id == u.id, e.company_id == co_id))
        .outerjoin(
            ea,
            and_(
                ea.employee_id == e.id,
                ea.company_id == co_id,
                ea.is_primary.is_(True),
                ea.to_date.is_(None),  # current primary
            ),
        )
        .outerjoin(b_assign, b_assign.id == ea.branch_id)
        # Primary affiliation (company-scoped)
        .outerjoin(
            ua,
            and_(
                ua.user_id == u.id,
                ua.company_id == co_id,
                ua.is_primary.is_(True),
            ),
        )
        .outerjoin(ut, ut.id == ua.user_type_id)
        .outerjoin(b_aff, b_aff.id == ua.branch_id)
        # Scope: must belong to tenant by EITHER HR or Affiliation side
        .where(
            or_(
                ua.company_id == co_id,
                e.company_id == co_id,
                ea.company_id == co_id,
            )
        )
    )

    # If caller has explicit branch scope list, you can optionally filter here.
    # But typically branch scoping for "users" lists is relaxed. Uncomment if you want:
    #
    # branch_ids = list(getattr(context, "branch_ids", []) or [])
    # if branch_ids:
    #     q = q.where(or_(ea.branch_id.in_(branch_ids), ua.branch_id.in_(branch_ids)))

    # Collapse duplicates introduced by joins (1 row per user)
    q = q.group_by(
        u.id, u.username, u.status, u.last_login,
        ut.name,
        e.full_name,
        b_assign.name, b_aff.name,
    )

    return q
