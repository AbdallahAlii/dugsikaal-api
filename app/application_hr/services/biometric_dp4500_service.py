from __future__ import annotations

import logging
from typing import Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from config.database import db
from app.application_hr.models.biometric_dp4500 import EmployeeFingerprintTemplate, FingerIndexEnum
from app.application_hr.repository.biometric_dp4500_repo import BiometricDP4500Repository
from app.application_hr.device.dp4500_reader import DP4500Reader, DP4500Error
from app.business_validation.item_validation import BizValidationError
from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


class BiometricDP4500Service:
    """
    - Enroll: captures template and stores it
    - Verify: captures template and compares using SDK (placeholder = exact match)
    - Optional: creates EmployeeCheckin on success (uses your AttendanceService if you want)
    """

    def __init__(self, session: Optional[Session] = None, reader: Optional[DP4500Reader] = None):
        self.s: Session = session or db.session
        self.repo = BiometricDP4500Repository(self.s)
        self.reader = reader  # injected from endpoint factory

    def enroll(
        self,
        *,
        company_id: int,
        employee_id: Optional[int],
        device_employee_id: Optional[str],
        finger_index: FingerIndexEnum,
        context: Optional[AffiliationContext] = None,
    ) -> Tuple[bool, str, Optional[EmployeeFingerprintTemplate]]:
        try:
            # resolve employee
            emp = None
            if employee_id:
                emp = self.repo.get_employee_by_id(employee_id)
                if emp and emp.company_id != company_id:
                    emp = None
            if not emp and device_employee_id:
                emp = self.repo.find_employee_by_device_id(company_id=company_id, device_employee_id=device_employee_id)

            if not emp:
                raise BizValidationError("Employee not found for enrollment.")

            if not self.reader:
                raise BizValidationError("DP4500 reader is not configured.")

            log.info("DP4500 enroll start company=%s emp=%s finger=%s", company_id, emp.id, finger_index.value)

            cap = self.reader.capture()

            existing = self.repo.get_template(
                company_id=company_id,
                employee_id=emp.id,
                finger_index=finger_index,
            )

            if existing:
                existing.template = cap.template_bytes
                existing.device_name = cap.device_name
                existing.device_serial = cap.device_serial
                existing.extra = cap.raw or {}
                obj = existing
            else:
                obj = EmployeeFingerprintTemplate(
                    company_id=company_id,
                    employee_id=emp.id,
                    finger_index=finger_index,
                    template=cap.template_bytes,
                    template_format="DP4500_TEMPLATE",
                    device_name=cap.device_name,
                    device_serial=cap.device_serial,
                    extra=cap.raw or {},
                )

            self.repo.upsert_template(obj)
            self.s.commit()

            log.info("DP4500 enroll success company=%s emp=%s finger=%s tpl_id=%s", company_id, emp.id, finger_index.value, obj.id)
            return True, "Fingerprint enrolled", obj

        except DP4500Error as e:
            self.s.rollback()
            log.warning("DP4500 enroll device error: %s", e)
            return False, str(e), None
        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            self.s.rollback()
            log.exception("DP4500 enroll failed: %s", e)
            return False, "Unexpected error during enrollment.", None

    def verify_1to1(
        self,
        *,
        company_id: int,
        employee_id: Optional[int],
        device_employee_id: Optional[str],
        finger_index: FingerIndexEnum,
    ) -> Tuple[bool, str, bool]:
        """
        Placeholder compare (exact bytes). Real match must be done by HID SDK/engine.
        Still useful for plumbing & end-to-end testing.
        """
        try:
            emp = None
            if employee_id:
                emp = self.repo.get_employee_by_id(employee_id)
                if emp and emp.company_id != company_id:
                    emp = None
            if not emp and device_employee_id:
                emp = self.repo.find_employee_by_device_id(company_id=company_id, device_employee_id=device_employee_id)

            if not emp:
                raise BizValidationError("Employee not found for verify.")

            tpl = self.repo.get_template(
                company_id=company_id,
                employee_id=emp.id,
                finger_index=finger_index,
            )
            if not tpl:
                return False, "No enrolled fingerprint template for this employee/finger.", False

            if not self.reader:
                raise BizValidationError("DP4500 reader is not configured.")

            log.info("DP4500 verify start company=%s emp=%s finger=%s", company_id, emp.id, finger_index.value)

            cap = self.reader.capture()

            # --- PLACEHOLDER ---
            match = (cap.template_bytes == tpl.template)

            log.info("DP4500 verify done company=%s emp=%s finger=%s match=%s", company_id, emp.id, finger_index.value, match)
            return True, "Verified" if match else "Not matched", match

        except DP4500Error as e:
            log.warning("DP4500 verify device error: %s", e)
            return False, str(e), False
        except BizValidationError as e:
            return False, str(e), False
        except Exception as e:
            log.exception("DP4500 verify failed: %s", e)
            return False, "Unexpected error during verify.", False

    def create_checkin_on_match(
        self,
        *,
        company_id: int,
        employee_id: int,
        log_type,  # CheckinLogTypeEnum
        source,    # CheckinSourceEnum
        device_id: str,
        raw_payload: dict,
        log_time_local: Optional[datetime] = None,
    ):
        """
        If you want: call your existing AttendanceService.create_employee_checkin()
        Here is a helper to normalize time and return a dict you can feed to your service.
        """
        tz = get_company_timezone(self.s, company_id)
        log_time_local = log_time_local or datetime.now()
        aware_local = ensure_aware(log_time_local, tz)
        log_time_utc = to_utc(aware_local)

        return {
            "company_id": company_id,
            "employee_id": employee_id,
            "log_time": log_time_utc,
            "log_type": log_type,
            "source": source,
            "device_id": device_id,
            "raw_payload": raw_payload,
        }
