from __future__ import annotations
from typing import Dict, Any, Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.application_org.models.company import City
from app.application_parties.parties_models import Party, PartyRoleEnum, PartyOrganizationDetail, PartyCommercialPolicy
from app.security.rbac_effective import AffiliationContext
from app.common.models.base import StatusEnum  # typing clarity only



# --------------------------
# tiny helpers / validations
# --------------------------
def _status_to_slug(v) -> str:
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return (s or "inactive").lower()


def _ensure_company_and_branch_visibility(
    s: Session, ctx: AffiliationContext, *, party_row: Any
) -> None:
    """
    - Company scope: party.company_id must be in caller's affiliations (unless sysadmin)
    - Branch visibility:
        * global (branch_id is NULL) -> allowed
        * branch-scoped -> caller must have that branch in ctx.branch_ids (unless sysadmin)
    """
    if getattr(ctx, "is_system_admin", False):
        return

    co_id = getattr(ctx, "company_id", None)
    if not co_id or int(party_row.company_id) != int(co_id):
        raise Forbidden("Out of scope.")

    branch_id = party_row.branch_id
    if branch_id is None:
        return  # global party -> visible to all company users

    allowed_branch_ids = set(getattr(ctx, "branch_ids", []) or [])
    if int(branch_id) not in allowed_branch_ids:
        raise Forbidden("Out of scope.")


# --------------------------
# resolvers (by = ...)
# --------------------------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_party_by_code(s: Session, ctx: AffiliationContext, code: str, *, role: PartyRoleEnum) -> int:
    """
    Resolve PK by (company_id, role, code). Requires ctx.company_id unless sysadmin.
    """
    code = (code or "").strip()
    if not code:
        raise BadRequest("Code required.")

    if not getattr(ctx, "is_system_admin", False):
        co_id = getattr(ctx, "company_id", None)
        if not co_id:
            raise Forbidden("Out of scope.")
        row = s.execute(
            select(Party.id)
            .where(and_(Party.company_id == int(co_id), Party.role == role, Party.code == code))
        ).first()
    else:
        row = s.execute(
            select(Party.id).where(and_(Party.role == role, Party.code == code))
        ).first()

    if not row:
        raise NotFound(f"{role.value} not found.")
    return int(row.id)


def resolve_customer_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    return resolve_party_by_code(s, ctx, code, role=PartyRoleEnum.CUSTOMER)


def resolve_supplier_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    return resolve_party_by_code(s, ctx, code, role=PartyRoleEnum.SUPPLIER)


# --------------------------
# loader (id -> JSON)
# --------------------------
def _load_party_row(s: Session, party_id: int, *, expected_role: PartyRoleEnum):
    q = (
        select(
            Party.id,
            Party.company_id,
            Party.branch_id,
            Party.code,
            Party.name,
            Party.nature,
            Party.role,
            Party.status,
            Party.is_cash_party,
            Party.email,
            Party.phone,
            Party.address_line1,
            Party.city_id,
            City.name.label("city_name"),
        )
        .select_from(Party)
        .outerjoin(City, City.id == Party.city_id)
        .where(Party.id == party_id)
    )
    row = s.execute(q).mappings().first()
    if not row:
        raise NotFound("Party not found.")
    if row.role != expected_role:
        raise Forbidden("Mismatched role.")
    return row


def _load_organization_details(s: Session, party_id: int) -> Dict[str, Any] | None:
    row = s.execute(
        select(
            PartyOrganizationDetail.org_company_name,
            PartyOrganizationDetail.org_branch_name,
            PartyOrganizationDetail.org_contact_name,
            PartyOrganizationDetail.org_contact_phone,
            PartyOrganizationDetail.org_contact_email,
        ).where(PartyOrganizationDetail.party_id == party_id)
    ).mappings().first()
    if not row:
        return None
    return {
        "org_company_name": row.org_company_name,
        "org_branch_name": row.org_branch_name,
        "org_contact_name": row.org_contact_name,
        "org_contact_phone": row.org_contact_phone,
        "org_contact_email": row.org_contact_email,
    }


def _load_commercial_policy(s: Session, party_id: int, company_id: int) -> Dict[str, Any] | None:
    row = s.execute(
        select(
            PartyCommercialPolicy.allow_credit,
            PartyCommercialPolicy.credit_limit,
        ).where(
            and_(
                PartyCommercialPolicy.party_id == party_id,
                PartyCommercialPolicy.company_id == company_id,
            )
        )
    ).mappings().first()
    if not row:
        return None
    return {
        "allow_credit": bool(row.allow_credit),
        "credit_limit": float(row.credit_limit or 0),
    }


def load_party_detail(s: Session, ctx: AffiliationContext, party_id: int, *, role: PartyRoleEnum) -> Dict[str, Any]:
    """
    Returns a stable, organized JSON shape (similar philosophy to your user detail).
    """
    # 1) fetch + scope checks
    party = _load_party_row(s, party_id, expected_role=role)
    _ensure_company_and_branch_visibility(s, ctx, party_row=party)

    # 2) extras
    org = _load_organization_details(s, party_id)
    comm = _load_commercial_policy(s, party_id, company_id=int(party.company_id))

    # 3) assemble
    identity = {
        "party_id": int(party.id),
        "company_id": int(party.company_id),
        "branch_id": int(party.branch_id) if party.branch_id is not None else None,
        "role": role.value.lower(),               # "customer" | "supplier"
        "code": party.code,
        "name": party.name,
        "nature": (party.nature.value if hasattr(party.nature, "value") else str(party.nature)),
        "status": _status_to_slug(party.status),  # "active"/"inactive"
        "is_cash_party": bool(party.is_cash_party),
    }

    territory = {
        "city_id": int(party.city_id) if party.city_id else None,
        "territory_name": party.city_name,
    }

    contacts_address = {
        "email": party.email,
        "phone": party.phone,
        "address_line1": party.address_line1,
        "city": party.city_name,
    }

    return {
        "identity": identity,
        "territory": territory,
        "organization_details": org,        # may be None
        "commercial_policy": comm,          # may be None
        "contacts_and_address": contacts_address,
    }


def load_customer_detail(s: Session, ctx: AffiliationContext, party_id: int) -> Dict[str, Any]:
    return load_party_detail(s, ctx, party_id, role=PartyRoleEnum.CUSTOMER)


def load_supplier_detail(s: Session, ctx: AffiliationContext, party_id: int) -> Dict[str, Any]:
    return load_party_detail(s, ctx, party_id, role=PartyRoleEnum.SUPPLIER)
