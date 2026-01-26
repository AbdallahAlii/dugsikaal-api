from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from app.application_hr.models.biometric_dp4500 import FingerIndexEnum


class DP4500EnrollIn(BaseModel):
    company_id: Optional[int] = None
    employee_id: Optional[int] = None
    device_employee_id: Optional[str] = None
    finger_index: FingerIndexEnum = FingerIndexEnum.UNKNOWN


class DP4500VerifyIn(BaseModel):
    company_id: Optional[int] = None
    employee_id: Optional[int] = None
    device_employee_id: Optional[str] = None
    finger_index: FingerIndexEnum = FingerIndexEnum.UNKNOWN
