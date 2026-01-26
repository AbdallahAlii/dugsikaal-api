# app/application_parties/dropdown_builders/parties_dropdown.py
from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, case, false
from sqlalchemy.orm import Session

from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_org.models.company import Branch
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.common.models.base import StatusEnum


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _empty_dropdown():
    return select(Party.id.label("value")).where(false())


def _enforce_company_scope_or_empty(ctx: AffiliationContext, company_id: int):
    """
    ✅ Rule:
      - Any user in the same company can see ALL parties (regardless of party.branch_id).
      - Users from other companies cannot see this data.
      - System Admin bypass is handled by ensure_scope_by_ids.
    """
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def _location_display():
    # Purely display (NOT a scope filter)
    return case((Party.branch_id.is_(None), "Company Wide"), else_=Branch.name).label("location")


def _base_party_dropdown_query(*, company_id: int):
    """
    Common select columns used by all dropdowns.
    """
    return (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            Party.email.label("email"),
            Party.phone.label("phone"),
            _location_display(),
            Party.branch_id.label("branch_id"),
            Party.role.label("role"),
            Party.created_at.label("created_at"),
        )
        .select_from(Party)
        .outerjoin(Branch, Branch.id == Party.branch_id)
        .where(
            Party.company_id == int(company_id),
            Party.status == StatusEnum.ACTIVE,
        )
    )


def build_suppliers_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Suppliers dropdown (role=SUPPLIER)

    ✅ Scope:
      - Same company: see ALL suppliers (no branch restriction)
      - Different company: no data

    ✅ Sorting:
      - Newest first (ERP-style)
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, co_id)
    except Exception:
        return _empty_dropdown()

    q = _base_party_dropdown_query(company_id=co_id).where(Party.role == PartyRoleEnum.SUPPLIER)

    # Newest first, then name (stable UX)
    q = q.order_by(Party.created_at.desc(), Party.name.asc())

    return q


def build_customers_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Customers dropdown (role=CUSTOMER)

    ✅ Scope:
      - Same company: see ALL customers (no branch restriction)
      - Different company: no data

    ✅ Sorting:
      - Newest first (ERP-style)
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, co_id)
    except Exception:
        return _empty_dropdown()

    q = _base_party_dropdown_query(company_id=co_id).where(Party.role == PartyRoleEnum.CUSTOMER)

    # Newest first, then name
    q = q.order_by(Party.created_at.desc(), Party.name.asc())

    return q


def build_all_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All parties dropdown (customers + suppliers)

    ✅ Scope:
      - Same company: see ALL parties (no branch restriction)
      - Different company: no data

    ✅ Sorting:
      - Newest first (ERP-style)
      - Then role (stable ordering if same timestamp)
      - Then name
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, co_id)
    except Exception:
        return _empty_dropdown()

    role_display = case(
        (Party.role == PartyRoleEnum.SUPPLIER, "Supplier"),
        else_="Customer",
    ).label("type")

    q = _base_party_dropdown_query(company_id=co_id).add_columns(role_display)

    q = q.order_by(
        Party.created_at.desc(),  # ✅ newest first
        case((Party.role == PartyRoleEnum.SUPPLIER, 0), else_=1),  # stable grouping
        Party.name.asc(),
    )

    return q


def build_cash_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Cash parties dropdown (is_cash_party=True)

    ✅ Scope:
      - Same company: see ALL cash parties (no branch restriction)
      - Different company: no data

    ✅ Sorting:
      - Newest first
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, co_id)
    except Exception:
        return _empty_dropdown()

    q = _base_party_dropdown_query(company_id=co_id).where(Party.is_cash_party.is_(True))

    q = q.order_by(Party.created_at.desc(), Party.name.asc())

    return q
