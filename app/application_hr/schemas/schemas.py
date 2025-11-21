# app/hr/schemas.py
from __future__ import annotations
from typing import Optional, List, Dict
from datetime import date, datetime
from pydantic import BaseModel, Field, validator

from app.application_hr.models.hr import EmploymentTypeEnum, AttendanceStatusEnum, CheckinLogTypeEnum, CheckinSourceEnum
from app.common.models.base import StatusEnum


# ----- inputs -----
class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    personal_email: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    date_of_joining: Optional[date] = None
    sex: Optional[str] = None
    status: Optional[StatusEnum] = None
    employment_type: Optional[EmploymentTypeEnum] = None
    holiday_list_id: Optional[int] = None
    default_shift_type_id: Optional[int] = None
    emergency_contacts: Optional[List["EmployeeEmergencyContactCreate"]] = None
    assignments: Optional[List["EmployeeAssignmentCreate"]] = None
    img_key: Optional[str] = None

    @validator("assignments")
    def _at_least_one_assignment(cls, v):
        if v and not any(getattr(a, "is_primary", False) for a in v):
            raise ValueError("At least one primary assignment is required.")
        return v

class EmployeeAssignmentCreate(BaseModel):
    branch_id: int
    from_date: date
    is_primary: bool = False
    department_id: Optional[int] = None
    job_title: Optional[str] = None
    extra: Dict = Field(default_factory=dict)

class EmployeeEmergencyContactCreate(BaseModel):
    full_name: str
    relationship_type: str  # PersonRelationshipEnum by name
    phone_number: str


class EmployeeCreate(BaseModel):
    code: Optional[str] = None
    full_name: str
    company_id: Optional[int] = None  # optional: resolved from branch
    personal_email: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    date_of_joining: date
    sex: Optional[str] = None  # GenderEnum by name
    employment_type: Optional[EmploymentTypeEnum] = None
    holiday_list_id: Optional[int] = None
    default_shift_type_id: Optional[int] = None

    assignments: List["EmployeeAssignmentCreate"]
    emergency_contacts: Optional[List["EmployeeEmergencyContactCreate"]] = None

    @validator("assignments")
    def _at_least_one_assignment(cls, v):
        if not v:
            raise ValueError("At least one assignment is required.")
        if not any(a.is_primary for a in v):
            raise ValueError("At least one primary assignment is required.")
        return v


# ----- outputs -----

class CreatedUserOut(BaseModel):
    id: int
    username: str
    temp_password: Optional[str] = None  # only returned at creation time
class EmployeeMinimalOut(BaseModel):
    id: int
    code: str


class EmployeeCreateResponse(BaseModel):
    message: str = "Employee created successfully"
    employee: EmployeeMinimalOut # Change from EmployeeOut to the new class
# ----------------------------
# Holiday List + Holidays
# ----------------------------

class HolidayIn(BaseModel):
    holiday_date: date
    description: Optional[str] = None
    is_full_day: bool = True
    is_weekly_off: bool = False


class HolidayListCreate(BaseModel):
    company_id: Optional[int] = None  # if None, use context company
    name: str
    from_date: date
    to_date: date
    is_default: bool = False
    holidays: List[HolidayIn] = Field(default_factory=list)


class HolidayListUpdate(BaseModel):
    name: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    is_default: Optional[bool] = None
    holidays: Optional[List[HolidayIn]] = None


# ----------------------------
# Shift Type + Assignment
# ----------------------------

class ShiftTypeCreate(BaseModel):
    company_id: Optional[int] = None
    name: str
    start_time: str  # "HH:MM"
    end_time: str    # "HH:MM"
    enable_auto_attendance: bool = False
    process_attendance_after: Optional[date] = None
    is_night_shift: bool = False
    holiday_list_id: Optional[int] = None


class ShiftTypeUpdate(BaseModel):
    name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    enable_auto_attendance: Optional[bool] = None
    process_attendance_after: Optional[date] = None
    is_night_shift: Optional[bool] = None
    holiday_list_id: Optional[int] = None


class ShiftAssignmentCreate(BaseModel):
    employee_id: int
    company_id: Optional[int] = None
    shift_type_id: int
    from_date: date
    to_date: Optional[date] = None
    is_active: bool = True


class ShiftAssignmentUpdate(BaseModel):
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    is_active: Optional[bool] = None


# ----------------------------
# Attendance (manual input)
# ----------------------------

class AttendanceCreate(BaseModel):
    employee_id: int
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    attendance_date: date
    status: AttendanceStatusEnum
    shift_type_id: Optional[int] = None
    in_time: Optional[datetime] = None
    out_time: Optional[datetime] = None
    remarks: Optional[str] = None


# ----------------------------
# Employee Checkin (device/API)
# ----------------------------

class EmployeeCheckinCreate(BaseModel):
    """
    Generic checkin payload for both manual and device-based logs.
    You can send either employee_id or employee_code.
    """
    company_id: Optional[int] = None
    employee_id: Optional[int] = None
    employee_code: Optional[str] = None  # map to Employee.code
    log_time: datetime
    log_type: CheckinLogTypeEnum
    source: CheckinSourceEnum = CheckinSourceEnum.DEVICE
    device_id: Optional[str] = None
    raw_payload: Dict = Field(default_factory=dict)

    @validator("employee_id", always=True)
    def _require_some_employee_identifier(cls, v, values):
        if v is None and not values.get("employee_code"):
            raise ValueError("Either employee_id or employee_code is required.")
        return v