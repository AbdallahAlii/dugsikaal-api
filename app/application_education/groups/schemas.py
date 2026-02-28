# app/application_education/groups/schemas.py
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, validator


# ----------------------------
# Batch
# ----------------------------
class BatchCreate(BaseModel):
    branch_id: Optional[int] = None
    batch_name: str

class BatchUpdate(BaseModel):
    branch_id: Optional[int] = None
    batch_name: Optional[str] = None
    is_enabled: Optional[bool] = None


# ----------------------------
# Student Category
# ----------------------------
class StudentCategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False

class StudentCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    is_enabled: Optional[bool] = None


# ----------------------------
# Student Group (Frappe-style: master only)
# ----------------------------
class StudentGroupCreate(BaseModel):
    # company_id may be provided but service will enforce scope anyway
    company_id: Optional[int] = None

    program_id: int
    academic_year_id: int
    group_based_on: str
    name: str

    academic_term_id: Optional[int] = None
    branch_id: Optional[int] = None

    batch_id: Optional[int] = None
    section_id: Optional[int] = None
    student_category_id: Optional[int] = None

    capacity: Optional[int] = None
    is_enabled: bool = True

class StudentGroupUpdate(BaseModel):
    name: Optional[str] = None
    academic_term_id: Optional[int] = None
    batch_id: Optional[int] = None
    section_id: Optional[int] = None
    student_category_id: Optional[int] = None
    capacity: Optional[int] = None
    is_enabled: Optional[bool] = None


# ----------------------------
# Get Students (button)
# ----------------------------
class GetStudentsIn(BaseModel):
    academic_year_id: int
    academic_term_id: Optional[int] = None
    program_id: Optional[int] = None
    batch_id: Optional[int] = None
    student_category_id: Optional[int] = None
    course_id: Optional[int] = None  # optional future support


# ----------------------------
# Save Students list (final roster)
# ----------------------------
class SaveStudentsIn(BaseModel):
    effective_on: date
    students: List[int] = Field(default_factory=list)

    @validator("students")
    def _uniq(cls, v):
        # prevent duplicates in one payload
        ids = [int(x) for x in (v or []) if x]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate student ids found in payload.")
        return ids


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