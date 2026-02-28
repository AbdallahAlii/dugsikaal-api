from __future__ import annotations

from typing import Dict, Any, Optional, Union, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.common.date_utils import format_date_out

from app.application_education.programs.models.program_models import Program, Course, ProgramCourse


# --------------------------
# resolvers (detail identifier)
# --------------------------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_name_strict(_: Session, __: AffiliationContext, v: str) -> str:
    vv = (v or "").strip()
    if not vv:
        raise BadRequest("Invalid identifier.")
    return vv


def resolve_id_or_name(_: Session, __: AffiliationContext, v: str) -> Union[int, str]:
    vv = (v or "").strip()
    if not vv:
        raise BadRequest("Invalid identifier.")
    if vv.isdigit():
        return int(vv)
    return vv


# --------------------------
# helpers
# --------------------------
def _ensure_company_scope(ctx: AffiliationContext, company_id: int) -> None:
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def _status_bool_to_label(is_enabled: bool) -> str:
    return "Enabled" if bool(is_enabled) else "Disabled"


def _enum_value(v) -> Optional[str]:
    if v is None:
        return None
    return getattr(v, "value", str(v))


def _fd(v):
    return format_date_out(v) if v else None


# --------------------------
# Program Detail Loader
# --------------------------
def load_program_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Program detail by ID or name (default_by=name).
    Includes Curriculum (ProgramCourse + Course).
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    q = (
        select(
            Program.id,
            Program.company_id,
            Program.name,
            Program.program_type,
            Program.is_enabled,
            Program.created_at,
            Program.updated_at,
        )
        .select_from(Program)
        .where(Program.company_id == int(co_id))
    )

    if isinstance(identifier, int):
        q = q.where(Program.id == int(identifier))
    else:
        q = q.where(func.lower(Program.name) == func.lower(str(identifier)))

    row = s.execute(q).mappings().first()
    if not row:
        raise NotFound("Program not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))
    program_id = int(row["id"])

    # ---- Curriculum (ProgramCourse + Course) ----
    cq = (
        select(
            ProgramCourse.id.label("link_id"),
            ProgramCourse.course_id.label("course_id"),
            Course.name.label("course_name"),
            ProgramCourse.is_mandatory.label("is_mandatory"),
            ProgramCourse.sequence_no.label("sequence_no"),
            ProgramCourse.curriculum_version.label("curriculum_version"),
            ProgramCourse.effective_start.label("effective_start"),
            ProgramCourse.effective_end.label("effective_end"),
        )
        .select_from(ProgramCourse)
        .join(Course, Course.id == ProgramCourse.course_id)
        .where(ProgramCourse.program_id == program_id)
        .order_by(
            ProgramCourse.curriculum_version.desc(),
            ProgramCourse.sequence_no.asc().nulls_last(),
            func.lower(Course.name).asc(),
            ProgramCourse.id.desc(),
        )
    )

    curriculum: List[Dict[str, Any]] = []
    for r in s.execute(cq).mappings().all():
        curriculum.append({
            "id": int(r["link_id"]),
            "course": {"id": int(r["course_id"]), "name": r["course_name"]},
            "is_mandatory": bool(r["is_mandatory"]),
            "sequence_no": int(r["sequence_no"]) if r["sequence_no"] is not None else None,
            "curriculum_version": int(r["curriculum_version"]),
            "effective_start": _fd(r["effective_start"]),
            "effective_end": _fd(r["effective_end"]),
        })

    return {
        "id": program_id,
        "name": row["name"],
        "program_type": _enum_value(row["program_type"]),
        "status": _status_bool_to_label(bool(row["is_enabled"])),
        "is_enabled": bool(row["is_enabled"]),
        "curriculum": curriculum,
        "created_at": _fd(row["created_at"]),
        "updated_at": _fd(row["updated_at"]),
    }


# --------------------------
# Course Detail Loader
# --------------------------
def load_course_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Course detail by ID or name (default_by=name).
    Includes "used_in_programs" (ProgramCourse + Program).
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    q = (
        select(
            Course.id,
            Course.company_id,
            Course.name,
            Course.course_type,
            Course.credit_hours,
            Course.description,
            Course.is_enabled,
            Course.created_at,
            Course.updated_at,
        )
        .select_from(Course)
        .where(Course.company_id == int(co_id))
    )

    if isinstance(identifier, int):
        q = q.where(Course.id == int(identifier))
    else:
        q = q.where(func.lower(Course.name) == func.lower(str(identifier)))

    row = s.execute(q).mappings().first()
    if not row:
        raise NotFound("Course not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))
    course_id = int(row["id"])

    # ---- used in programs ----
    pq = (
        select(
            ProgramCourse.id.label("link_id"),
            ProgramCourse.program_id.label("program_id"),
            Program.name.label("program_name"),
            Program.program_type.label("program_type"),
            ProgramCourse.is_mandatory.label("is_mandatory"),
            ProgramCourse.sequence_no.label("sequence_no"),
            ProgramCourse.curriculum_version.label("curriculum_version"),
        )
        .select_from(ProgramCourse)
        .join(Program, Program.id == ProgramCourse.program_id)
        .where(ProgramCourse.course_id == course_id)
        .order_by(
            ProgramCourse.curriculum_version.desc(),
            func.lower(Program.name).asc(),
            ProgramCourse.id.desc(),
        )
    )

    used_in_programs: List[Dict[str, Any]] = []
    for r in s.execute(pq).mappings().all():
        used_in_programs.append({
            "id": int(r["link_id"]),
            "program": {
                "id": int(r["program_id"]),
                "name": r["program_name"],
                "program_type": _enum_value(r["program_type"]),
            },
            "is_mandatory": bool(r["is_mandatory"]),
            "sequence_no": int(r["sequence_no"]) if r["sequence_no"] is not None else None,
            "curriculum_version": int(r["curriculum_version"]),
        })

    return {
        "id": course_id,
        "name": row["name"],
        "course_type": _enum_value(row["course_type"]),
        "status": _status_bool_to_label(bool(row["is_enabled"])),
        "is_enabled": bool(row["is_enabled"]),
        "course_information": {
            "credit_hours": int(row["credit_hours"]) if row["credit_hours"] is not None else None,
            "description": row["description"],
        },
        "used_in_programs": used_in_programs,
        "created_at": _fd(row["created_at"]),
        "updated_at": _fd(row["updated_at"]),
    }
