from __future__ import annotations

from datetime import date
from typing import Optional, List

from pydantic import BaseModel, Field, validator


# ----------------------------
# Program Enrollment
# ----------------------------
class ProgramEnrollmentCreate(BaseModel):
    # minimal required
    student_id: int
    program_id: int
    academic_year_id: int
    branch_id: int

    # optional
    academic_term_id: Optional[int] = None
    batch_id: Optional[int] = None
    student_group_id: Optional[int] = None

    application_date: Optional[date] = None
    admission_date: Optional[date] = None
    enrollment_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None
    remarks: Optional[str] = None

    # UI flow:
    # - Draft by default
    # - if submit=True => set Enrolled and create/enroll courses too
    submit: bool = False

    # Enrolled courses: optional
    enrolled_course_ids: List[int] = Field(default_factory=list)

    @validator("enrolled_course_ids")
    def _course_ids_int(cls, v):
        return [int(x) for x in (v or [])]


class ProgramEnrollmentUpdate(BaseModel):
    # patch update
    academic_term_id: Optional[int] = None
    batch_id: Optional[int] = None
    student_group_id: Optional[int] = None

    application_date: Optional[date] = None
    admission_date: Optional[date] = None
    enrollment_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None
    remarks: Optional[str] = None

    # optional changes
    enrollment_status: Optional[str] = None
    result_status: Optional[str] = None

    # Draft -> Enrolled (preferred UI action)
    submit: Optional[bool] = None

    # allow add/replace course list on update
    enrolled_course_ids: Optional[List[int]] = None

    @validator("enrolled_course_ids")
    def _course_ids_int(cls, v):
        if v is None:
            return None
        return [int(x) for x in v]


# ----------------------------
# Course Enrollment (manual)
# ----------------------------
class CourseEnrollmentCreate(BaseModel):
    student_id: int
    course_id: int
    academic_year_id: int
    branch_id: int

    academic_term_id: Optional[int] = None
    program_enrollment_id: Optional[int] = None

    enrollment_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None
    remarks: Optional[str] = None

    # default Draft, submit => Enrolled
    submit: bool = False


class CourseEnrollmentUpdate(BaseModel):
    academic_term_id: Optional[int] = None
    program_enrollment_id: Optional[int] = None

    enrollment_status: Optional[str] = None
    enrollment_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None
    remarks: Optional[str] = None

    submit: Optional[bool] = None


# ----------------------------
# Bulk delete
# ----------------------------
class BulkDeleteIn(BaseModel):
    ids: List[int]

    @validator("ids")
    def _ids_required(cls, v):
        if not v:
            raise ValueError("At least one id is required.")
        return [int(x) for x in v]
