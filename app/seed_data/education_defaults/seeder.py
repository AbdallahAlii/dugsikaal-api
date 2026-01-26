# # # app/seed_data/education_defaults/seeder.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.application_org.models.company import Company
from app.common.timezone.service import now_in_company_tz
from app.application_hr.models.hr import HolidayList

from app.application_education.institution.academic_model import (
    EducationSettings,
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)

from app.seed_data.core_org.data import DEFAULT_WEEKLY_OFF_DAYS
from .data import (
    ACADEMIC_YEAR_START_MONTH,
    ACADEMIC_YEAR_START_DAY,
    TERM_ONE_LABEL,
    TERM_TWO_LABEL,
    DEFAULT_K12_PROGRAMS,
    DEFAULT_COURSES,
    DEFAULT_STUDENT_CATEGORIES,
    GLOBAL_SECTIONS,
    DEFAULT_SCHOOL_SESSIONS,
    DEFAULT_VALIDATE_BATCH_IN_STUDENT_GROUP,
    DEFAULT_ATTENDANCE_BASED_ON_COURSE_SCHEDULE,
)

logger = logging.getLogger(__name__)

_PY_WEEKDAY_TO_CODE = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_OUTPUT_WEEK_ORDER = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]


# -------------------------------------------------------------------
# Safe imports
# -------------------------------------------------------------------
def _import_program_course_models():
    from app.application_education.programs.models.program_models import (
        Program, Course, ProgramTypeEnum, CourseTypeEnum
    )
    return Program, Course, ProgramTypeEnum, CourseTypeEnum


def _import_groups_models():
    from app.application_education.groups.student_group_model import (
        Section, StudentCategory, StudentGroup
    )
    return Section, StudentCategory, StudentGroup


def _import_timetable_models():
    from app.application_education.timetable.model import SchoolSession, TimeSlot
    return SchoolSession, TimeSlot


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _model_column_names(model) -> set[str]:
    try:
        return {c.name for c in model.__table__.columns}  # type: ignore[attr-defined]
    except Exception:
        return set()


def _filter_model_kwargs(model, data: Dict[str, Any]) -> Dict[str, Any]:
    cols = _model_column_names(model)
    if not cols:
        # fallback: best effort (still remove known bad keys)
        bad = {"periods", "time_slots", "slots"}
        return {k: v for k, v in data.items() if k not in bad}
    return {k: v for k, v in data.items() if k in cols}


def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters):
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False

    payload = {**filters, **(defaults or {})}
    payload = _filter_model_kwargs(model, payload)

    obj = model(**payload)
    db.add(obj)
    db.flush([obj])
    return obj, True


def _build_working_and_off_days() -> Tuple[str, str]:
    off_codes = {_PY_WEEKDAY_TO_CODE[i] for i in DEFAULT_WEEKLY_OFF_DAYS if 0 <= i <= 6}
    working = [c for c in _OUTPUT_WEEK_ORDER if c not in off_codes]
    off = [c for c in _OUTPUT_WEEK_ORDER if c in off_codes]
    return ",".join(working), ",".join(off)


def _get_default_holiday_list_id(db: Session, company_id: int) -> Optional[int]:
    hl = db.scalar(
        select(HolidayList).where(
            HolidayList.company_id == company_id,
            HolidayList.is_default.is_(True),
        )
    )
    return int(hl.id) if hl else None


def _time_to_minutes(t: time) -> int:
    return (t.hour * 60) + t.minute


def _minutes_to_time(m: int) -> time:
    m = max(0, m)
    hh = (m // 60) % 24
    mm = m % 60
    return time(hh, mm)


def _expand_periods_to_rows(
    *,
    periods_value: Any,
    session_start: Optional[time],
    session_end: Optional[time],
) -> List[Dict[str, Any]]:
    """
    Supports:
    - periods = list[dict] with period_number/start_time/end_time
    - periods = int  (auto-split session time evenly into N periods)
    """
    if isinstance(periods_value, list):
        # assume caller already formatted correctly
        out: List[Dict[str, Any]] = []
        for p in periods_value:
            if not isinstance(p, dict):
                continue
            if "period_number" not in p or "start_time" not in p or "end_time" not in p:
                continue
            out.append(p)
        return out

    if isinstance(periods_value, int):
        n = int(periods_value)
        if n <= 0:
            return []

        if not session_start or not session_end:
            # cannot expand without times
            return []

        s = _time_to_minutes(session_start)
        e = _time_to_minutes(session_end)
        if e <= s:
            return []

        total = e - s
        step = total // n
        if step <= 0:
            return []

        rows: List[Dict[str, Any]] = []
        cur = s
        for i in range(1, n + 1):
            nxt = (s + (step * i)) if i < n else e
            rows.append(
                {
                    "period_number": i,
                    "start_time": _minutes_to_time(cur),
                    "end_time": _minutes_to_time(nxt),
                }
            )
            cur = nxt
        return rows

    return []


# -------------------------------------------------------------------
# Academic year (single-year policy)
# -------------------------------------------------------------------
@dataclass(frozen=True)
class AcademicYearWindow:
    start: date
    end: date
    name: str


def _compute_current_academic_year(today: date) -> AcademicYearWindow:
    anchor = date(today.year, ACADEMIC_YEAR_START_MONTH, ACADEMIC_YEAR_START_DAY)
    if today >= anchor:
        sy, ey = today.year, today.year + 1
    else:
        sy, ey = today.year - 1, today.year

    return AcademicYearWindow(
        start=date(sy, ACADEMIC_YEAR_START_MONTH, ACADEMIC_YEAR_START_DAY),
        end=date(ey, 7, 31),
        name=f"{sy}-{ey}",
    )


def _ensure_single_academic_year(db: Session, *, company_id: int, window: AcademicYearWindow) -> AcademicYear:
    ay = db.scalar(select(AcademicYear).where(AcademicYear.company_id == company_id))

    if ay:
        ay.start_date = window.start
        ay.end_date = window.end
        ay.name = window.name
        ay.is_current = True
        ay.status = AcademicStatusEnum.OPEN
    else:
        ay = AcademicYear(
            company_id=company_id,
            name=window.name,
            start_date=window.start,
            end_date=window.end,
            is_current=True,
            status=AcademicStatusEnum.OPEN,
        )
        db.add(ay)
        db.flush([ay])

    # hard guarantee only one current
    db.execute(
        update(AcademicYear)
        .where(AcademicYear.company_id == company_id, AcademicYear.id != ay.id)
        .values(is_current=False)
    )

    return ay


def _ensure_terms(db: Session, *, company_id: int, ay: AcademicYear) -> None:
    # Term One: Aug 1 -> Dec 31 (start year)
    # Term Two: Jan 1 -> Jul 31 (end year)
    sy = ay.start_date.year
    ey = ay.end_date.year

    t1_start = date(sy, 8, 1)
    t1_end = date(sy, 12, 31)
    t2_start = date(ey, 1, 1)
    t2_end = date(ey, 7, 31)

    # idempotent by (company_id, academic_year_id, name)
    _get_or_create(
        db,
        AcademicTerm,
        company_id=company_id,
        academic_year_id=ay.id,
        name=TERM_ONE_LABEL,
        defaults={
            "start_date": t1_start,
            "end_date": t1_end,
            "status": AcademicStatusEnum.OPEN,
            "is_current": True,
        },
    )
    _get_or_create(
        db,
        AcademicTerm,
        company_id=company_id,
        academic_year_id=ay.id,
        name=TERM_TWO_LABEL,
        defaults={
            "start_date": t2_start,
            "end_date": t2_end,
            "status": AcademicStatusEnum.DRAFT,
            "is_current": False,
        },
    )


def _ensure_education_settings(db: Session, *, company_id: int) -> None:
    settings = db.scalar(select(EducationSettings).where(EducationSettings.company_id == company_id))
    if not settings:
        settings = EducationSettings(company_id=company_id)
        db.add(settings)
        db.flush([settings])

    working, off = _build_working_and_off_days()
    hl_id = _get_default_holiday_list_id(db, company_id)

    # Set only if fields exist (safe across model changes)
    if hasattr(settings, "working_days") and getattr(settings, "working_days", None) in (None, ""):
        setattr(settings, "working_days", working)
    if hasattr(settings, "weekly_off_days") and getattr(settings, "weekly_off_days", None) in (None, ""):
        setattr(settings, "weekly_off_days", off)
    if hasattr(settings, "holiday_list_id") and getattr(settings, "holiday_list_id", None) is None and hl_id is not None:
        setattr(settings, "holiday_list_id", hl_id)
    if hasattr(settings, "validate_batch_in_student_group") and getattr(settings, "validate_batch_in_student_group", None) is None:
        setattr(settings, "validate_batch_in_student_group", bool(DEFAULT_VALIDATE_BATCH_IN_STUDENT_GROUP))
    if hasattr(settings, "attendance_based_on_course_schedule") and getattr(settings, "attendance_based_on_course_schedule", None) is None:
        setattr(settings, "attendance_based_on_course_schedule", bool(DEFAULT_ATTENDANCE_BASED_ON_COURSE_SCHEDULE))

    db.flush([settings])


def _seed_k12_groups(
    db: Session,
    *,
    company_id: int,
    academic_year_id: int,
) -> List[int]:
    Program, _, _, _ = _import_program_course_models()
    Section, _, StudentGroup = _import_groups_models()

    section_a, _ = _get_or_create(db, Section, section_name="A")

    programs = db.execute(
        select(Program.id, Program.name).where(
            Program.company_id == company_id
        )
    ).all()
    name_to_id = {name: int(pid) for pid, name in programs}

    # existing keys
    existing = {
        (int(r[0]), int(r[1]))
        for r in db.execute(
            select(StudentGroup.program_id, StudentGroup.section_id).where(
                StudentGroup.company_id == company_id,
                StudentGroup.academic_year_id == academic_year_id,
            )
        ).all()
    }

    created_ids: List[int] = []
    for grade in range(1, 13):
        pname = f"Grade {grade}"
        pid = name_to_id.get(pname)
        if not pid:
            continue

        key = (pid, int(section_a.id))
        if key in existing:
            continue

        sg = StudentGroup(
            company_id=company_id,
            program_id=pid,
            academic_year_id=academic_year_id,
            section_id=int(section_a.id),
            name=f"{pname} - A",
            is_enabled=True,
        )
        db.add(sg)
        db.flush([sg])
        created_ids.append(int(sg.id))

    return created_ids


# -------------------------------------------------------------------
# PUBLIC ENTRYPOINT
# -------------------------------------------------------------------
def seed_education_defaults(db: Session, *, company_id: int) -> Dict[str, Any]:
    """
    PRODUCTION Education Defaults Seeder

    Seeds:
      - Single AcademicYear
      - 2 Terms
      - EducationSettings
      - Programs, Courses, StudentCategories, Sections
      - SchoolSessions + TimeSlots (supports periods list OR periods int)
      - K12 StudentGroups for Section A

    Returns context used by fee seeder.
    """
    logger.info("EducationDefaults: start company_id=%s", company_id)

    company = db.scalar(select(Company).where(Company.id == company_id))
    if not company:
        raise RuntimeError(f"Company {company_id} not found")

    today = now_in_company_tz(db, company_id).date()
    window = _compute_current_academic_year(today)
    ay = _ensure_single_academic_year(db, company_id=company_id, window=window)

    _ensure_terms(db, company_id=company_id, ay=ay)
    _ensure_education_settings(db, company_id=company_id)

    Program, Course, ProgramTypeEnum, CourseTypeEnum = _import_program_course_models()
    Section, StudentCategory, StudentGroup = _import_groups_models()
    SchoolSession, TimeSlot = _import_timetable_models()

    # Programs
    for row in DEFAULT_K12_PROGRAMS:
        _get_or_create(
            db,
            Program,
            company_id=company_id,
            name=row["name"],
            defaults=row,
        )

    # Courses
    for row in DEFAULT_COURSES:
        _get_or_create(
            db,
            Course,
            company_id=company_id,
            name=row["name"],
            defaults=row,
        )

    # Student Categories
    for row in DEFAULT_STUDENT_CATEGORIES:
        _get_or_create(
            db,
            StudentCategory,
            company_id=company_id,
            name=row["name"],
            defaults=row,
        )

    # Sections
    for sec in GLOBAL_SECTIONS:
        _get_or_create(db, Section, section_name=sec)

    # Sessions + TimeSlots
    for row in DEFAULT_SCHOOL_SESSIONS:
        # create session without periods/time_slots keys
        session_defaults = dict(row)
        session_defaults.pop("periods", None)
        session_defaults.pop("time_slots", None)
        session_defaults.pop("slots", None)

        session, _ = _get_or_create(
            db,
            SchoolSession,
            company_id=company_id,
            name=row["name"],
            defaults=session_defaults,
        )

        # Support different schema keys:
        # - periods: list[dict] OR int
        periods_value = row.get("periods")
        if periods_value is None:
            # maybe caller uses another key
            periods_value = row.get("time_slots") or row.get("slots")

        period_rows = _expand_periods_to_rows(
            periods_value=periods_value,
            session_start=getattr(session, "start_time", None),
            session_end=getattr(session, "end_time", None),
        )

        for p in period_rows:
            _get_or_create(
                db,
                TimeSlot,
                company_id=company_id,
                session_id=int(session.id),
                period_number=int(p["period_number"]),
                defaults={
                    "start_time": p["start_time"],
                    "end_time": p["end_time"],
                    "is_enabled": True,
                },
            )

    # Student Groups (Grade 1..12 - A)
    created_group_ids = _seed_k12_groups(
        db,
        company_id=company_id,
        academic_year_id=int(ay.id),
    )

    # Collect program ids for context
    program_ids = [
        int(pid)
        for (pid,) in db.execute(
            select(Program.id).where(Program.company_id == company_id)
        ).all()
    ]

    logger.info(
        "EducationDefaults: done company_id=%s academic_year=%s programs=%s groups_created=%s",
        company_id,
        ay.name,
        len(program_ids),
        len(created_group_ids),
    )

    return {
        "academic_year_id": int(ay.id),
        "program_ids": program_ids,
    }
