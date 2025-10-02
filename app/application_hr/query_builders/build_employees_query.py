from __future__ import annotations
from typing import Optional

from sqlalchemy import select, and_, func, false
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_hr.models.hr import Employee, EmployeeAssignment
from app.application_org.models.company import Branch, Department


def build_employees_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of employees with key columns:
      id, code, full_name, status, branch_name

    Rules:
      - Requires context.company_id (unless your repo injects it another way).
      - Uses CURRENT PRIMARY assignment for branch/department (is_primary & to_date IS NULL).
      - Optionally filter by caller's branch_ids (if your ListRepository passes them in).
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(Employee.id).where(false())

    # Current primary assignment
    ea = EmployeeAssignment
    b  = Branch
    d  = Department

    branch_name_expr = b.name.label("branch_name")

    q = (
        select(
            Employee.id.label("id"),
            Employee.code.label("code"),
            Employee.full_name.label("full_name"),
            Employee.status.label("status"),
            branch_name_expr,
        )
        .select_from(Employee)
        .outerjoin(
            ea,
            and_(
                ea.employee_id == Employee.id,
                ea.company_id == co_id,
                ea.is_primary.is_(True),
                ea.to_date.is_(None),
            ),
        )
        .outerjoin(b, b.id == ea.branch_id)
        .outerjoin(d, d.id == ea.department_id)
        .where(Employee.company_id == co_id)
        .group_by(
            Employee.id, Employee.code, Employee.full_name, Employee.status,
            b.name
        )
    )

    # If you want to restrict list to only caller's branches, uncomment:
    # branch_ids = list(getattr(context, "branch_ids", []) or [])
    # if branch_ids:
    #     q = q.where(ea.branch_id.in_(branch_ids))

    return q
