from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, case, false
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.student.models import Student, Guardian
from app.application_org.models.company import Branch


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _br(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "branch_id", None)


def _empty_student_dropdown():
    return select(Student.id.label("value")).where(false())


def _empty_guardian_dropdown():
    return select(Guardian.id.label("value")).where(false())


def _enforce_company_scope_or_empty(ctx: AffiliationContext, company_id: int) -> None:
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def build_students_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all students (company-scoped)
    ✅ Smart order:
      1) current user's branch first (if ctx.branch_id exists)
      2) newest first, then name
    ✅ label = student name
    ✅ meta includes code + phone + branch
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_student_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return _empty_student_dropdown()

    ctx_branch_id = _br(ctx)

    q = (
        select(
            Student.id.label("value"),
            Student.full_name.label("label"),

            # meta
            Student.student_code.label("code"),
            Student.student_mobile_number.label("phone"),
            Student.branch_id.label("branch_id"),
            Branch.name.label("branch_name"),
        )
        .select_from(Student)
        .outerjoin(Branch, Branch.id == Student.branch_id)
        .where(Student.company_id == int(co_id))
    )

    # Optional filters (safe)
    branch_id = params.get("branch_id")
    if branch_id:
        try:
            q = q.where(Student.branch_id == int(branch_id))
        except Exception:
            pass

    is_enabled = params.get("is_enabled")
    if is_enabled is not None:
        if isinstance(is_enabled, str):
            v = is_enabled.strip().lower()
            if v in ("1", "true", "yes", "y"):
                q = q.where(Student.is_enabled.is_(True))
            elif v in ("0", "false", "no", "n"):
                q = q.where(Student.is_enabled.is_(False))
        elif isinstance(is_enabled, bool):
            q = q.where(Student.is_enabled.is_(is_enabled))

    # ✅ Dynamic order_by (avoid ORDER BY 0)
    order_by_items = []
    if ctx_branch_id:
        order_by_items.append(case((Student.branch_id == int(ctx_branch_id), 0), else_=1).asc())

    order_by_items.extend([
        Student.created_at.desc(),
        Student.full_name.asc(),
        Student.id.desc(),
    ])

    q = q.order_by(*order_by_items)
    return q


def build_guardians_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all guardians (company-scoped)
    ✅ Smart order:
      1) current user's branch first (if ctx.branch_id exists)
      2) newest first, then name
    ✅ label = guardian name
    ✅ meta includes code + phone + branch
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_guardian_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return _empty_guardian_dropdown()

    ctx_branch_id = _br(ctx)

    q = (
        select(
            Guardian.id.label("value"),
            Guardian.guardian_name.label("label"),

            # meta
            Guardian.guardian_code.label("code"),
            Guardian.mobile_number.label("phone"),
            Guardian.branch_id.label("branch_id"),
            Branch.name.label("branch_name"),
        )
        .select_from(Guardian)
        .outerjoin(Branch, Branch.id == Guardian.branch_id)
        .where(Guardian.company_id == int(co_id))
    )

    # Optional filter: branch_id
    branch_id = params.get("branch_id")
    if branch_id:
        try:
            q = q.where(Guardian.branch_id == int(branch_id))
        except Exception:
            pass

    # ✅ Dynamic order_by (avoid ORDER BY 0)
    order_by_items = []
    if ctx_branch_id:
        order_by_items.append(case((Guardian.branch_id == int(ctx_branch_id), 0), else_=1).asc())

    order_by_items.extend([
        Guardian.created_at.desc(),
        Guardian.guardian_name.asc(),
        Guardian.id.desc(),
    ])

    q = q.order_by(*order_by_items)
    return q
