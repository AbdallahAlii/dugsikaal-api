from __future__ import annotations

from typing import Optional

from sqlalchemy import select, case, false, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.programs.models.program_models import Program, Course


def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def _empty_program_list():
    return select(Program.id.label("id")).where(false())


def _empty_course_list():
    return select(Course.id.label("id")).where(false())


def build_programs_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Programs.

    Fields:
      - id, name, program_type, is_enabled

    Smart order:
      1) Enabled first
      2) Newest first (created_at desc)
      3) Name asc
      4) ID desc
    """
    co_id = _co(context)
    if not co_id:
        return _empty_program_list()

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return _empty_program_list()

    enabled_first = case((Program.is_enabled.is_(True), 0), else_=1)

    q = (
        select(
            Program.id.label("id"),
            Program.name.label("name"),
            Program.program_type.label("program_type"),
            Program.is_enabled.label("is_enabled"),
            Program.created_at.label("created_at"),
        )
        .select_from(Program)
        .where(Program.company_id == int(co_id))
        .order_by(
            enabled_first.asc(),
            Program.created_at.desc(),
            func.lower(Program.name).asc(),
            Program.id.desc(),
        )
    )
    return q


def build_courses_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of Courses.

    Fields:
      - id, name, course_type, is_enabled
    """
    co_id = _co(context)
    if not co_id:
        return _empty_course_list()

    try:
        ensure_scope_by_ids(context=context, target_company_id=int(co_id), target_branch_id=None)
    except Forbidden:
        return _empty_course_list()

    enabled_first = case((Course.is_enabled.is_(True), 0), else_=1)

    q = (
        select(
            Course.id.label("id"),
            Course.name.label("name"),
            Course.course_type.label("course_type"),
            Course.is_enabled.label("is_enabled"),
            Course.created_at.label("created_at"),
        )
        .select_from(Course)
        .where(Course.company_id == int(co_id))
        .order_by(
            enabled_first.asc(),
            Course.created_at.desc(),
            func.lower(Course.name).asc(),
            Course.id.desc(),
        )
    )
    return q
