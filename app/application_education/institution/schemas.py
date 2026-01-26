
from __future__ import annotations
from datetime import date
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator
from app.application_education.institution.academic_model import AcademicStatusEnum
from app.common.date_utils import parse_date_flex, ACCEPTED_FORMATS_HUMAN

_VALID_DAYS = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}

def _normalize_weekdays(v: str) -> str:
    parts = [p.strip().upper() for p in v.split(",") if p.strip()]
    for day in parts:
        if day not in _VALID_DAYS:
            raise ValueError(f"Invalid weekday: {day}")
    return ",".join(parts)

def _coerce_date(v: Any) -> date:
    """
    Accept strings in multiple formats (and some structured values),
    return python date, else raise ValueError.
    """
    if isinstance(v, date):
        return v
    d = parse_date_flex(v)
    if not d:
        raise ValueError(f"Invalid date format. Accepted: {ACCEPTED_FORMATS_HUMAN}")
    return d

def _coerce_status(v: Any) -> Any:
    """
    Accept:
      - AcademicStatusEnum
      - 'open'/'draft'/'closed'
      - 'Open'/'Draft'/'Closed'
      - 'OPEN'/'DRAFT'/'CLOSED'
    Return:
      - AcademicStatusEnum (preferred) OR exact enum value string
    """
    if v is None or v == "":
        return None

    if isinstance(v, AcademicStatusEnum):
        return v

    s = str(v).strip()

    # normalize
    s_lower = s.lower()

    mapping = {
        "open": AcademicStatusEnum.OPEN,
        "opened": AcademicStatusEnum.OPEN,
        "close": AcademicStatusEnum.CLOSED,
        "closed": AcademicStatusEnum.CLOSED,
        "draft": AcademicStatusEnum.DRAFT,
    }

    if s_lower in mapping:
        return mapping[s_lower]

    # try TitleCase fallback: "Open"/"Closed"/"Draft"
    s_title = s_lower.title()
    if s_title in ("Open", "Closed", "Draft"):
        return AcademicStatusEnum(s_title)

    # Let Pydantic raise a clean error
    return s



class EducationSettingsCreate(BaseModel):
    company_id: Optional[int] = None
    default_academic_year_id: Optional[int] = None
    default_academic_term_id: Optional[int] = None
    validate_batch_in_student_group: bool = False
    attendance_based_on_course_schedule: bool = True
    working_days: str = Field(default="SUN,MON,TUE,WED,THU")
    weekly_off_days: str = Field(default="FRI,SAT")
    default_holiday_list_id: Optional[int] = None

    @field_validator("working_days", "weekly_off_days")
    @classmethod
    def validate_weekdays(cls, v: str) -> str:
        return _normalize_weekdays(v)


class EducationSettingsUpdate(BaseModel):
    default_academic_year_id: Optional[int] = None
    default_academic_term_id: Optional[int] = None
    validate_batch_in_student_group: Optional[bool] = None
    attendance_based_on_course_schedule: Optional[bool] = None
    working_days: Optional[str] = None
    weekly_off_days: Optional[str] = None
    default_holiday_list_id: Optional[int] = None

    @field_validator("working_days", "weekly_off_days")
    @classmethod
    def validate_weekdays(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _normalize_weekdays(v)


class AcademicYearCreate(BaseModel):
    company_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date
    is_current: bool = False
    status: AcademicStatusEnum = AcademicStatusEnum.DRAFT

    @field_validator("start_date", mode="before")
    @classmethod
    def start_date_before(cls, v: Any) -> date:
        return _coerce_date(v)

    @field_validator("end_date", mode="before")
    @classmethod
    def end_date_before(cls, v: Any) -> date:
        return _coerce_date(v)

    @field_validator("status", mode="before")
    @classmethod
    def status_before(cls, v: Any) -> Any:
        return _coerce_status(v)

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: date, info) -> date:
        if v < info.data.get("start_date"):
            raise ValueError("End date must be after start date")
        return v


class AcademicYearUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: Optional[bool] = None
    status: Optional[AcademicStatusEnum] = None

    @field_validator("start_date", mode="before")
    @classmethod
    def start_date_before(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return _coerce_date(v)

    @field_validator("end_date", mode="before")
    @classmethod
    def end_date_before(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return _coerce_date(v)

    @field_validator("status", mode="before")
    @classmethod
    def status_before(cls, v: Any) -> Any:
        return _coerce_status(v)

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[date], info) -> Optional[date]:
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("End date must be after start date")
        return v


class AcademicTermCreate(BaseModel):
    company_id: Optional[int] = None
    academic_year_id: int
    name: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date
    status: AcademicStatusEnum = AcademicStatusEnum.DRAFT

    @field_validator("start_date", mode="before")
    @classmethod
    def start_date_before(cls, v: Any) -> date:
        return _coerce_date(v)

    @field_validator("end_date", mode="before")
    @classmethod
    def end_date_before(cls, v: Any) -> date:
        return _coerce_date(v)

    @field_validator("status", mode="before")
    @classmethod
    def status_before(cls, v: Any) -> Any:
        return _coerce_status(v)

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: date, info) -> date:
        if v < info.data.get("start_date"):
            raise ValueError("End date must be after start date")
        return v


class AcademicTermUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[AcademicStatusEnum] = None

    @field_validator("start_date", mode="before")
    @classmethod
    def start_date_before(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return _coerce_date(v)

    @field_validator("end_date", mode="before")
    @classmethod
    def end_date_before(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return _coerce_date(v)

    @field_validator("status", mode="before")
    @classmethod
    def status_before(cls, v: Any) -> Any:
        return _coerce_status(v)

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[date], info) -> Optional[date]:
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("End date must be after start date")
        return v


# Response models (unchanged)
class AcademicYearOut(BaseModel):
    id: int
    company_id: int
    name: str
    start_date: date
    end_date: date
    is_current: bool
    status: AcademicStatusEnum

class AcademicTermOut(BaseModel):
    id: int
    company_id: int
    academic_year_id: int
    name: str
    start_date: date
    end_date: date
    status: AcademicStatusEnum

class EducationSettingsOut(BaseModel):
    id: int
    company_id: int
    default_academic_year_id: Optional[int]
    default_academic_term_id: Optional[int]
    validate_batch_in_student_group: bool
    attendance_based_on_course_schedule: bool
    working_days: str
    weekly_off_days: str
    default_holiday_list_id: Optional[int]
