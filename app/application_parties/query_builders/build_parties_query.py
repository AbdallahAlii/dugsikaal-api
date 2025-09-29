from __future__ import annotations
from typing import Optional, Iterable

from sqlalchemy import select, and_, or_, func, false
from sqlalchemy.orm import Session, aliased

from app.application_org.models.company import City
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.security.rbac_effective import AffiliationContext
from app.common.models.base import StatusEnum  # type hints only


def _branch_scope_predicate(branch_ids: Iterable[int] | None):
    """
    Global parties (branch_id IS NULL) are visible to everyone in the company.
    Branch-scoped parties are visible only if the caller belongs to that branch.
    """
    if branch_ids:
        return or_(Party.branch_id.is_(None), Party.branch_id.in_(list(branch_ids)))
    # no branch scope provided -> show only global parties
    return Party.branch_id.is_(None)


def build_parties_query(session: Session, context: AffiliationContext, *, role: PartyRoleEnum):
    """
    Company-scoped list of parties (Customer/Supplier).

    Columns returned:
        id, code, name, status, territory_name (City.name)

    Scoping:
      - Requires context.company_id
      - Always shows global parties (branch_id IS NULL) for that company
      - Shows branch-scoped parties (branch_id IN context.branch_ids) only if user belongs to those branches
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        # No tenant context -> empty query
        return select(Party.id).where(false())

    c = aliased(City, name="city")

    territory_expr = func.coalesce(c.name, "").label("territory_name")

    branch_ids = list(getattr(context, "branch_ids", []) or [])

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
                _branch_scope_predicate(branch_ids),
            )
        )
        # one row per party; explicit group_by makes ORM happy across dialects
        .group_by(
            Party.id, Party.code, Party.name, Party.status, c.name
        )
    )

    return q


def build_customers_query(session: Session, context: AffiliationContext):
    return build_parties_query(session, context, role=PartyRoleEnum.CUSTOMER)


def build_suppliers_query(session: Session, context: AffiliationContext):
    return build_parties_query(session, context, role=PartyRoleEnum.SUPPLIER)
