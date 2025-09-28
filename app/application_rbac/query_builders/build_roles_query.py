# app/application_rbac/query_builders/build_roles_query.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, or_, and_, false
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_rbac.rbac_models import Role  # make sure this is the correct path


def build_roles_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of roles:

      id, name, scope, company_id, is_system_defined, is_active

    Visibility rules:
      - Always include system-defined roles (is_system_defined = True)
      - Include roles created for the caller's company (company_id = ctx.company_id)
      - Exclude roles from other companies
      - If no company_id in context and not sysadmin: only system-defined

    NOTE:
      If your sysadmin should also see *all* company roles, change the WHERE accordingly.
    """
    co_id: Optional[int] = getattr(context, "company_id", None)

    # If you want sysadmin to see only sys-defined + current tenant roles, keep this.
    # If you want sysadmin to see everything, replace the whole where() with True().
    visibility_clause = (
        Role.is_system_defined.is_(True)
        if co_id is None
        else or_(Role.is_system_defined.is_(True), Role.company_id == co_id)
    )

    q = (
        select(
            Role.id.label("id"),
            Role.name.label("name"),
            Role.scope.label("scope"),
            Role.company_id.label("company_id"),
            Role.is_system_defined.label("is_system_defined"),

        )
        .select_from(Role)
        .where(visibility_clause)
    )

    # 1 row per role; no GROUP BY needed unless you add joins later
    return q
