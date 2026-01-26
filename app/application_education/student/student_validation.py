# from __future__ import annotations
#
# from datetime import date
# from typing import Optional
#
# from app.business_validation.item_validation import BizValidationError
# from app.application_education.student.models import BloodGroupEnum, OrphanStatusEnum
# from app.common.models.base import GenderEnum
#
#
# # ----------------------------
# # Generic
# # ----------------------------
# ERR_DUPLICATE_ENTRY = "Duplicate entry exists."
# ERR_USER_TYPE_NOT_FOUND = "User type 'Student' or 'Guardian' not configured."
#
# def cannot_delete_linked(doc: str, linked: str) -> str:
#     return f"Cannot delete or cancel because {doc} is linked with {linked}."
#
#
# # ----------------------------
# # Student
# # ----------------------------
# ERR_STUDENT_NOT_FOUND = "Student not found."
# ERR_STUDENT_EXISTS = "Student already exists with this name."
# ERR_STUDENT_EMAIL_EXISTS = "Email address already in use by another student."
# ERR_STUDENT_CODE_EXISTS = "Student code already exists."
# ERR_STUDENT_LEAVING_DATE = "Leaving date cannot be before joining date."
# ERR_STUDENT_BIRTH_DATE = "Birth date cannot be in the future."
# ERR_INVALID_BLOOD_GROUP = "Invalid blood group."
# ERR_INVALID_ORPHAN_STATUS = "Invalid orphan status."
# ERR_INVALID_GENDER = "Invalid gender."
#
#
# # ----------------------------
# # Guardian
# # ----------------------------
# ERR_GUARDIAN_NOT_FOUND = "Guardian not found."
# ERR_GUARDIAN_EXISTS = "Guardian already exists with this name."
# ERR_GUARDIAN_EMAIL_EXISTS = "Email address already in use by another guardian."
# ERR_GUARDIAN_MOBILE_EXISTS = "Mobile number already in use by another guardian."
# ERR_GUARDIAN_CODE_EXISTS = "Guardian code already exists."
#
#
# # ----------------------------
# # Links
# # ----------------------------
# ERR_GUARDIAN_LINK_EXISTS = "Guardian already linked to this student."
# ERR_PRIMARY_GUARDIAN_EXISTS = "Student already has a primary guardian."
#
#
# # ----------------------------
# # Validators
# # ----------------------------
# def validate_student_dates(
#     *,
#     joining_date: Optional[date],
#     leaving_date: Optional[date],
#     birth_date: Optional[date],
#     today: Optional[date] = None,
# ) -> None:
#     if joining_date and leaving_date and leaving_date < joining_date:
#         raise BizValidationError(ERR_STUDENT_LEAVING_DATE)
#
#     if birth_date:
#         t = today or date.today()
#         if birth_date > t:
#             raise BizValidationError(ERR_STUDENT_BIRTH_DATE)
#
#
# def validate_enum_blood_group(v) -> Optional[BloodGroupEnum]:
#     if v is None:
#         return None
#     if isinstance(v, BloodGroupEnum):
#         return v
#     if isinstance(v, str):
#         s = v.strip()
#         # allow enum name or enum value
#         for m in BloodGroupEnum:
#             if s == m.value or s.upper() == m.name:
#                 return m
#     raise BizValidationError(ERR_INVALID_BLOOD_GROUP)
#
#
# def validate_enum_orphan_status(v) -> Optional[OrphanStatusEnum]:
#     if v is None:
#         return None
#     if isinstance(v, OrphanStatusEnum):
#         return v
#     if isinstance(v, str):
#         s = v.strip()
#         for m in OrphanStatusEnum:
#             if s.lower() == m.value.lower() or s.upper() == m.name:
#                 return m
#     raise BizValidationError(ERR_INVALID_ORPHAN_STATUS)
#
#
# def validate_enum_gender(v) -> Optional[GenderEnum]:
#     if v is None:
#         return None
#     if isinstance(v, GenderEnum):
#         return v
#     if isinstance(v, str):
#         s = v.strip()
#         for m in GenderEnum:
#             if s.lower() == m.value.lower() or s.upper() == m.name:
#                 return m
#     raise BizValidationError(ERR_INVALID_GENDER)
from __future__ import annotations

from datetime import date
from typing import Optional

from app.business_validation.item_validation import BizValidationError
from app.application_education.student.models import BloodGroupEnum, OrphanStatusEnum
from app.common.models.base import GenderEnum, PersonRelationshipEnum


# ----------------------------
# Generic
# ----------------------------
ERR_DUPLICATE_ENTRY = "Duplicate entry exists."
ERR_USER_TYPE_NOT_FOUND = "User type 'Student' or 'Guardian' not configured."

def cannot_delete_linked(doc: str, linked: str) -> str:
    # Frappe style
    return f"Cannot delete or cancel because {doc} is linked with {linked}."


# ----------------------------
# Student
# ----------------------------
ERR_STUDENT_NOT_FOUND = "Student not found."
ERR_STUDENT_EXISTS = "Student already exists with this name."
ERR_STUDENT_EMAIL_EXISTS = "Email address already in use by another student."
ERR_STUDENT_CODE_EXISTS = "Student code already exists."
ERR_STUDENT_LEAVING_DATE = "Leaving date cannot be before joining date."
ERR_STUDENT_BIRTH_DATE = "Birth date cannot be in the future."


# ----------------------------
# Guardian
# ----------------------------
ERR_GUARDIAN_NOT_FOUND = "Guardian not found."
ERR_GUARDIAN_EXISTS = "Guardian already exists with this name."
ERR_GUARDIAN_EMAIL_EXISTS = "Email address already in use by another guardian."
ERR_GUARDIAN_MOBILE_EXISTS = "Mobile number already in use by another guardian."
ERR_GUARDIAN_CODE_EXISTS = "Guardian code already exists."


# ----------------------------
# Links
# ----------------------------
ERR_GUARDIAN_LINK_EXISTS = "Guardian already linked to this student."
ERR_PRIMARY_GUARDIAN_EXISTS = "Student already has a primary guardian."


# ----------------------------
# Enums / Relationship
# ----------------------------
ERR_INVALID_BLOOD_GROUP = "Invalid blood group."
ERR_INVALID_ORPHAN_STATUS = "Invalid orphan status."
ERR_INVALID_GENDER = "Invalid gender."
ERR_INVALID_RELATIONSHIP = "Invalid relationship."


# ----------------------------
# Validators
# ----------------------------
def validate_student_dates(
    *,
    joining_date: Optional[date],
    leaving_date: Optional[date],
    birth_date: Optional[date],
    today: Optional[date] = None,
) -> None:
    if joining_date and leaving_date and leaving_date < joining_date:
        raise BizValidationError(ERR_STUDENT_LEAVING_DATE)

    if birth_date:
        t = today or date.today()
        if birth_date > t:
            raise BizValidationError(ERR_STUDENT_BIRTH_DATE)


def validate_enum_blood_group(v) -> Optional[BloodGroupEnum]:
    if v is None:
        return None
    if isinstance(v, BloodGroupEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in BloodGroupEnum:
            if s == m.value or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_BLOOD_GROUP)


def validate_enum_orphan_status(v) -> Optional[OrphanStatusEnum]:
    if v is None:
        return None
    if isinstance(v, OrphanStatusEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in OrphanStatusEnum:
            if s.lower() == m.value.lower() or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_ORPHAN_STATUS)


def validate_enum_gender(v) -> Optional[GenderEnum]:
    if v is None:
        return None
    if isinstance(v, GenderEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in GenderEnum:
            if s.lower() == m.value.lower() or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_GENDER)


def validate_enum_relationship(v) -> PersonRelationshipEnum:
    if isinstance(v, PersonRelationshipEnum):
        return v
    if isinstance(v, str):
        s = v.strip()
        for m in PersonRelationshipEnum:
            if s.lower() == m.value.lower() or s.upper() == m.name:
                return m
    raise BizValidationError(ERR_INVALID_RELATIONSHIP)
