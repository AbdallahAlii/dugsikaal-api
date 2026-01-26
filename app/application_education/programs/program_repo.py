from __future__ import annotations

from typing import Optional, List, Set

from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from config.database import db
from app.application_education.core.base_repo import BaseEducationRepo
from app.application_education.programs.models.program_models import Program, Course, ProgramCourse


class ProgramRepo(BaseEducationRepo[Program]):
    def __init__(self, session: Optional[Session] = None):
        super().__init__(Program, session or db.session)

    def name_exists(self, company_id: int, name: str, *, exclude_id: Optional[int] = None) -> bool:
        stmt = select(Program.id).where(
            Program.company_id == int(company_id),
            func.lower(Program.name) == func.lower(name.strip()),
        )
        if exclude_id:
            stmt = stmt.where(Program.id != int(exclude_id))
        return self.s.scalar(stmt) is not None

    def get_with_courses(self, program_id: int) -> Optional[Program]:
        stmt = (
            select(Program)
            .options(selectinload(Program.courses).selectinload(ProgramCourse.course))
            .where(Program.id == int(program_id))
        )
        return self.s.scalar(stmt)

    def programs_with_groups(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        try:
            from app.application_education.groups.student_group_model import StudentGroup
        except Exception:
            return set()
        stmt = select(StudentGroup.program_id).where(StudentGroup.program_id.in_(ids)).distinct()
        return set(int(x) for x in self.s.scalars(stmt).all())

    def programs_with_enrollments(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        try:
            from app.application_education.enrollments.enrollment_model import ProgramEnrollment
        except Exception:
            return set()
        stmt = select(ProgramEnrollment.program_id).where(ProgramEnrollment.program_id.in_(ids)).distinct()
        return set(int(x) for x in self.s.scalars(stmt).all())


class CourseRepo(BaseEducationRepo[Course]):
    def __init__(self, session: Optional[Session] = None):
        super().__init__(Course, session or db.session)

    def name_exists(self, company_id: int, name: str, *, exclude_id: Optional[int] = None) -> bool:
        stmt = select(Course.id).where(
            Course.company_id == int(company_id),
            func.lower(Course.name) == func.lower(name.strip()),
        )
        if exclude_id:
            stmt = stmt.where(Course.id != int(exclude_id))
        return self.s.scalar(stmt) is not None

    def existing_course_ids_in_company(self, *, company_id: int, course_ids: List[int]) -> Set[int]:
        if not course_ids:
            return set()
        stmt = (
            select(Course.id)
            .where(Course.company_id == int(company_id))
            .where(Course.id.in_([int(x) for x in course_ids]))
        )
        return set(int(x) for x in self.s.scalars(stmt).all())

    def courses_with_program_links(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        stmt = select(ProgramCourse.course_id).where(ProgramCourse.course_id.in_(ids)).distinct()
        return set(int(x) for x in self.s.scalars(stmt).all())


class ProgramCourseRepo(BaseEducationRepo[ProgramCourse]):
    def __init__(self, session: Optional[Session] = None):
        super().__init__(ProgramCourse, session or db.session)

    def delete_for_program(self, program_id: int) -> int:
        q = self.s.query(ProgramCourse).filter(ProgramCourse.program_id == int(program_id))
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)
