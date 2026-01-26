from __future__ import annotations

from datetime import date
from typing import Optional, List

from pydantic import BaseModel, Field, validator

from app.common.models.base import PersonRelationshipEnum


# ----------------------------
# Guardian
# ----------------------------
class GuardianCreate(BaseModel):
    branch_id: int
    guardian_code: Optional[str] = None
    guardian_name: str

    email_address: Optional[str] = None
    mobile_number: Optional[str] = None
    alternate_number: Optional[str] = None

    date_of_birth: Optional[date] = None
    education: Optional[str] = None
    occupation: Optional[str] = None
    work_address: Optional[str] = None

    create_user: bool = False  # optional


class GuardianUpdate(BaseModel):
    guardian_name: Optional[str] = None
    email_address: Optional[str] = None
    mobile_number: Optional[str] = None
    alternate_number: Optional[str] = None

    date_of_birth: Optional[date] = None
    education: Optional[str] = None
    occupation: Optional[str] = None
    work_address: Optional[str] = None

    create_user: Optional[bool] = None  # if True and no user yet -> create


# ----------------------------
# StudentGuardian link input
# ----------------------------
class StudentGuardianLinkIn(BaseModel):
    guardian_id: int
    relationship: PersonRelationshipEnum
    is_primary: bool = False


# ----------------------------
# Student
# ----------------------------
class StudentCreate(BaseModel):
    branch_id: int
    student_code: Optional[str] = None
    full_name: str

    joining_date: Optional[date] = None
    student_email: Optional[str] = None
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = None  # accept enum name/value
    student_mobile_number: Optional[str] = None
    gender: Optional[str] = None       # accept enum name/value
    nationality: Optional[str] = None
    orphan_status: Optional[str] = None  # accept enum name/value

    create_user: bool = False  # optional
    guardians: List[StudentGuardianLinkIn] = Field(default_factory=list)


class StudentUpdate(BaseModel):
    is_enabled: Optional[bool] = None

    full_name: Optional[str] = None
    joining_date: Optional[date] = None
    student_email: Optional[str] = None
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = None
    student_mobile_number: Optional[str] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    orphan_status: Optional[str] = None

    date_of_leaving: Optional[date] = None
    leaving_certificate_number: Optional[str] = None
    reason_for_leaving: Optional[str] = None

    create_user: Optional[bool] = None  # if True and no user yet -> create

    # Add more guardians (append mode)
    guardians_add: Optional[List[StudentGuardianLinkIn]] = None


# ----------------------------
# Bulk delete input
# ----------------------------
class BulkDeleteIn(BaseModel):
    ids: List[int]

    @validator("ids")
    def _ids_required(cls, v):
        if not v:
            raise ValueError("At least one id is required.")
        return v
