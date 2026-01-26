# app/application_data_import/query_builders/data_import_list_builders.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, false
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_data_import.models import DataImport
from app.application_org.models.company import Company


def _has_platform_admin_scope(ctx: AffiliationContext) -> bool:
    """
    System-level users who can see ALL companies' data imports.

    We treat as platform admin if:
      - ctx.is_system_admin is True
      - OR role 'System Admin' (case-insensitive) is present
      - OR role 'Super Admin' (for future compatibility)
    """
    if getattr(ctx, "is_system_admin", False):
        return True
    roles = getattr(ctx, "roles", []) or []
    roles_l = {str(r).strip().lower() for r in roles if r}
    return "system admin" in roles_l or "super admin" in roles_l


def _get_company_scope(ctx: AffiliationContext) -> Optional[int]:
    """
    For non-platform users, Data Import is company-level.

    Normal users: see only their own company imports.
    """
    return getattr(ctx, "company_id", None)


def build_data_imports_list_query(session: Session, context: AffiliationContext):
    """
    Data Import list (minimal columns for list UI):

      - id
      - code
      - status
      - reference_doctype
      - company_id
      - company_name
    """
    DI = DataImport
    C = Company

    # ✅ Platform/System admin → see ALL imports (no company filter)
    if _has_platform_admin_scope(context):
        q = (
            select(
                DI.id.label("id"),
                DI.code.label("code"),
                DI.status.label("status"),
                DI.reference_doctype.label("reference_doctype"),
                DI.company_id.label("company_id"),
                C.name.label("company_name"),
            )
            .select_from(DI)
            .join(C, C.id == DI.company_id)
        )
        return q

    # 👤 Normal user → restrict by their company_id
    company_id = _get_company_scope(context)
    if not company_id:
        # no company context → safe empty result
        return select(DI.id).where(false())

    q = (
        select(
            DI.id.label("id"),
            DI.code.label("code"),
            DI.status.label("status"),
            DI.reference_doctype.label("reference_doctype"),
            DI.company_id.label("company_id"),
            C.name.label("company_name"),
        )
        .select_from(DI)
        .join(C, C.id == DI.company_id)
        .where(DI.company_id == company_id)
    )

    return q
