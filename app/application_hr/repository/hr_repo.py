# app/hr/repo.py
from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.database import db
from app.application_hr.models.hr import Employee, EmployeeAssignment, EmployeeEmergencyContact
from app.application_org.models.company import Branch
from app.auth.models.users import UserType, User, UserAffiliation
from app.common.models.base import StatusEnum, GenderEnum, PersonRelationshipEnum


class HrRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---- lookups used only for admin / global "*:*" callers ----
    def branch_in_company(self, branch_id: int, company_id: int) -> bool:
        return bool(self.s.scalar(select(Branch.id).where(
            Branch.id == branch_id, Branch.company_id == company_id
        )))

    def get_branch_by_id(self, branch_id: int) -> Optional[Branch]:
        """ Fetches a Branch by its primary key ID. """
        return self.s.query(Branch).filter(Branch.id == branch_id).first()
    def employee_code_exists(self, company_id: int, code: str) -> bool:
        return bool(self.s.scalar(select(Employee.id).where(
            Employee.company_id == company_id,
            func.lower(Employee.code) == func.lower(code),
        )))

    def get_user_type_by_name(self, name: str) -> Optional[UserType]:
        return self.s.scalar(select(UserType).where(func.lower(UserType.name) == func.lower(name)))

    # ---- create operations ----
    def create_employee(self, e: Employee) -> Employee:
        self.s.add(e)
        self.s.flush()  # get e.id
        return e

    def update_employee_img_key(self, emp: Employee, img_key: str) -> None:
        emp.img_key = img_key
        self.s.flush([emp])

    def create_assignments(self, employee_id: int, company_id: int, rows: List[dict]) -> None:
        objs = []
        primary_seen = False
        for r in rows:
            is_primary = bool(r.get("is_primary", False))
            if is_primary:
                if primary_seen:
                    is_primary = False  # keep it sane; DB constraint also protects
                primary_seen = True
            objs.append(EmployeeAssignment(
                employee_id=employee_id,
                company_id=company_id,
                branch_id=r["branch_id"],
                department_id=r.get("department_id"),
                job_title=r.get("job_title"),
                from_date=r["from_date"],
                to_date=r.get("to_date"),
                is_primary=is_primary,
                status=StatusEnum.ACTIVE,
                extra=r.get("extra") or {},
            ))
        self.s.add_all(objs)
        self.s.flush(objs)

    def create_emergency_contacts(self, employee_id: int, rows: List[dict]) -> None:
        if not rows:
            return
        objs = []
        for r in rows:
            objs.append(EmployeeEmergencyContact(
                employee_id=employee_id,
                full_name=r["full_name"],
                relationship_type=PersonRelationshipEnum[r["relationship_type"].upper()]
                    if isinstance(r["relationship_type"], str) else r["relationship_type"],
                phone_number=r["phone_number"],
            ))
        self.s.add_all(objs)
        self.s.flush(objs)

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
