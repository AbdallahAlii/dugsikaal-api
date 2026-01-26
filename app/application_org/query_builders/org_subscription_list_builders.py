from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.sql import literal_column
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin

from app.application_org.models.company import Company
from app.navigation_workspace.models.subscription import (
    CompanyPackageSubscription as CPS,
    ModulePackage as P,
)


def _ensure_system_admin(ctx: AffiliationContext) -> None:
    if not _is_system_admin(ctx):
        raise Forbidden("Only System Admin can perform this action.")


def build_company_packages_matrix_list_query(session: Session, context: AffiliationContext):
    """
    One row per company, with packages array:

    {
      company_id,
      company_name,
      company_status,
      packages: [
        { id, package_id, package_slug, package_name, subscription_is_enabled },
        ...
      ]
    }
    """
    _ensure_system_admin(context)

    C = Company

    pkg_obj = func.json_build_object(
        "id", CPS.id,  # subscription id (important for detail/update)
        "package_id", P.id,
        "package_slug", P.slug,
        "package_name", P.name,
        "subscription_is_enabled", CPS.is_enabled,
    )

    packages = func.coalesce(
        func.json_agg(aggregate_order_by(pkg_obj, P.slug.asc())).filter(CPS.id.isnot(None)),
        literal_column("'[]'::jsonb"),
    ).label("packages")

    q = (
        select(
            C.id.label("company_id"),
            C.name.label("company_name"),
            C.status.label("company_status"),
            packages,
        )
        .select_from(C)
        .outerjoin(CPS, CPS.company_id == C.id)
        .outerjoin(P, P.id == CPS.package_id)
        .group_by(C.id, C.name, C.status)
    )

    return q
