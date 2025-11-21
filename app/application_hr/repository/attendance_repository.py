# app/application_hr/repositories/attendance_repository.py
from __future__ import annotations

from typing import Optional, List
from datetime import date, datetime

from sqlalchemy import select, func

from config.database import db
from app.application_hr.models.hr import (
    Employee,
BiometricDevice,
    Attendance,
    EmployeeCheckin,
)

class AttendanceRepository:
    """
    Persistence helpers for Attendance + EmployeeCheckin + some Employee lookups.
    """

    def __init__(self, session=None):
        self.s = session or db.session

    # -----------------
    # Employee lookups
    # -----------------

    def get_employee_by_id(self, employee_id: int) -> Optional[Employee]:
        return self.s.query(Employee).filter(Employee.id == employee_id).first()

    def find_employee_by_code(self, *, company_id: int, code: str) -> Optional[Employee]:
        stmt = (
            select(Employee)
            .where(
                Employee.company_id == company_id,
                func.lower(Employee.code) == func.lower(code),
            )
        )
        return self.s.scalar(stmt)

    def find_employee_by_device_id(
        self,
        *,
        company_id: int,
        device_employee_id: str,
    ) -> Optional[Employee]:
        stmt = (
            select(Employee)
            .where(
                Employee.company_id == company_id,
                func.lower(Employee.attendance_device_id) == func.lower(device_employee_id),
            )
        )
        return self.s.scalar(stmt)

    def list_active_employees_for_company(self, company_id: int) -> List[Employee]:
        # you can later filter by StatusEnum.ACTIVE if you want
        stmt = (
            select(Employee)
            .where(Employee.company_id == company_id)
        )
        return list(self.s.scalars(stmt))

    # -----------------
    # Attendance
    # -----------------

    def get_attendance_for_emp_date(
        self,
        *,
        employee_id: int,
        company_id: int,
        attendance_date: date,
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

    # -----------------
    # Employee Checkin
    # -----------------

    def create_employee_checkin(self, ec: EmployeeCheckin) -> EmployeeCheckin:
        self.s.add(ec)
        self.s.flush([ec])
        return ec

    def get_employee_checkin_for_timestamp(
        self,
        *,
        employee_id: int,
        company_id: int,
        log_time_utc: datetime,
    ) -> Optional[EmployeeCheckin]:
        stmt = (
            select(EmployeeCheckin)
            .where(
                EmployeeCheckin.employee_id == employee_id,
                EmployeeCheckin.company_id == company_id,
                EmployeeCheckin.log_time == log_time_utc,
            )
        )
        return self.s.scalar(stmt)

    def get_checkins_for_emp_date(
        self,
        *,
        employee_id: int,
        company_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[EmployeeCheckin]:
        stmt = (
            select(EmployeeCheckin)
            .where(
                EmployeeCheckin.employee_id == employee_id,
                EmployeeCheckin.company_id == company_id,
                EmployeeCheckin.log_time >= start_utc,
                EmployeeCheckin.log_time < end_utc,
            )
            .order_by(EmployeeCheckin.log_time.asc())
        )
        return list(self.s.scalars(stmt))
    def get_active_biometric_devices(self, company_id: int | None = None) -> list[BiometricDevice]:
        q = self.s.query(BiometricDevice).filter(BiometricDevice.is_active.is_(True))
        if company_id is not None:
            q = q.filter(BiometricDevice.company_id == company_id)
        return q.order_by(BiometricDevice.company_id, BiometricDevice.code).all()