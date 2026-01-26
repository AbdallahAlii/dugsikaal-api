from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.application_education.programs.models.program_models import ProgramTypeEnum, CourseTypeEnum


# ----------------------------
# Program -> child table item (minimal, strict)
# Only allow: course_id + is_mandatory
# ----------------------------
class ProgramCourseMiniIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: int
    is_mandatory: bool = True


# ----------------------------
# Program
# company_id is from ctx (NOT payload)
# required fields: name + program_type
# ----------------------------
class ProgramCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    program_type: ProgramTypeEnum
    is_enabled: bool = True

    # Optional child table on create
    courses: List[ProgramCourseMiniIn] = Field(default_factory=list)


class ProgramUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    program_type: Optional[ProgramTypeEnum] = None
    is_enabled: Optional[bool] = None

    # If provided -> REPLACE full child table (ERPNext style)
    courses: Optional[List[ProgramCourseMiniIn]] = None


# ----------------------------
# Course
# company_id is from ctx (NOT payload)
# ----------------------------
class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    course_type: CourseTypeEnum = CourseTypeEnum.CORE
    credit_hours: Optional[int] = None
    description: Optional[str] = None
    is_enabled: bool = True


class CourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    course_type: Optional[CourseTypeEnum] = None
    credit_hours: Optional[int] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None


# ----------------------------
# Bulk delete
# ----------------------------
class BulkIds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: List[int]
