from __future__ import annotations

from typing import Dict, Any, Optional, Union

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.institution.academic_model import (
    EducationSettings,
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)

# Import date helper for formatting
from app.common.date_utils import format_date_out


# --------------------------
# resolvers
# --------------------------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_id_or_name(s: Session, ctx: AffiliationContext, v: str) -> Union[int, str]:
    """
    Resolve either ID (integer) or name (string).
    Returns the value as-is for the loader to handle.
    """
    vv = (v or "").strip()
    if vv.isdigit():
        return int(vv)
    return vv



def resolve_company_from_ctx(_: Session, ctx: AffiliationContext, __: str) -> int:
    """
    Resolve company_id from auth context.
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id and not getattr(ctx, "is_system_admin", False):
        raise Forbidden("Company context is required.")
    if not co_id:
        raise BadRequest("Company context is required.")
    return int(co_id)


# --------------------------
# tiny helpers
# --------------------------
def _status_slug(v) -> str:
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return (s or "draft").lower()


def _ensure_company_scope(ctx: AffiliationContext, company_id: int) -> None:
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


# --------------------------
# loaders
# --------------------------
def load_academic_year_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Load academic year detail by ID or name.
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    # Build query based on identifier type
    query = select(
        AcademicYear.id,
        AcademicYear.company_id,
        AcademicYear.name,
        AcademicYear.start_date,
        AcademicYear.end_date,
        AcademicYear.is_current,
        AcademicYear.status,
        AcademicYear.created_at,
        AcademicYear.updated_at,
    ).where(
        AcademicYear.company_id == int(co_id)
    )

    # Filter by ID or name
    if isinstance(identifier, int):
        query = query.where(AcademicYear.id == identifier)
    else:
        query = query.where(AcademicYear.name == identifier)

    row = s.execute(query).mappings().first()

    if not row:
        raise NotFound("Academic year not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))

    # Format dates using helper
    start_date = format_date_out(row["start_date"])
    end_date = format_date_out(row["end_date"])
    created_at = format_date_out(row["created_at"]) if row["created_at"] else None
    updated_at = format_date_out(row["updated_at"]) if row["updated_at"] else None

    return {
        "id": int(row["id"]),
        "company_id": int(row["company_id"]),
        "name": row["name"],
        "start_date": start_date,
        "end_date": end_date,
        "is_current": bool(row["is_current"]),
        "status": _status_slug(row["status"]),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def load_academic_term_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Load academic term detail by ID or name.
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    # Build query based on identifier type
    query = (
        select(
            AcademicTerm.id,
            AcademicTerm.company_id,
            AcademicTerm.academic_year_id,
            AcademicTerm.name,
            AcademicTerm.start_date,
            AcademicTerm.end_date,
            AcademicTerm.status,
            AcademicTerm.created_at,
            AcademicTerm.updated_at,
            AcademicYear.name.label("academic_year_name"),
        )
        .select_from(AcademicTerm)
        .outerjoin(AcademicYear, AcademicYear.id == AcademicTerm.academic_year_id)
        .where(AcademicTerm.company_id == int(co_id))
    )

    # Filter by ID or name
    if isinstance(identifier, int):
        query = query.where(AcademicTerm.id == identifier)
    else:
        query = query.where(AcademicTerm.name == identifier)

    row = s.execute(query).mappings().first()

    if not row:
        raise NotFound("Academic term not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))

    # Format dates using helper
    start_date = format_date_out(row["start_date"])
    end_date = format_date_out(row["end_date"])
    created_at = format_date_out(row["created_at"]) if row["created_at"] else None
    updated_at = format_date_out(row["updated_at"]) if row["updated_at"] else None

    return {
        "id": int(row["id"]),
        "company_id": int(row["company_id"]),
        "academic_year": {
            "id": int(row["academic_year_id"]) if row["academic_year_id"] else None,
            "name": row["academic_year_name"],
        },
        "name": row["name"],
        "start_date": start_date,
        "end_date": end_date,
        "status": _status_slug(row["status"]),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def load_education_settings_detail(s: Session, ctx: AffiliationContext, company_id: int) -> Dict[str, Any]:
    """
    Detail-only (no list).

    Returns EducationSettings fields with names for referenced IDs.
    """
    _ensure_company_scope(ctx, int(company_id))

    # First, get the education settings
    settings = s.execute(
        select(
            EducationSettings.id,
            EducationSettings.company_id,
            EducationSettings.default_academic_year_id,
            EducationSettings.default_academic_term_id,
            EducationSettings.validate_batch_in_student_group,
            EducationSettings.attendance_based_on_course_schedule,
            EducationSettings.working_days,
            EducationSettings.weekly_off_days,
            EducationSettings.default_holiday_list_id,
            EducationSettings.created_at,
            EducationSettings.updated_at,
        ).where(EducationSettings.company_id == int(company_id))
    ).mappings().first()

    if not settings:
        raise NotFound("Education settings not found.")

    # Get default academic year name if ID exists
    default_academic_year = None
    if settings["default_academic_year_id"]:
        year = s.execute(
            select(AcademicYear.id, AcademicYear.name)
            .where(AcademicYear.id == settings["default_academic_year_id"])
        ).mappings().first()
        if year:
            default_academic_year = {
                "id": int(year["id"]),
                "name": year["name"]
            }

    # Get default academic term name if ID exists
    default_academic_term = None
    if settings["default_academic_term_id"]:
        term = s.execute(
            select(AcademicTerm.id, AcademicTerm.name)
            .where(AcademicTerm.id == settings["default_academic_term_id"])
        ).mappings().first()
        if term:
            default_academic_term = {
                "id": int(term["id"]),
                "name": term["name"]
            }

    # Get default holiday list name if ID exists
    default_holiday_list = None
    if settings["default_holiday_list_id"]:
        # Assuming you have a HolidayList model
        # Import it if you have it, otherwise handle appropriately
        try:
            from app.application_hr.hr_models import HolidayList
            holiday = s.execute(
                select(HolidayList.id, HolidayList.name)
                .where(HolidayList.id == settings["default_holiday_list_id"])
            ).mappings().first()
            if holiday:
                default_holiday_list = {
                    "id": int(holiday["id"]),
                    "name": holiday["name"]
                }
        except ImportError:
            # If HolidayList model doesn't exist, just use the ID
            default_holiday_list = {
                "id": settings["default_holiday_list_id"],
                "name": None
            }

    # Format dates for settings
    created_at = format_date_out(settings["created_at"]) if settings["created_at"] else None
    updated_at = format_date_out(settings["updated_at"]) if settings["updated_at"] else None

    return {
        "id": int(settings["id"]),
        "company_id": int(settings["company_id"]),
        "default_academic_year": default_academic_year,
        "default_academic_term": default_academic_term,
        "default_holiday_list": default_holiday_list,
        "validate_batch_in_student_group": bool(settings["validate_batch_in_student_group"]),
        "attendance_based_on_course_schedule": bool(settings["attendance_based_on_course_schedule"]),
        "working_days": settings["working_days"],
        "weekly_off_days": settings["weekly_off_days"],
        "created_at": created_at,
        "updated_at": updated_at,
    }