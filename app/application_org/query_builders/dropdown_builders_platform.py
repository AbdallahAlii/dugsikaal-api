# # app/application_org/dropdown_builders_platform.py
# from __future__ import annotations
#
# from typing import Mapping, Any
#
# from sqlalchemy import select, literal
# from sqlalchemy.orm import Session
#
# from app.application_org.models.company import Company, Branch
#
# from app.security.rbac_effective import AffiliationContext
#
#
#
# def build_companies_platform_dropdown(
#     session: Session,
#     ctx: AffiliationContext,
#     params: Mapping[str, Any] | None,
# ):
#     """
#     Companies dropdown.
#
#     • value: Company.id
#     • label: Company.name
#     • meta: prefix, timezone, status
#
#     Behaviour:
#       - Platform/System admins: can see ALL companies.
#       - Non-platform users: restricted to their own company_id (if any).
#         Host-level non-admins see nothing.
#     """
#     params = params or {}
#
#     q = select(
#         Company.id.label("value"),
#         Company.name.label("label"),
#         Company.prefix.label("prefix"),
#         Company.timezone.label("timezone"),
#         Company.status.label("status"),
#     )
#
#     # Access control
#     if _has_platform_admin_scope(ctx):
#         # Optional filters for admins
#         if "status" in params and params["status"]:
#             q = q.where(Company.status == params["status"])
#
#         if "city_id" in params and params["city_id"]:
#             try:
#                 city_id = int(params["city_id"])
#                 q = q.where(Company.city_id == city_id)
#             except (TypeError, ValueError):
#                 pass  # ignore bad filter values silently
#     else:
#         # Non-platform → restrict to their own company_id
#         company_id = getattr(ctx, "company_id", None)
#         if company_id is not None:
#             q = q.where(Company.id == int(company_id))
#         else:
#             # host-level user with no company and not platform admin → no access
#             q = q.where(literal(False))
#
#     q = q.order_by(Company.name.asc())
#     return q
#
#
# def build_platform_branches_dropdown(
#     session: Session,
#     ctx: AffiliationContext,
#     params: Mapping[str, Any] | None,
# ):
#     """
#     Branches dropdown.
#
#     • value: Branch.id
#     • label: Branch.name
#     • meta: code, company_id, company_name, is_hq, status
#
#     Behaviour:
#       - Platform/System admins: can see branches across ALL companies,
#         optionally filtered by company_id.
#       - Non-platform users: only branches under their company_id.
#     """
#     params = params or {}
#
#     q = (
#         select(
#             Branch.id.label("value"),
#             Branch.name.label("label"),
#             Branch.code.label("code"),
#             Branch.company_id.label("company_id"),
#             Branch.is_hq.label("is_hq"),
#             Branch.status.label("status"),
#             Company.name.label("company_name"),
#         )
#         .join(Company, Branch.company_id == Company.id)
#     )
#
#     # Access control
#     if _has_platform_admin_scope(ctx):
#         # Admin can optionally filter by company_id
#         company_id = params.get("company_id")
#         if company_id:
#             try:
#                 company_id = int(company_id)
#                 q = q.where(Branch.company_id == company_id)
#             except (TypeError, ValueError):
#                 pass
#     else:
#         # Non-platform → restrict to ctx.company_id
#         company_id = getattr(ctx, "company_id", None)
#         if company_id is not None:
#             q = q.where(Branch.company_id == int(company_id))
#         else:
#             q = q.where(literal(False))
#
#     # Optional status / is_hq filters
#     status = params.get("status")
#     if status:
#         q = q.where(Branch.status == status)
#
#     is_hq = params.get("is_hq")
#     if is_hq is not None and is_hq != "":
#         # expect true/false in params; handle "true"/"false" strings
#         if isinstance(is_hq, str):
#             is_hq_l = is_hq.strip().lower()
#             if is_hq_l in ("true", "1", "yes"):
#                 is_hq_val = True
#             elif is_hq_l in ("false", "0", "no"):
#                 is_hq_val = False
#             else:
#                 is_hq_val = None
#         else:
#             is_hq_val = bool(is_hq)
#
#         if is_hq_val is not None:
#             q = q.where(Branch.is_hq == is_hq_val)
#
#     q = q.order_by(Company.name.asc(), Branch.is_hq.desc(), Branch.name.asc())
#     return q
# def build_company_branches_dependent_dropdown(
#     session: Session,
#     ctx: AffiliationContext,
#     params: Mapping[str, Any] | None,
# ):
#     """
#     Dependent branches dropdown driven by company_id.
#
#     • value: Branch.id
#     • label: Branch.name
#     • meta: code, is_hq, status
#
#     Behaviour:
#       - Requires params['company_id'].
#       - Platform admins: can see branches for any company_id.
#       - Normal users: only see branches under their own ctx.company_id;
#         cannot see branches for other companies even if company_id is passed.
#       - If no company_id is provided → returns no rows (for nice dependent UX).
#     """
#     params = params or {}
#
#     raw_company_id = params.get("company_id")
#     if not raw_company_id:
#         # No company selected yet -> don't hit DB with full scan
#         return select(Branch.id.label("value")).where(literal(False))
#
#     try:
#         company_id = int(raw_company_id)
#     except (TypeError, ValueError):
#         # Bad value -> empty result
#         return select(Branch.id.label("value")).where(literal(False))
#
#     q = select(
#         Branch.id.label("value"),
#         Branch.name.label("label"),
#         Branch.code.label("code"),
#         Branch.is_hq.label("is_hq"),
#         Branch.status.label("status"),
#     )
#
#     if _has_platform_admin_scope(ctx):
#         # Platform admin can see branches for *any* company_id passed in params
#         q = q.where(Branch.company_id == company_id)
#     else:
#         # Normal user -> enforce ctx.company_id
#         ctx_company_id = getattr(ctx, "company_id", None)
#         if ctx_company_id is None or int(ctx_company_id) != company_id:
#             # Trying to access other company's branches -> deny
#             q = q.where(literal(False))
#         else:
#             q = q.where(Branch.company_id == int(ctx_company_id))
#
#     # Optional extra filters
#     status = params.get("status")
#     if status:
#         q = q.where(Branch.status == status)
#
#     is_hq = params.get("is_hq")
#     if is_hq is not None and is_hq != "":
#         if isinstance(is_hq, str):
#             is_hq_l = is_hq.strip().lower()
#             if is_hq_l in ("true", "1", "yes"):
#                 is_hq_val = True
#             elif is_hq_l in ("false", "0", "no"):
#                 is_hq_val = False
#             else:
#                 is_hq_val = None
#         else:
#             is_hq_val = bool(is_hq)
#
#         if is_hq_val is not None:
#             q = q.where(Branch.is_hq == is_hq_val)
#
#     return q.order_by(Branch.is_hq.desc(), Branch.name.asc())
# app/application_org/dropdown_builders_platform.py
from __future__ import annotations

from typing import Mapping, Any

from sqlalchemy import select, literal
from sqlalchemy.orm import Session

from app.application_org.models.company import Company, Branch
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin


def _has_platform_admin_scope(ctx: AffiliationContext) -> bool:
    """
    In this context, "platform admin" == System Admin.

    We delegate to the central _is_system_admin() helper so the rule
    lives in one place (flag or 'System Admin' role). This ensures that
    only true system admins can see platform-wide dropdowns.
    """
    return _is_system_admin(ctx)


def build_companies_platform_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any] | None,
):
    """
    Companies dropdown (platform-level).

    • value: Company.id
    • label: Company.name
    • meta: prefix, timezone, status

    Behaviour:
      - System admins: can see ALL companies (optionally filtered).
      - Non-admins: see NOTHING (this endpoint is platform-only).
    """
    params = params or {}

    # 🔒 Hard gate: only system admins
    if not _has_platform_admin_scope(ctx):
        # Return an always-false query -> no rows
        return select(Company.id.label("value")).where(literal(False))

    q = select(
        Company.id.label("value"),
        Company.name.label("label"),
        Company.prefix.label("prefix"),
        Company.timezone.label("timezone"),
        Company.status.label("status"),
    )

    # Optional filters for admins
    status = params.get("status")
    if status:
        q = q.where(Company.status == status)

    city_id = params.get("city_id")
    if city_id:
        try:
            city_id_int = int(city_id)
            q = q.where(Company.city_id == city_id_int)
        except (TypeError, ValueError):
            # ignore bad filter values silently
            pass

    q = q.order_by(Company.name.asc())
    return q


def build_platform_branches_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any] | None,
):
    """
    Branches dropdown (platform-level).

    • value: Branch.id
    • label: Branch.name
    • meta: code, company_id, company_name, is_hq, status

    Behaviour:
      - System admins: can see branches across ALL companies
        (optionally filtered by company_id, status, is_hq).
      - Non-admins: see NOTHING (this endpoint is platform-only).
    """
    params = params or {}

    # 🔒 Hard gate: only system admins
    if not _has_platform_admin_scope(ctx):
        return select(Branch.id.label("value")).where(literal(False))

    q = (
        select(
            Branch.id.label("value"),
            Branch.name.label("label"),
            Branch.code.label("code"),
            Branch.company_id.label("company_id"),
            Branch.is_hq.label("is_hq"),
            Branch.status.label("status"),
            Company.name.label("company_name"),
        )
        .join(Company, Branch.company_id == Company.id)
    )

    # Admin can optionally filter by company_id
    company_id = params.get("company_id")
    if company_id:
        try:
            company_id_int = int(company_id)
            q = q.where(Branch.company_id == company_id_int)
        except (TypeError, ValueError):
            pass

    # Optional status / is_hq filters
    status = params.get("status")
    if status:
        q = q.where(Branch.status == status)

    is_hq = params.get("is_hq")
    if is_hq is not None and is_hq != "":
        # Expect true/false; handle "true"/"false" strings
        if isinstance(is_hq, str):
            is_hq_l = is_hq.strip().lower()
            if is_hq_l in ("true", "1", "yes"):
                is_hq_val = True
            elif is_hq_l in ("false", "0", "no"):
                is_hq_val = False
            else:
                is_hq_val = None
        else:
            is_hq_val = bool(is_hq)

        if is_hq_val is not None:
            q = q.where(Branch.is_hq == is_hq_val)

    q = q.order_by(Company.name.asc(), Branch.is_hq.desc(), Branch.name.asc())
    return q


def build_company_branches_dependent_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any] | None,
):
    """
    Dependent branches dropdown driven by company_id.

    • value: Branch.id
    • label: Branch.name
    • meta: code, is_hq, status

    Behaviour:
      - Requires params['company_id'].
      - System admins: can see branches for ANY company_id.
      - Normal users: only see branches under their own ctx.company_id;
        cannot see branches for other companies even if company_id is passed.
      - If no company_id is provided → returns no rows (for nice dependent UX).
    """
    params = params or {}

    raw_company_id = params.get("company_id")
    if not raw_company_id:
        # No company selected yet -> don't hit DB with full scan
        return select(Branch.id.label("value")).where(literal(False))

    try:
        company_id = int(raw_company_id)
    except (TypeError, ValueError):
        # Bad value -> empty result
        return select(Branch.id.label("value")).where(literal(False))

    q = select(
        Branch.id.label("value"),
        Branch.name.label("label"),
        Branch.code.label("code"),
        Branch.is_hq.label("is_hq"),
        Branch.status.label("status"),
    )

    if _has_platform_admin_scope(ctx):
        # Platform admin can see branches for *any* company_id passed in params
        q = q.where(Branch.company_id == company_id)
    else:
        # Normal user -> enforce ctx.company_id
        ctx_company_id = getattr(ctx, "company_id", None)
        if ctx_company_id is None or int(ctx_company_id) != company_id:
            # Trying to access other company's branches -> deny
            q = q.where(literal(False))
        else:
            q = q.where(Branch.company_id == int(ctx_company_id))

    # Optional extra filters
    status = params.get("status")
    if status:
        q = q.where(Branch.status == status)

    is_hq = params.get("is_hq")
    if is_hq is not None and is_hq != "":
        if isinstance(is_hq, str):
            is_hq_l = is_hq.strip().lower()
            if is_hq_l in ("true", "1", "yes"):
                is_hq_val = True
            elif is_hq_l in ("false", "0", "no"):
                is_hq_val = False
            else:
                is_hq_val = None
        else:
            is_hq_val = bool(is_hq)

        if is_hq_val is not None:
            q = q.where(Branch.is_hq == is_hq_val)

    return q.order_by(Branch.is_hq.desc(), Branch.name.asc())
