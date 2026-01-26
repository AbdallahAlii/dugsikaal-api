
# app/application_org/query_builders/org_detail_builders.py
from __future__ import annotations

from typing import Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin

from app.application_org.models.company import Company, Branch, City
from app.navigation_workspace.models.subscription import (
    CompanyPackageSubscription,
    ModulePackage,
)
from app.application_media.encrypted_media import image_url_from_key


def _enum_value(x) -> Optional[str]:
    if x is None:
        return None
    return getattr(x, "value", x)


def _ensure_system_admin(ctx: AffiliationContext) -> None:
    """
    Only System Admin can hit these host-level detail resolvers.
    """
    if not _is_system_admin(ctx):
        raise Forbidden("Only System Admin can perform this action.")


# =========================
# Resolvers (optional)
# =========================
def resolve_company_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """
    Resolve company_id by name.

    Only System Admin allowed; others get 403.
    """
    _ensure_system_admin(ctx)

    stmt = select(Company.id).where(Company.name == name)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Company not found.")
    return int(row[0])


def resolve_branch_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """
    Resolve branch_id by name.

    Only System Admin allowed; others get 403.
    """
    _ensure_system_admin(ctx)

    stmt = select(Branch.id).where(Branch.name == name)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Branch not found.")
    return int(row[0])


# =========================
# Company detail loader
# =========================
def load_company_detail(
    s: Session,
    ctx: AffiliationContext,
    company_id: int,
) -> Dict[str, Any]:
    """
    Clean JSON response for a company:

    {
      "company": { ... full company info ... },
      "subscriptions": [ ... packages ... ],
      "branches": [ ... branch summary ... ],
      "meta": { created_at, updated_at }
    }

    Only System Admin can load this.
    """
    _ensure_system_admin(ctx)

    C = Company
    CityM = City

    # --- Company header with city ---
    stmt = (
        select(
            C.id,
            C.name,
            C.prefix,
            C.status,
            C.timezone,
            C.headquarters_address,
            C.contact_email,
            C.contact_phone,
            C.city_id,
            C.img_key.label("logo_img_key"),
            C.created_at,
            C.updated_at,
            CityM.name.label("city_name"),
            CityM.region.label("city_region"),
        )
        .select_from(C)
        .outerjoin(CityM, CityM.id == C.city_id)
        .where(C.id == company_id)
    )
    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Company not found.")

    # --- Logo URL from encrypted key ---
    logo_url: Optional[str] = None
    img_key = row.get("logo_img_key")
    if img_key:
        try:
            logo_url = image_url_from_key(img_key)
        except Exception:
            logo_url = None

    # --- Subscriptions (packages) ---
    cps_stmt = (
        select(
            CompanyPackageSubscription.id,
            CompanyPackageSubscription.package_id,
            CompanyPackageSubscription.is_enabled,
            CompanyPackageSubscription.valid_from,
            CompanyPackageSubscription.valid_until,
            ModulePackage.slug.label("package_slug"),
            ModulePackage.name.label("package_name"),
        )
        .select_from(CompanyPackageSubscription)
        .join(ModulePackage, ModulePackage.id == CompanyPackageSubscription.package_id)
        .where(CompanyPackageSubscription.company_id == company_id)
        .order_by(ModulePackage.slug.asc())
    )
    cps_rows = s.execute(cps_stmt).mappings().all()

    subscriptions = []
    for r in cps_rows:
        subscriptions.append(
            {
                "id": r["id"],
                "package_id": r["package_id"],
                "package_slug": r["package_slug"],
                "package_name": r["package_name"],
                "is_enabled": bool(r["is_enabled"]),
                "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
                "valid_until": r["valid_until"].isoformat() if r["valid_until"] else None,
            }
        )

    # --- Branch summary (id + name + status + is_hq) ---
    B = Branch
    br_stmt = (
        select(
            B.id,
            B.name,
            B.status,
            B.is_hq,
        )
        .where(B.company_id == company_id)
        .order_by(B.is_hq.desc(), B.name.asc())
    )
    br_rows = s.execute(br_stmt).mappings().all()

    branches = [
        {
            "id": br["id"],
            "name": br["name"],
            "status": _enum_value(br["status"]),
            "is_hq": bool(br["is_hq"]),
        }
        for br in br_rows
    ]

    return {
        "company": {
            "id": row["id"],
            "name": row["name"],
            "prefix": row.get("prefix"),
            "status": _enum_value(row["status"]),
            "timezone": row.get("timezone"),
            "headquarters_address": row.get("headquarters_address"),
            "contact_email": row.get("contact_email"),
            "contact_phone": row.get("contact_phone"),
            "city": {
                "id": row.get("city_id"),
                "name": row.get("city_name"),
                "region": row.get("city_region"),
            },
            "logo_url": logo_url,
            "extra": {},
        },
        "subscriptions": subscriptions,
        "branches": branches,
        "meta": {
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        },
    }


# =========================
# Branch detail loader
# =========================
def load_branch_detail(
    s: Session,
    ctx: AffiliationContext,
    branch_id: int,
) -> Dict[str, Any]:
    """
    Clean JSON response for a branch:

    {
      "branch": { ... full branch info ... },
      "meta": { created_at, updated_at }
    }

    Only System Admin can load this.
    """
    _ensure_system_admin(ctx)

    B = Branch
    C = Company
    CityM = City

    stmt = (
        select(
            B.id,
            B.name,
            B.code,
            B.status,
            B.is_hq,
            B.company_id,
            B.location.label("location"),
            B.img_key.label("logo_img_key"),
            B.created_at,
            B.updated_at,
            C.name.label("company_name"),
            CityM.id.label("city_id"),
            CityM.name.label("city_name"),
            CityM.region.label("city_region"),
        )
        .select_from(B)
        .join(C, C.id == B.company_id)
        .outerjoin(CityM, CityM.id == C.city_id)
        .where(B.id == branch_id)
    )
    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Branch not found.")

    # --- Logo URL ---
    logo_url: Optional[str] = None
    img_key = row.get("logo_img_key")
    if img_key:
        try:
            logo_url = image_url_from_key(img_key)
        except Exception:
            logo_url = None

    return {
        "branch": {
            "id": row["id"],
            "name": row["name"],
            "code": row.get("code"),
            "status": _enum_value(row["status"]),
            "is_hq": bool(row.get("is_hq")),
            "company": {
                "id": row["company_id"],
                "name": row["company_name"],
            },
            "city": {
                "id": row.get("city_id"),
                "name": row.get("city_name"),
                "region": row.get("city_region"),
            },
            "location": row.get("location"),
            "address": row.get("location"),
            "contact_email": None,
            "contact_phone": None,
            "logo_url": logo_url,
            "extra": {},
        },
        "meta": {
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        },
    }
