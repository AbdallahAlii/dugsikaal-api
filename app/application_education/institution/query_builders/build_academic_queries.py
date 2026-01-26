
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, case, false, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.institution.academic_model import (
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)

# Import your date helper
from app.common.date_utils import format_date_out


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _empty_list():
    return select(AcademicYear.id.label("id")).where(false())


def build_academic_years_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Academic Years.

    ✅ Scope:
      - Any user in Company X can see ALL years in Company X (no branch filtering)
      - Users from other companies get empty (Forbidden -> empty)

    ✅ Order:
      - OPEN first
      - then start_date desc
      - then name asc
    """
    co_id = _co(context)
    if not co_id:
        return _empty_list()

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return _empty_list()

    open_first = case((AcademicYear.status == AcademicStatusEnum.OPEN, 0), else_=1)

    q = (
        select(
            AcademicYear.id.label("id"),
            AcademicYear.name.label("name"),
            # Format dates using helper function
            func.to_char(AcademicYear.start_date, 'DD-MM-YYYY').label("start_date"),
            func.to_char(AcademicYear.end_date, 'DD-MM-YYYY').label("end_date"),
            AcademicYear.status.label("status"),
        )
        .select_from(AcademicYear)
        .where(AcademicYear.company_id == int(co_id))
        .order_by(
            open_first.asc(),
            AcademicYear.start_date.desc(),
            AcademicYear.name.asc(),
            AcademicYear.id.desc(),
        )
    )
    return q


def build_academic_terms_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Academic Terms.

    ✅ Output fields (as requested):
      - id, name, start_date, end_date

    ✅ Order:
      - OPEN first
      - then start_date desc
      - then name asc
    """
    co_id = _co(context)
    if not co_id:
        return select(AcademicTerm.id.label("id")).where(false())

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return select(AcademicTerm.id.label("id")).where(false())

    open_first = case((AcademicTerm.status == AcademicStatusEnum.OPEN, 0), else_=1)

    q = (
        select(
            AcademicTerm.id.label("id"),
            AcademicTerm.name.label("name"),
            # Format dates using helper function
            func.to_char(AcademicTerm.start_date, 'DD-MM-YYYY').label("start_date"),
            func.to_char(AcademicTerm.end_date, 'DD-MM-YYYY').label("end_date"),
        )
        .select_from(AcademicTerm)
        .where(AcademicTerm.company_id == int(co_id))
        .order_by(
            open_first.asc(),
            AcademicTerm.start_date.desc(),
            AcademicTerm.name.asc(),
            AcademicTerm.id.desc(),
        )
    )
    return q