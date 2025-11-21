# app/application_hr/services/attendance_service.py
from __future__ import annotations

import logging
from typing import Tuple, Optional
from datetime import datetime, date, time as dtime

from app.application_hr.repository.attendance_repository import AttendanceRepository
from app.security.rbac_guards import ensure_scope_by_ids
from config.database import db
from app.application_hr.models.hr import (
    Employee,
BiometricDevice,
    Attendance,
    EmployeeCheckin, AttendanceStatusEnum,
)
from app.business_validation.hr_validation import (
    validate_attendance_basic,
    validate_checkin_basic,
    ERR_ATTENDANCE_DUPLICATE,
    ERR_CHECKIN_EMP_NOT_FOUND,
    ERR_CHECKIN_DUPLICATE,
)
from app.business_validation.item_validation import BizValidationError
from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc
from app.security.rbac_effective import AffiliationContext


class AttendanceService:
    """
    Handles Attendance + EmployeeCheckin + Auto Attendance.
    """

    def __init__(self, session=None):
        self.s = session or db.session
        self.repo = AttendanceRepository(self.s)
    def list_biometric_devices_for_agent(
        self,
        company_id: int | None = None,
    ) -> list[BiometricDevice]:
        return self.repo.get_active_biometric_devices(company_id=company_id)
    # ------------------------------------------------------------------
    # Attendance (manual)
    # ------------------------------------------------------------------
    def create_manual_attendance(
        self,
        *,
        payload,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Attendance]]:
        """
        Used when company enters attendance manually (no device),
        or to override auto attendance.
        """
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Attendance.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=payload.branch_id,
            )

            validate_attendance_basic(
                attendance_date=payload.attendance_date,
                status=payload.status.value if payload.status else None,
            )

            existing = self.repo.get_attendance_for_emp_date(
                employee_id=payload.employee_id,
                company_id=company_id,
                attendance_date=payload.attendance_date,
            )
            if existing:
                raise BizValidationError(ERR_ATTENDANCE_DUPLICATE)

            att = Attendance(
                employee_id=payload.employee_id,
                company_id=company_id,
                branch_id=payload.branch_id,
                attendance_date=payload.attendance_date,
                status=payload.status,
                shift_type_id=payload.shift_type_id,
                in_time=payload.in_time,
                out_time=payload.out_time,
                working_hours=0,
                late_entry=False,
                early_exit=False,
                source="MANUAL",
                remarks=payload.remarks,
            )

            self.repo.create_attendance(att)
            self.s.commit()
            return True, "Attendance recorded", att

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            self.s.rollback()
            logging.exception("create_manual_attendance failed: %s", e)
            return False, "Unexpected error while creating Attendance.", None

    # ------------------------------------------------------------------
    # Employee Checkin (device / mobile / manual)
    # ------------------------------------------------------------------
    def create_employee_checkin(
        self,
        *,
        payload,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional["EmployeeCheckin"]]:
        """
        Generic entry-point for logs from device / mobile / manual.

        Resolves employee by:
          - employee_id
          - employee_code
          - device_employee_id (attendance_device_id on Employee)
        """
        from app.application_hr.models.hr import EmployeeCheckin  # avoid circular import at top

        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Employee Checkin.", None

            validate_checkin_basic(
                log_time=payload.log_time,
                log_type=payload.log_type.value if payload.log_type else None,
                source=payload.source.value if payload.source else None,
            )

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None,
            )

            # ---- Resolve employee ----
            employee: Optional[Employee] = None

            if payload.employee_id:
                employee = self.repo.get_employee_by_id(payload.employee_id)
                if not employee or employee.company_id != company_id:
                    employee = None

            if not employee and getattr(payload, "employee_code", None):
                employee = self.repo.find_employee_by_code(
                    company_id=company_id,
                    code=payload.employee_code,
                )

            if not employee and getattr(payload, "device_employee_id", None):
                employee = self.repo.find_employee_by_device_id(
                    company_id=company_id,
                    device_employee_id=payload.device_employee_id,
                )

            if not employee:
                raise BizValidationError(ERR_CHECKIN_EMP_NOT_FOUND)

            # ---- Timezone normalization ----
            tz = get_company_timezone(self.s, company_id)
            aware_local = ensure_aware(payload.log_time, tz)
            log_time_utc = to_utc(aware_local)

            # ---- Duplicate check ----
            existing = self.repo.get_employee_checkin_for_timestamp(
                employee_id=employee.id,
                company_id=company_id,
                log_time_utc=log_time_utc,
            )
            if existing:
                raise BizValidationError(ERR_CHECKIN_DUPLICATE)

            ec = EmployeeCheckin(
                employee_id=employee.id,
                company_id=company_id,
                log_time=log_time_utc,
                log_type=payload.log_type,
                source=payload.source,
                device_id=payload.device_id,
                skip_auto_attendance=False,
                raw_payload=payload.raw_payload or {},
            )

            self.repo.create_employee_checkin(ec)
            self.s.commit()
            return True, "Employee Checkin created", ec

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            self.s.rollback()
            logging.exception("create_employee_checkin failed: %s", e)
            return False, "Unexpected server error while creating Employee Checkin.", None

    # ------------------------------------------------------------------
    # Auto Attendance: first scan = IN, last scan = OUT
    # ------------------------------------------------------------------
    def run_auto_attendance_for_date(
        self,
        *,
        company_id: int,
        target_date: date,
    ) -> Tuple[bool, str]:
        """
        Process EmployeeCheckin → Attendance for one company & one date.

        Rule:
          - If employee has ≥ 1 checkin on that day:
              in_time  = first checkin
              out_time = last checkin
              status   = Present
          - Additional scans in the middle are ignored for in/out.
          - If no checkin, we do nothing here (you can later create Absent rows if needed).
        """
        try:
            tz = get_company_timezone(self.s, company_id)

            start_local = datetime.combine(target_date, dtime.min)
            end_local = datetime.combine(target_date, dtime.max)

            start_utc = to_utc(ensure_aware(start_local, tz))
            end_utc = to_utc(ensure_aware(end_local, tz))

            employees = self.repo.list_active_employees_for_company(company_id)
            processed = 0

            for emp in employees:
                checkins = self.repo.get_checkins_for_emp_date(
                    employee_id=emp.id,
                    company_id=company_id,
                    start_utc=start_utc,
                    end_utc=end_utc,
                )
                if not checkins:
                    continue

                in_time_utc = checkins[0].log_time
                out_time_utc = checkins[-1].log_time

                in_time = in_time_utc
                out_time = out_time_utc

                if in_time and out_time and out_time > in_time:
                    working_hours = (out_time - in_time).total_seconds() / 3600.0
                else:
                    working_hours = 0.0

                status = AttendanceStatusEnum.PRESENT
                branch_id = emp.primary_branch_id
                shift_type_id = emp.default_shift_type_id

                existing = self.repo.get_attendance_for_emp_date(
                    employee_id=emp.id,
                    company_id=company_id,
                    attendance_date=target_date,
                )

                if existing:
                    if existing.source == "AUTO":
                        existing.in_time = in_time
                        existing.out_time = out_time
                        existing.working_hours = working_hours
                        existing.status = status
                        existing.shift_type_id = shift_type_id
                        existing.branch_id = branch_id or existing.branch_id
                else:
                    att = Attendance(
                        employee_id=emp.id,
                        company_id=company_id,
                        branch_id=branch_id,
                        attendance_date=target_date,
                        status=status,
                        shift_type_id=shift_type_id,
                        in_time=in_time,
                        out_time=out_time,
                        working_hours=working_hours,
                        late_entry=False,
                        early_exit=False,
                        source="AUTO",
                        remarks=None,
                    )
                    self.repo.create_attendance(att)

                processed += 1

            self.s.commit()
            return True, f"Auto attendance completed for {processed} employees on {target_date}"

        except Exception as e:
            self.s.rollback()
            logging.exception("run_auto_attendance_for_date failed: %s", e)
            return False, "Unexpected error while running auto attendance."
