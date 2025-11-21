# app/hr/repo.py
from __future__ import annotations

from datetime import date
from typing import Optional, List
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.database import db
from app.application_hr.models.hr import (
    Employee,
    EmployeeAssignment,
    EmployeeEmergencyContact,
    HolidayList,
    Holiday,
    ShiftType,
    ShiftAssignment,
    Attendance,
    EmployeeCheckin,
)
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
        # ---- Fetch employee ----

    def get_employee_by_id(self, employee_id: int) -> Optional[Employee]:
        """ Fetches an Employee by its primary key ID. """
        return self.s.query(Employee).filter(Employee.id == employee_id).first()

        # ---- Update Employee ----

    def update_employee(self, emp: Employee, update_data: dict) -> None:
        """ Update employee fields based on the provided data """
        for field, value in update_data.items():
            if hasattr(emp, field):
                setattr(emp, field, value)
        self.s.flush([emp])

        # ---- Update assignments ----

    def update_assignments(self, employee_id: int, rows: List[dict]) -> None:
        # Update only the provided assignments
        pass  # You can follow a similar pattern as creating assignments but with `UPDATE` operations.

        # ---- Update emergency contacts ----

    def update_emergency_contacts(self, employee_id: int, rows: List[dict]) -> None:
        # Update only the provided emergency contacts
        pass  # Follow a similar pattern for updating the emergency contacts.

    # ------------------------------------------------------------------
    # Holiday List + Holidays
    # ------------------------------------------------------------------

    def get_holiday_list_by_id(self, holiday_list_id: int) -> Optional[HolidayList]:
        return self.s.get(HolidayList, holiday_list_id)

    def create_holiday_list(self, hl: HolidayList, holidays: list[dict]) -> HolidayList:
        self.s.add(hl)
        self.s.flush([hl])
        if holidays:
            objs = []
            for h in holidays:
                objs.append(
                    Holiday(
                        holiday_list_id=hl.id,
                        holiday_date=h["holiday_date"],
                        description=h.get("description"),
                        is_full_day=h.get("is_full_day", True),
                        is_weekly_off=h.get("is_weekly_off", False),
                    )
                )
            self.s.add_all(objs)
            self.s.flush(objs)
        return hl

    def replace_holiday_list_rows(self, hl: HolidayList, holidays: list[dict]) -> None:
        # delete existing
        self.s.query(Holiday).filter(Holiday.holiday_list_id == hl.id).delete()
        self.s.flush()
        if holidays:
            objs = []
            for h in holidays:
                objs.append(
                    Holiday(
                        holiday_list_id=hl.id,
                        holiday_date=h["holiday_date"],
                        description=h.get("description"),
                        is_full_day=h.get("is_full_day", True),
                        is_weekly_off=h.get("is_weekly_off", False),
                    )
                )
            self.s.add_all(objs)
            self.s.flush(objs)

    # ------------------------------------------------------------------
    # Shift Type + Assignment
    # ------------------------------------------------------------------

    def get_shift_type_by_id(self, shift_type_id: int) -> Optional[ShiftType]:
        return self.s.get(ShiftType, shift_type_id)

    def create_shift_type(self, st: ShiftType) -> ShiftType:
        self.s.add(st)
        self.s.flush([st])
        return st

    def update_shift_type_fields(self, st: ShiftType, data: dict) -> None:
        for field, value in data.items():
            if hasattr(st, field) and value is not None:
                setattr(st, field, value)
        self.s.flush([st])

    def get_shift_assignment_by_id(self, sa_id: int) -> Optional[ShiftAssignment]:
        return self.s.get(ShiftAssignment, sa_id)

    def create_shift_assignment(self, sa: ShiftAssignment) -> ShiftAssignment:
        self.s.add(sa)
        self.s.flush([sa])
        return sa

    def update_shift_assignment_fields(self, sa: ShiftAssignment, data: dict) -> None:
        for field, value in data.items():
            if hasattr(sa, field) and value is not None:
                setattr(sa, field, value)
        self.s.flush([sa])

    # ------------------------------------------------------------------
    # Attendance
    # ------------------------------------------------------------------

    def get_attendance_for_emp_date(
        self, *, employee_id: int, company_id: int, attendance_date: date
    ) -> Optional[Attendance]:
        stmt = (
            select(Attendance)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.company_id == company_id,
                Attendance.attendance_date == attendance_date,
            )
        )
        return self.s.scalar(stmt)

    def create_attendance(self, att: Attendance) -> Attendance:
        self.s.add(att)
        self.s.flush([att])
        return att

    # ------------------------------------------------------------------
    # Employee Checkin
    # ------------------------------------------------------------------

    def create_employee_checkin(self, ec: EmployeeCheckin) -> EmployeeCheckin:
        self.s.add(ec)
        self.s.flush([ec])
        return ec

    def find_employee_by_code(
        self, *, company_id: int, code: str
    ) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.company_id == company_id,
            func.lower(Employee.code) == func.lower(code),
        )
        return self.s.scalar(stmt)