from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import select, case, false, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.programs.models.program_models import Program, Course


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _empty_program_dropdown():
    return select(Program.id.label("value")).where(false())


def _empty_course_dropdown():
    return select(Course.id.label("value")).where(false())


def _enforce_company_scope_or_empty(ctx: AffiliationContext, company_id: int) -> None:
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def build_programs_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all programs (company-scoped)
    label = program name
    meta includes program_type + is_enabled
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_program_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return _empty_program_dropdown()

    q = (
        select(
            Program.id.label("value"),
            Program.name.label("label"),
            Program.program_type.label("program_type"),
            Program.is_enabled.label("is_enabled"),
        )
        .select_from(Program)
        .where(Program.company_id == int(co_id))
    )

    # Optional filters
    program_type = params.get("program_type")
    if program_type:
        try:
            q = q.where(Program.program_type == program_type)
        except Exception:
            pass

    is_enabled = params.get("is_enabled")
    if is_enabled is not None:
        if isinstance(is_enabled, str):
            v = is_enabled.strip().lower()
            if v in ("1", "true", "yes", "y"):
                q = q.where(Program.is_enabled.is_(True))
            elif v in ("0", "false", "no", "n"):
                q = q.where(Program.is_enabled.is_(False))
        elif isinstance(is_enabled, bool):
            q = q.where(Program.is_enabled.is_(is_enabled))

    enabled_first = case((Program.is_enabled.is_(True), 0), else_=1)

    q = q.order_by(
        enabled_first.asc(),
        Program.created_at.desc(),
        func.lower(Program.name).asc(),
        Program.id.desc(),
    )
    return q


def build_courses_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown: all courses (company-scoped)
    label = course name
    meta includes course_type + is_enabled
    """
    co_id = _co(ctx)
    if not co_id:
        return _empty_course_dropdown()

    try:
        _enforce_company_scope_or_empty(ctx, int(co_id))
    except (Forbidden, Exception):
        return _empty_course_dropdown()

    q = (
        select(
            Course.id.label("value"),
            Course.name.label("label"),
            Course.course_type.label("course_type"),
            Course.is_enabled.label("is_enabled"),
        )
        .select_from(Course)
        .where(Course.company_id == int(co_id))
    )

    # Optional filters
    course_type = params.get("course_type")
    if course_type:
        try:
            q = q.where(Course.course_type == course_type)
        except Exception:
            pass

    is_enabled = params.get("is_enabled")
    if is_enabled is not None:
        if isinstance(is_enabled, str):
            v = is_enabled.strip().lower()
            if v in ("1", "true", "yes", "y"):
                q = q.where(Course.is_enabled.is_(True))
            elif v in ("0", "false", "no", "n"):
                q = q.where(Course.is_enabled.is_(False))
        elif isinstance(is_enabled, bool):
            q = q.where(Course.is_enabled.is_(is_enabled))

    enabled_first = case((Course.is_enabled.is_(True), 0), else_=1)

    q = q.order_by(
        enabled_first.asc(),
        Course.created_at.desc(),
        func.lower(Course.name).asc(),
        Course.id.desc(),
    )
    return q
