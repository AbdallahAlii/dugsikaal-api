# app/hr/schemas.py
from __future__ import annotations
from typing import Optional, List, Dict
from datetime import date
from pydantic import BaseModel, Field, validator

from app.common.models.base import StatusEnum


# ----- inputs -----
class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    personal_email: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    date_of_joining: Optional[date] = None
    sex: Optional[str] = None
    status: Optional[StatusEnum] = None  # Can be ACTIVE/INACTIVE
    emergency_contacts: Optional[List[EmployeeEmergencyContactCreate]] = None
    assignments: Optional[List[EmployeeAssignmentCreate]] = None
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
    # Minimal required + optional fields
    code: Optional[str] = None  # if omitted, we will auto-generate with HR-EMP
    full_name: str
    company_id: Optional[int] = None  # if omitted, taken from current user's company
    personal_email: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[date] = None
    date_of_joining: date
    sex: Optional[str] = None  # GenderEnum by name, or None
    assignments: List[EmployeeAssignmentCreate]
    emergency_contacts: Optional[List[EmployeeEmergencyContactCreate]] = None

    @validator("assignments")
    def _at_least_one_assignment(cls, v):
        if not v:
            raise ValueError("At least one assignment is required.")
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
