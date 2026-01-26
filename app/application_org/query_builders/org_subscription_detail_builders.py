from __future__ import annotations

from typing import Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden, NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin
from app.application_org.models.company import Company
from app.navigation_workspace.models.subscription import CompanyPackageSubscription, ModulePackage


def _ensure_system_admin(ctx: AffiliationContext) -> None:
    if not _is_system_admin(ctx):
        raise Forbidden("Only System Admin can perform this action.")


def load_company_package_subscription_detail(
    s: Session,
    ctx: AffiliationContext,
    subscription_id: int,
) -> Dict[str, Any]:
    """
    Detail for ONE subscription (System Admin only).
    Use this for edit/update package assignment for a company.
    """
    _ensure_system_admin(ctx)

    CPS = CompanyPackageSubscription
    C = Company
    P = ModulePackage

    stmt = (
        select(
            CPS.id.label("id"),
            CPS.company_id,
            CPS.package_id,
            CPS.is_enabled.label("is_enabled"),
            CPS.valid_from,
            CPS.valid_until,
            CPS.extra.label("extra"),
            C.name.label("company_name"),
            C.status.label("company_status"),
            P.slug.label("package_slug"),
            P.name.label("package_name"),
            P.is_enabled.label("package_is_enabled"),
        )
        .select_from(CPS)
        .join(C, C.id == CPS.company_id)
        .join(P, P.id == CPS.package_id)
        .where(CPS.id == subscription_id)
    )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("CompanyPackageSubscription not found.")

    return {
        "subscription": {
            "id": row["id"],
            "company": {
                "id": row["company_id"],
                "name": row["company_name"],
                "status": getattr(row["company_status"], "value", row["company_status"]),
            },
            "package": {
                "id": row["package_id"],
                "slug": row["package_slug"],
                "name": row["package_name"],
                "package_is_enabled": bool(row["package_is_enabled"]),
            },
            "is_enabled": bool(row["is_enabled"]),
            "valid_from": row["valid_from"].isoformat() if row["valid_from"] else None,
            "valid_until": row["valid_until"].isoformat() if row["valid_until"] else None,
            "extra": row["extra"] or {},
        }
    }
