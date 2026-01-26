from __future__ import annotations

from datetime import date
from typing import Optional, Iterable, List, Dict, Any, Set, Tuple

from sqlalchemy import select, exists, func
from sqlalchemy.orm import Session

from config.database import db

from app.application_education.student.models import Student
from app.application_education.programs.models.program_models import Program, Course, ProgramCourse
from app.application_education.institution.academic_model import AcademicYear, AcademicTerm
from app.application_education.groups.student_group_model import Batch, StudentGroup
from app.application_org.models.company import Branch

from app.application_education.enrollments.enrollment_model import (
    ProgramEnrollment,
    CourseEnrollment,
)


class EnrollmentRepo:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ----------------------------
    # Safe get helpers (company scoped)
    # ----------------------------
    def get_student(self, *, company_id: int, student_id: int) -> Optional[Student]:
        return self.s.scalar(select(Student).where(Student.company_id == company_id, Student.id == int(student_id)))

    def get_program(self, *, company_id: int, program_id: int) -> Optional[Program]:
        return self.s.scalar(select(Program).where(Program.company_id == company_id, Program.id == int(program_id)))

    def get_course(self, *, company_id: int, course_id: int) -> Optional[Course]:
        return self.s.scalar(select(Course).where(Course.company_id == company_id, Course.id == int(course_id)))

    def get_year(self, *, company_id: int, year_id: int) -> Optional[AcademicYear]:
        return self.s.scalar(select(AcademicYear).where(AcademicYear.company_id == company_id, AcademicYear.id == int(year_id)))

    def get_term(self, *, company_id: int, term_id: int) -> Optional[AcademicTerm]:
        return self.s.scalar(select(AcademicTerm).where(AcademicTerm.company_id == company_id, AcademicTerm.id == int(term_id)))

    def get_branch(self, *, company_id: int, branch_id: int) -> Optional[Branch]:
        # Branch is org model but should have company_id
        return self.s.scalar(select(Branch).where(Branch.company_id == company_id, Branch.id == int(branch_id)))

    def get_batch(self, *, company_id: int, batch_id: int) -> Optional[Batch]:
        return self.s.scalar(select(Batch).where(Batch.company_id == company_id, Batch.id == int(batch_id)))

    def get_group(self, *, company_id: int, group_id: int) -> Optional[StudentGroup]:
        return self.s.scalar(select(StudentGroup).where(StudentGroup.company_id == company_id, StudentGroup.id == int(group_id)))

    # ----------------------------
    # Enrollment fetch (company scoped)
    # ----------------------------
    def get_program_enrollment(self, *, company_id: int, enrollment_id: int) -> Optional[ProgramEnrollment]:
        return self.s.scalar(
            select(ProgramEnrollment).where(
                ProgramEnrollment.company_id == company_id,
                ProgramEnrollment.id == int(enrollment_id),
            )
        )

    def get_course_enrollment(self, *, company_id: int, enrollment_id: int) -> Optional[CourseEnrollment]:
        return self.s.scalar(
            select(CourseEnrollment).where(
                CourseEnrollment.company_id == company_id,
                CourseEnrollment.id == int(enrollment_id),
            )
        )

    # ----------------------------
    # Uniqueness checks
    # ----------------------------
    def program_enrollment_exists(
        self,
        *,
        company_id: int,
        student_id: int,
        program_id: int,
        academic_year_id: int,
        exclude_id: Optional[int] = None,
    ) -> bool:
        cond = [
            ProgramEnrollment.company_id == company_id,
            ProgramEnrollment.student_id == int(student_id),
            ProgramEnrollment.program_id == int(program_id),
            ProgramEnrollment.academic_year_id == int(academic_year_id),
        ]
        if exclude_id:
            cond.append(ProgramEnrollment.id != int(exclude_id))
        stmt = select(exists().where(*cond))
        return bool(self.s.scalar(stmt))

    def course_enrollment_exists(
        self,
        *,
        company_id: int,
        branch_id: int,
        student_id: int,
        course_id: int,
        academic_year_id: int,
        academic_term_id: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> bool:
        cond = [
            CourseEnrollment.company_id == company_id,
            CourseEnrollment.branch_id == int(branch_id),
            CourseEnrollment.student_id == int(student_id),
            CourseEnrollment.course_id == int(course_id),
            CourseEnrollment.academic_year_id == int(academic_year_id),
        ]
        # term may be NULL; SQL unique constraint treats NULL specially, so we match explicitly:
        if academic_term_id is None:
            cond.append(CourseEnrollment.academic_term_id.is_(None))
        else:
            cond.append(CourseEnrollment.academic_term_id == int(academic_term_id))

        if exclude_id:
            cond.append(CourseEnrollment.id != int(exclude_id))

        stmt = select(exists().where(*cond))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Bulk course lookups (fast)
    # ----------------------------
    def get_courses_by_ids(
        self,
        *,
        company_id: int,
        course_ids: List[int],
        only_enabled: bool = True,
    ) -> List[Course]:
        if not course_ids:
            return []
        stmt = select(Course).where(Course.company_id == company_id, Course.id.in_(course_ids))
        if only_enabled:
            stmt = stmt.where(Course.is_enabled.is_(True))
        return list(self.s.scalars(stmt).all())

    # ----------------------------
    # Curriculum for program (ProgramCourse + Course)
    # ----------------------------
    def get_program_curriculum(
        self,
        *,
        company_id: int,
        program_id: int,
        curriculum_version: int = 1,
        on_date: Optional[date] = None,
    ) -> List[Tuple[ProgramCourse, Course]]:
        stmt = (
            select(ProgramCourse, Course)
            .join(Course, Course.id == ProgramCourse.course_id)
            .where(
                ProgramCourse.company_id == company_id,
                Course.company_id == company_id,
                ProgramCourse.program_id == int(program_id),
                ProgramCourse.curriculum_version == int(curriculum_version),
            )
        )

        if on_date:
            stmt = stmt.where(
                (ProgramCourse.effective_start.is_(None)) | (ProgramCourse.effective_start <= on_date),
                (ProgramCourse.effective_end.is_(None)) | (on_date <= ProgramCourse.effective_end),
            )

        # order by sequence_no NULL last, then course name
        stmt = stmt.order_by(
            ProgramCourse.sequence_no.is_(None),
            ProgramCourse.sequence_no.asc(),
            func.lower(Course.name).asc(),
        )

        return list(self.s.execute(stmt).all())

    # ----------------------------
    # Bulk delete helpers
    # ----------------------------
    def delete_program_enrollments_by_ids(self, *, company_id: int, ids: Iterable[int]) -> int:
        q = self.s.query(ProgramEnrollment).filter(
            ProgramEnrollment.company_id == company_id,
            ProgramEnrollment.id.in_(list(ids)),
        )
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)

    def delete_course_enrollments_by_ids(self, *, company_id: int, ids: Iterable[int]) -> int:
        q = self.s.query(CourseEnrollment).filter(
            CourseEnrollment.company_id == company_id,
            CourseEnrollment.id.in_(list(ids)),
        )
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)
