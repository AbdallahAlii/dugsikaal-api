from __future__ import annotations

from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.database import db
from app.application_hr.models.hr import Employee
from app.application_hr.models.biometric_dp4500 import EmployeeFingerprintTemplate, FingerIndexEnum


class BiometricDP4500Repository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # -------------------------
    # Employee resolution
    # -------------------------
    def get_employee_by_id(self, employee_id: int) -> Optional[Employee]:
        return self.s.get(Employee, employee_id)

    def find_employee_by_device_id(self, *, company_id: int, device_employee_id: str) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.company_id == company_id,
            func.lower(Employee.attendance_device_id) == func.lower(device_employee_id),
        )
        return self.s.scalar(stmt)

    # -------------------------
    # Templates
    # -------------------------
    def get_template(
        self,
        *,
        company_id: int,
        employee_id: int,
        finger_index: FingerIndexEnum,
    ) -> Optional[EmployeeFingerprintTemplate]:
        stmt = select(EmployeeFingerprintTemplate).where(
            EmployeeFingerprintTemplate.company_id == company_id,
            EmployeeFingerprintTemplate.employee_id == employee_id,
            EmployeeFingerprintTemplate.finger_index == finger_index,
        )
        return self.s.scalar(stmt)

    def list_templates_for_employee(
        self,
        *,
        company_id: int,
        employee_id: int,
    ) -> List[EmployeeFingerprintTemplate]:
        stmt = (
            select(EmployeeFingerprintTemplate)
            .where(
                EmployeeFingerprintTemplate.company_id == company_id,
                EmployeeFingerprintTemplate.employee_id == employee_id,
            )
            .order_by(EmployeeFingerprintTemplate.created_at.desc())
        )
        return list(self.s.scalars(stmt))

    def upsert_template(self, obj: EmployeeFingerprintTemplate) -> EmployeeFingerprintTemplate:
        self.s.add(obj)
        self.s.flush([obj])
        return obj
