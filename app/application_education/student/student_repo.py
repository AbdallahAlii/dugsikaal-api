from __future__ import annotations

from typing import Optional, Iterable, List, Set

from sqlalchemy import select, func, exists, update
from sqlalchemy.orm import Session

from app.common.cache.session_manager import set_cached_user_status, remove_session
from config.database import db
from app.application_education.core.base_repo import BaseEducationRepo

from app.application_education.student.models import Student, Guardian, StudentGuardian
from app.application_org.models.company import Branch

from app.auth.models.users import UserType, User, UserAffiliation
from app.common.models.base import StatusEnum


class StudentRepo:
    """
    Domain repo composed of smaller BaseEducationRepo for each model,
    plus special queries for uniqueness, counts, links.
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.students = BaseEducationRepo(Student, self.s)
        self.guardians = BaseEducationRepo(Guardian, self.s)
        self.links = BaseEducationRepo(StudentGuardian, self.s)

    # ----------------------------
    # Branch helpers
    # ----------------------------
    def get_branch_by_id(self, branch_id: int) -> Optional[Branch]:
        return self.s.query(Branch).filter(Branch.id == branch_id).first()

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        return self.s.scalar(select(Branch.company_id).where(Branch.id == branch_id))


    # ----------------------------
    # Student existence checks
    # ----------------------------
    def student_name_exists(self, *, company_id: int, branch_id: int, full_name: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Student.company_id == company_id,
            Student.branch_id == branch_id,
            func.lower(Student.full_name) == func.lower(full_name.strip()),
            *( [Student.id != exclude_id] if exclude_id else [] )
        ))
        return bool(self.s.scalar(stmt))

    def student_email_exists(self, *, company_id: int, branch_id: int, email: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Student.company_id == company_id,
            Student.branch_id == branch_id,
            func.lower(Student.student_email) == func.lower(email.strip()),
            *( [Student.id != exclude_id] if exclude_id else [] )
        ))
        return bool(self.s.scalar(stmt))

    def student_code_exists(self, *, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Student.company_id == company_id,
            Student.branch_id == branch_id,
            func.lower(Student.student_code) == func.lower(code.strip()),
            *( [Student.id != exclude_id] if exclude_id else [] )
        ))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Guardian existence checks
    # ----------------------------
    def guardian_name_exists(self, *, company_id: int, branch_id: int, name: str,
                             exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Guardian.company_id == company_id,
            Guardian.branch_id == branch_id,
            func.lower(Guardian.guardian_name) == func.lower(name.strip()),
            *([Guardian.id != exclude_id] if exclude_id else [])
        ))
        return bool(self.s.scalar(stmt))

    def guardian_email_exists(self, *, company_id: int, branch_id: int, email: str,
                              exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Guardian.company_id == company_id,
            Guardian.branch_id == branch_id,
            func.lower(Guardian.email_address) == func.lower(email.strip()),
            *([Guardian.id != exclude_id] if exclude_id else [])
        ))
        return bool(self.s.scalar(stmt))

    def guardian_mobile_exists(self, *, company_id: int, branch_id: int, mobile: str,
                               exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Guardian.company_id == company_id,
            Guardian.branch_id == branch_id,
            func.lower(Guardian.mobile_number) == func.lower(mobile.strip()),
            *([Guardian.id != exclude_id] if exclude_id else [])
        ))
        return bool(self.s.scalar(stmt))

    def delete_student_guardian_links(self, *, student_id: int) -> int:
        q = self.s.query(StudentGuardian).filter(StudentGuardian.student_id == int(student_id))
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)

    def guardian_code_exists(self, *, company_id: int, branch_id: int, code: str,
                             exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Guardian.company_id == company_id,
            Guardian.branch_id == branch_id,
            func.lower(Guardian.guardian_code) == func.lower(code.strip()),
            *([Guardian.id != exclude_id] if exclude_id else [])
        ))
        return bool(self.s.scalar(stmt))

    def student_has_sales_invoices(self, *, student_id: int) -> bool:
        from app.application_selling.models import SalesInvoice
        stmt = select(exists().where(SalesInvoice.student_id == int(student_id)))
        return bool(self.s.scalar(stmt))

    def student_has_sales_quotations(self, *, student_id: int) -> bool:
        from app.application_selling.models import SalesQuotation
        stmt = select(exists().where(SalesQuotation.student_id == int(student_id)))
        return bool(self.s.scalar(stmt))

    # ----------------------------
    # Link helpers
    # ----------------------------
    def guardian_link_exists(self, *, student_id: int, guardian_id: int, branch_id: int) -> bool:
        stmt = select(exists().where(
            StudentGuardian.student_id == student_id,
            StudentGuardian.guardian_id == guardian_id,
            StudentGuardian.branch_id == branch_id,
        ))
        return bool(self.s.scalar(stmt))

    def student_has_primary_guardian(self, *, student_id: int) -> bool:
        stmt = select(exists().where(
            StudentGuardian.student_id == student_id,
            StudentGuardian.is_primary.is_(True),
        ))
        return bool(self.s.scalar(stmt))

    def count_student_guardian_links(self, student_id: int) -> int:
        stmt = select(func.count()).select_from(StudentGuardian).where(StudentGuardian.student_id == student_id)
        return int(self.s.scalar(stmt) or 0)

    def count_guardian_links(self, guardian_id: int) -> int:
        stmt = select(func.count()).select_from(StudentGuardian).where(StudentGuardian.guardian_id == guardian_id)
        return int(self.s.scalar(stmt) or 0)

    def count_student_enrollments(self, student_id: int) -> int:
        # ✅ correct import path (your project)
        from app.application_education.enrollments.enrollment_model import ProgramEnrollment, CourseEnrollment

        pe = int(self.s.scalar(
            select(func.count()).select_from(ProgramEnrollment).where(ProgramEnrollment.student_id == student_id)
        ) or 0)

        ce = int(self.s.scalar(
            select(func.count()).select_from(CourseEnrollment).where(CourseEnrollment.student_id == student_id)
        ) or 0)

        return pe + ce

    # ----------------------------
    # Bulk hard delete
    # ----------------------------
    def delete_students_by_ids(self, ids: Iterable[int]) -> int:
        q = self.s.query(Student).filter(Student.id.in_(list(ids)))
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)

    def delete_guardians_by_ids(self, ids: Iterable[int]) -> int:
        q = self.s.query(Guardian).filter(Guardian.id.in_(list(ids)))
        n = q.delete(synchronize_session=False)
        self.s.flush()
        return int(n or 0)
    # ----------------------------
    # Bulk "in use" checks (avoid 2N queries)
    # ----------------------------
    def students_with_guardian_links(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        stmt = select(StudentGuardian.student_id).where(StudentGuardian.student_id.in_(ids)).distinct()
        return set(self.s.scalars(stmt).all())

    def guardians_with_student_links(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        stmt = select(StudentGuardian.guardian_id).where(StudentGuardian.guardian_id.in_(ids)).distinct()
        return set(self.s.scalars(stmt).all())

    def students_with_any_enrollments(self, ids: List[int]) -> Set[int]:
        if not ids:
            return set()
        from app.application_education.enrollments.enrollment_model import ProgramEnrollment, CourseEnrollment

        stmt1 = select(ProgramEnrollment.student_id).where(ProgramEnrollment.student_id.in_(ids)).distinct()
        stmt2 = select(CourseEnrollment.student_id).where(CourseEnrollment.student_id.in_(ids)).distinct()

        pe = set(self.s.scalars(stmt1).all())
        ce = set(self.s.scalars(stmt2).all())
        return pe | ce

    # ----------------------------
    # User helpers (same idea as HR)
    # ----------------------------
    def disable_users_and_affiliations_bulk(self, user_ids: Iterable[int]) -> int:
        """
        Fast bulk disable:
          - users.status => INACTIVE
          - user_affiliations.is_primary => False
          - kick active sessions (Redis + cached status)
        """
        ids: Set[int] = {int(x) for x in user_ids if x}
        if not ids:
            return 0

        # 1) Disable users (DB)
        self.s.execute(
            update(User)
            .where(User.id.in_(ids))
            .values(status=StatusEnum.INACTIVE)
        )

        # 2) "Disable" affiliations best-effort without changing model
        self.s.execute(
            update(UserAffiliation)
            .where(UserAffiliation.user_id.in_(ids))
            .values(is_primary=False)
        )

        self.s.flush()

        # 3) Kick sessions + mark cached status (best-effort, do NOT break DB transaction)
        for uid in ids:
            try:
                set_cached_user_status(uid, StatusEnum.INACTIVE.value)
            except Exception:
                pass
            try:
                remove_session(uid)
            except Exception:
                pass

        return len(ids)
    def get_user_type_by_name(self, name: str) -> Optional[UserType]:
        return self.s.scalar(select(UserType).where(func.lower(UserType.name) == func.lower(name.strip())))

    def create_user_and_affiliation(
            self,
            *,
            username: str,
            password_hash: str,
            company_id: int,
            branch_id: Optional[int],
            user_type: UserType,
            linked_entity_id: Optional[int],
            make_primary: bool = True,
    ) -> User:
        u = User(username=username, password_hash=password_hash, status=StatusEnum.ACTIVE)
        self.s.add(u)
        self.s.flush([u])

        aff = UserAffiliation(
            user_id=u.id,
            company_id=company_id,
            branch_id=branch_id,
            user_type_id=user_type.id,
            linked_entity_id=linked_entity_id,
            is_primary=make_primary,
        )
        self.s.add(aff)
        self.s.flush([aff])
        return u
