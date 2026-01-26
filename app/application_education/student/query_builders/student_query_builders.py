from __future__ import annotations

from typing import Optional

from sqlalchemy import select, case, false, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.student.models import Student, Guardian
from app.application_org.models.company import Branch


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _br(ctx: AffiliationContext) -> Optional[int]:
    # if your ctx uses branch_id
    return getattr(ctx, "branch_id", None)


def _empty_student_list():
    return select(Student.id.label("id")).where(false())


def _empty_guardian_list():
    return select(Guardian.id.label("id")).where(false())


def build_students_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Students.

    ✅ Scope:
      - Any user in Company X can see ALL students in Company X (no branch filtering)
      - Users from other companies get empty (Forbidden -> empty)

    ✅ Smart Order:
      1) Current user's branch first (if ctx.branch_id exists)
      2) Newest first (created_at desc)
      3) Name asc
      4) ID desc
    """
    co_id = _co(context)
    if not co_id:
        return _empty_student_list()

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return _empty_student_list()

    my_branch_id = _br(context)
    my_branch_first = case((Student.branch_id == int(my_branch_id), 0), else_=1) if my_branch_id else case((false(), 0), else_=1)

    q = (
        select(
            Student.id.label("id"),
            Student.student_code.label("code"),
            Student.full_name.label("student_name"),
            Student.is_enabled.label("is_enabled"),
            Student.branch_id.label("branch_id"),
            Branch.name.label("branch_name"),
        )
        .select_from(Student)
        .outerjoin(Branch, Branch.id == Student.branch_id)
        .where(Student.company_id == int(co_id))
        .order_by(
            my_branch_first.asc(),
            Student.created_at.desc(),
            func.lower(Student.full_name).asc(),
            Student.id.desc(),
        )
    )
    return q


def build_guardians_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Guardians.

    ✅ Fields:
      - id, guardian_code, guardian_name, mobile_number, branch

    ✅ Smart Order:
      1) Current user's branch first (if ctx.branch_id exists)
      2) Newest first (created_at desc)
      3) Name asc
      4) ID desc
    """
    co_id = _co(context)
    if not co_id:
        return _empty_guardian_list()

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return _empty_guardian_list()

    my_branch_id = _br(context)
    my_branch_first = case((Guardian.branch_id == int(my_branch_id), 0), else_=1) if my_branch_id else case((false(), 0), else_=1)

    q = (
        select(
            Guardian.id.label("id"),
            Guardian.guardian_code.label("code"),
            Guardian.guardian_name.label("guardian_name"),
            Guardian.mobile_number.label("mobile_number"),
            Guardian.branch_id.label("branch_id"),
            Branch.name.label("branch_name"),
        )
        .select_from(Guardian)
        .outerjoin(Branch, Branch.id == Guardian.branch_id)
        .where(Guardian.company_id == int(co_id))
        .order_by(
            my_branch_first.asc(),
            Guardian.created_at.desc(),
            func.lower(Guardian.guardian_name).asc(),
            Guardian.id.desc(),
        )
    )
    return q
