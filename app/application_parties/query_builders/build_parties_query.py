from __future__ import annotations

from typing import Optional

from sqlalchemy import select, and_, func, false
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import Forbidden

from app.application_org.models.company import City
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.common.models.base import StatusEnum  # type hints only


def build_parties_query(session: Session, context: AffiliationContext, *, role: PartyRoleEnum):
    """
    Company-scoped list of parties (Customer/Supplier).

    ✅ Scope rules:
      - User in Company X (any branch) can see ALL parties in Company X
        (both company-level and branch-level parties).
      - User in Company Y cannot see Company X data.
      - No hard-coded branch filtering here.

    ERP-style ordering:
      - Newest first (created_at desc)
      - Then name asc
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(Party.id).where(false())

    # Enforce company scope (System Admin bypass is inside ensure_scope_by_ids)
    try:
        ensure_scope_by_ids(context=context, target_company_id=co_id, target_branch_id=None)
    except Forbidden:
        return select(Party.id).where(false())

    c = aliased(City, name="city")
    territory_expr = func.coalesce(c.name, "").label("territory_name")

    q = (
        select(
            Party.id.label("id"),
            Party.code.label("code"),
            Party.name.label("name"),
            Party.status.label("status"),
            territory_expr,
        )
        .select_from(Party)
        .outerjoin(c, c.id == Party.city_id)
        .where(
            and_(
                Party.company_id == co_id,
                Party.role == role,
            )
        )
        # one row per party; explicit group_by makes ORM happy across dialects
        .group_by(Party.id, Party.code, Party.name, Party.status, c.name)
        .order_by(
            Party.created_at.desc(),  # ✅ newest first
            Party.name.asc(),
            Party.id.desc(),          # tie-breaker (safe)
        )
    )

    return q


def build_customers_query(session: Session, context: AffiliationContext):
    return build_parties_query(session, context, role=PartyRoleEnum.CUSTOMER)


def build_suppliers_query(session: Session, context: AffiliationContext):
    return build_parties_query(session, context, role=PartyRoleEnum.SUPPLIER)
