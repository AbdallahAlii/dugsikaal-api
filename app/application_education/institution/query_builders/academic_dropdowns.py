from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, case, false
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.institution.academic_model import (
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _empty_dropdown():
    return select(AcademicYear.id.label("value")).where(false())


def _enforce_company_scope_or_empty(ctx: AffiliationContext, company_id: int):
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def build_academic_years_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all academic years (company-scoped)
    ✅ OPEN first
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return _empty_dropdown()

    open_first = case((AcademicYear.status == AcademicStatusEnum.OPEN, 0), else_=1)

    q = (
        select(
            AcademicYear.id.label("value"),
            AcademicYear.name.label("label"),
            AcademicYear.status.label("status"),
            AcademicYear.start_date.label("start_date"),
            AcademicYear.end_date.label("end_date"),
        )
        .select_from(AcademicYear)
        .where(AcademicYear.company_id == int(co_id))
        .order_by(open_first.asc(), AcademicYear.start_date.desc(), AcademicYear.name.asc())
    )
    return q


def build_academic_terms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all academic terms (company-scoped)
    ✅ OPEN first
    Optional filter: academic_year_id
    """
    co_id = _co(ctx)
    if not co_id:
        return select(AcademicTerm.id.label("value")).where(false())

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return select(AcademicTerm.id.label("value")).where(false())

    year_id = params.get("academic_year_id")
    open_first = case((AcademicTerm.status == AcademicStatusEnum.OPEN, 0), else_=1)

    q = (
        select(
            AcademicTerm.id.label("value"),
            AcademicTerm.name.label("label"),
            AcademicTerm.status.label("status"),
            AcademicTerm.start_date.label("start_date"),
            AcademicTerm.end_date.label("end_date"),
            AcademicTerm.academic_year_id.label("academic_year_id"),
        )
        .select_from(AcademicTerm)
        .where(AcademicTerm.company_id == int(co_id))
    )

    if year_id:
        try:
            q = q.where(AcademicTerm.academic_year_id == int(year_id))
        except Exception:
            # ignore bad filter, keep base query safe
            pass

    q = q.order_by(open_first.asc(), AcademicTerm.start_date.desc(), AcademicTerm.name.asc())
    return q
