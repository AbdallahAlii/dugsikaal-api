
# app/application_org/query_builders/org_list_builders.py
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin
from app.application_org.models.company import Company, Branch, City


def _ensure_system_admin(context: AffiliationContext) -> None:
    """
    Only System Admin can access host-level company/branch lists.
    Super Admin (company-scoped) is NOT enough.
    """
    if not _is_system_admin(context):
        # Match OrgService behavior
        raise Forbidden("Only System Admin can perform this action.")


# =========================
# Company list query
# =========================
def build_companies_list_query(session: Session, context: AffiliationContext):
    """
    Host-level Companies list.

    Minimal columns:
      - id
      - name
      - status
      - timezone
      - city_id, city_name
      - branches_count

    Only System Admin can access this. Others get 403.
    """
    _ensure_system_admin(context)

    C = Company
    CityM = City
    B = Branch

    q = (
        select(
            C.id.label("id"),
            C.name.label("name"),
            C.status.label("status"),
            C.timezone.label("timezone"),
            CityM.id.label("city_id"),
            CityM.name.label("city_name"),
            func.count(B.id).label("branches_count"),
        )
        .select_from(C)
        .outerjoin(CityM, CityM.id == C.city_id)
        .outerjoin(B, B.company_id == C.id)
        .group_by(
            C.id,
            C.name,
            C.status,
            C.timezone,
            CityM.id,
            CityM.name,
        )
    )

    return q


# =========================
# Branch list query
# =========================
def build_branches_list_query(session: Session, context: AffiliationContext):
    """
    Host-level Branches list.

    Minimal columns:
      - id
      - name
      - status
      - is_hq
      - company_id, company_name

    Only System Admin can access this. Others get 403.
    """
    _ensure_system_admin(context)

    B = Branch
    C = Company

    q = (
        select(
            B.id.label("id"),
            B.name.label("name"),
            B.status.label("status"),
            B.is_hq.label("is_hq"),
            C.id.label("company_id"),
            C.name.label("company_name"),
        )
        .select_from(B)
        .join(C, C.id == B.company_id)
    )

    return q
