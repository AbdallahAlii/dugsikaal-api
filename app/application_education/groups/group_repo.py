# app/application_education/groups/group_repo.py
from __future__ import annotations

from typing import List, Optional, Set, Dict, Any

from sqlalchemy import select, func, exists, update
from sqlalchemy.orm import Session

from config.database import db
from app.application_education.core.base_repo import BaseEducationRepo

from app.application_education.groups.student_group_model import Batch, StudentCategory, StudentGroup, StudentGroupMembership
from app.application_education.enrollments.enrollment_model import ProgramEnrollment
from app.application_education.student.models import Student


class GroupRepo:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.batches = BaseEducationRepo(Batch, self.s)
        self.categories = BaseEducationRepo(StudentCategory, self.s)
        self.groups = BaseEducationRepo(StudentGroup, self.s)
        self.memberships = BaseEducationRepo(StudentGroupMembership, self.s)

    # ----------------------------
    # Batch duplicates
    # ----------------------------
    def batch_name_exists(self, *, company_id: int, branch_id: Optional[int], batch_name: str, exclude_id: Optional[int] = None) -> bool:
        conds = [
            Batch.company_id == company_id,
            func.lower(Batch.batch_name) == func.lower(batch_name.strip()),
        ]
        if branch_id is None:
            conds.append(Batch.branch_id.is_(None))
        else:
            conds.append(Batch.branch_id == int(branch_id))
        if exclude_id:
            conds.append(Batch.id != int(exclude_id))

        stmt = select(exists().where(*conds))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Category duplicates
    # ----------------------------
    def category_name_exists(self, *, company_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        conds = [
            StudentCategory.company_id == company_id,
            func.lower(StudentCategory.name) == func.lower(name.strip()),
        ]
        if exclude_id:
            conds.append(StudentCategory.id != int(exclude_id))
        stmt = select(exists().where(*conds))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Group duplicates (same as constraints)
    # ----------------------------
    def group_name_exists(self, *, company_id: int, program_id: int, academic_year_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        conds = [
            StudentGroup.company_id == company_id,
            StudentGroup.program_id == int(program_id),
            StudentGroup.academic_year_id == int(academic_year_id),
            func.lower(StudentGroup.name) == func.lower(name.strip()),
        ]
        if exclude_id:
            conds.append(StudentGroup.id != int(exclude_id))
        stmt = select(exists().where(*conds))
        return bool(self.s.scalar(stmt))

    def group_setup_exists(self, *, company_id: int, program_id: int, academic_year_id: int, section_id: Optional[int], exclude_id: Optional[int] = None) -> bool:
        # matches uq_group_program_year_section
        conds = [
            StudentGroup.company_id == company_id,
            StudentGroup.program_id == int(program_id),
            StudentGroup.academic_year_id == int(academic_year_id),
        ]
        if section_id is None:
            conds.append(StudentGroup.section_id.is_(None))
        else:
            conds.append(StudentGroup.section_id == int(section_id))

        if exclude_id:
            conds.append(StudentGroup.id != int(exclude_id))

        stmt = select(exists().where(*conds))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Membership counts + active roster
    # ----------------------------
    def count_membership_history(self, *, group_id: int) -> int:
        stmt = select(func.count()).select_from(StudentGroupMembership).where(StudentGroupMembership.group_id == int(group_id))
        return int(self.s.scalar(stmt) or 0)

    def get_active_member_ids(self, *, group_id: int) -> Set[int]:
        stmt = select(StudentGroupMembership.student_id).where(
            StudentGroupMembership.group_id == int(group_id),
            StudentGroupMembership.left_on.is_(None),
        )
        return set(self.s.scalars(stmt).all())

    def set_left_on_bulk(self, *, company_id: int, group_id: int, student_ids: List[int], left_on) -> int:
        if not student_ids:
            return 0
        res = self.s.execute(
            update(StudentGroupMembership)
            .where(
                StudentGroupMembership.company_id == int(company_id),
                StudentGroupMembership.group_id == int(group_id),
                StudentGroupMembership.student_id.in_([int(x) for x in student_ids]),
                StudentGroupMembership.left_on.is_(None),
            )
            .values(left_on=left_on)
        )
        self.s.flush()
        return int(res.rowcount or 0)

    # ----------------------------
    # ERPNext-like Get Students (from Program Enrollment)
    # ----------------------------
    def get_students_from_enrollments(
        self,
        *,
        company_id: int,
        branch_id: Optional[int],
        academic_year_id: int,
        academic_term_id: Optional[int],
        program_id: Optional[int],
        batch_id: Optional[int],
        student_category_id: Optional[int],  # optional: if you later store on enrollment/student
    ) -> List[Dict[str, Any]]:
        """
        ERPNext uses Program Enrollment (+ join Program Enrollment Course if course filter).
        Your model doesn't have docstatus, so we treat "active/submitted" as:
          enrollment_status != 'Cancelled'
        (you can tighten to only ENROLLED/SUSPENDED if you want.)
        """

        stmt = (
            select(
                ProgramEnrollment.student_id,
                Student.full_name,
                Student.is_enabled,
            )
            .select_from(ProgramEnrollment)
            .join(Student, Student.id == ProgramEnrollment.student_id)
            .where(
                ProgramEnrollment.company_id == int(company_id),
                ProgramEnrollment.academic_year_id == int(academic_year_id),
                ProgramEnrollment.enrollment_status != "Cancelled",
            )
        )

        if branch_id is not None:
            stmt = stmt.where(ProgramEnrollment.branch_id == int(branch_id))
        if academic_term_id is not None:
            stmt = stmt.where(ProgramEnrollment.academic_term_id == int(academic_term_id))
        if program_id is not None:
            stmt = stmt.where(ProgramEnrollment.program_id == int(program_id))
        if batch_id is not None:
            stmt = stmt.where(ProgramEnrollment.batch_id == int(batch_id))

        rows = self.s.execute(stmt).all()
        out: List[Dict[str, Any]] = []
        for sid, name, enabled in rows:
            out.append({
                "student_id": int(sid),
                "student_name": name,
                "active": bool(enabled),
            })
        return out