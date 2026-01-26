from __future__ import annotations

from typing import Dict, Any, Optional, Union, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.common.date_utils import format_date_out

from app.application_education.student.models import Student, Guardian, StudentGuardian
from app.application_org.models.company import Branch
from app.auth.models.users import User


# --------------------------
# resolvers
# --------------------------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_code_strict(_: Session, __: AffiliationContext, v: str) -> str:
    vv = (v or "").strip()
    if not vv:
        raise BadRequest("Invalid identifier.")
    return vv


def resolve_id_or_code(_: Session, __: AffiliationContext, v: str) -> Union[int, str]:
    vv = (v or "").strip()
    if not vv:
        raise BadRequest("Invalid identifier.")
    if vv.isdigit():
        return int(vv)
    return vv


# --------------------------
# helpers
# --------------------------
def _ensure_company_scope(ctx: AffiliationContext, company_id: int) -> None:
    ensure_scope_by_ids(context=ctx, target_company_id=int(company_id), target_branch_id=None)


def _status_bool_to_label(is_enabled: bool) -> str:
    # ERPNext-like: "Enabled"/"Disabled"
    return "Enabled" if bool(is_enabled) else "Disabled"


def _enum_value(v) -> Optional[str]:
    if v is None:
        return None
    # works for Enum or string
    return getattr(v, "value", str(v))


# --------------------------
# Student Detail Loader
# --------------------------
def load_student_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Student detail by ID or code (default_by=code).
    Returns:
      - Student Information (core fields)
      - Parents' Information (guardians list)
      - Program Enrollments (best-effort)
      - Account (username/status)
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    # ---- main student row (include username + branch name) ----
    q = (
        select(
            Student.id,
            Student.company_id,
            Student.branch_id,
            Branch.name.label("branch_name"),

            Student.student_code,
            Student.full_name,
            Student.is_enabled,
            Student.joining_date,
            Student.student_email,
            Student.date_of_birth,
            Student.blood_group,
            Student.student_mobile_number,
            Student.gender,
            Student.nationality,
            Student.orphan_status,

            Student.date_of_leaving,
            Student.leaving_certificate_number,
            Student.reason_for_leaving,

            Student.user_id,
            User.username.label("username"),

            Student.created_at,
            Student.updated_at,
        )
        .select_from(Student)
        .outerjoin(Branch, Branch.id == Student.branch_id)
        .outerjoin(User, User.id == Student.user_id)
        .where(Student.company_id == int(co_id))
    )

    if isinstance(identifier, int):
        q = q.where(Student.id == int(identifier))
    else:
        q = q.where(Student.student_code == str(identifier))

    row = s.execute(q).mappings().first()
    if not row:
        raise NotFound("Student not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))

    student_id = int(row["id"])

    # ---- guardians (Parents' Information) ----
    gq = (
        select(
            StudentGuardian.id.label("link_id"),
            StudentGuardian.guardian_id.label("guardian_id"),
            Guardian.guardian_code.label("guardian_code"),
            Guardian.guardian_name.label("guardian_name"),
            Guardian.mobile_number.label("mobile_number"),
            Guardian.email_address.label("email_address"),
            StudentGuardian.relationship.label("relationship"),
            StudentGuardian.is_primary.label("is_primary"),
        )
        .select_from(StudentGuardian)
        .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
        .where(StudentGuardian.student_id == student_id)
        .order_by(StudentGuardian.is_primary.desc(), func.lower(Guardian.guardian_name).asc())
    )
    guardians = []
    for r in s.execute(gq).mappings().all():
        guardians.append({
            "id": int(r["guardian_id"]),
            "code": r["guardian_code"],
            "name": r["guardian_name"],
            "mobile_number": r["mobile_number"],
            "email_address": r["email_address"],
            "relationship": _enum_value(r["relationship"]),
            "is_primary": bool(r["is_primary"]),
            "link_id": int(r["link_id"]),
        })

    # ---- program enrollments (best-effort) ----
    enrollments: List[Dict[str, Any]] = []
    try:
        from app.application_education.enrollments.enrollment_model import ProgramEnrollment
        # Try also importing Program name if exists (optional)
        # If Program model path differs, this will still work with just IDs.
        eq = (
            select(
                ProgramEnrollment.id.label("id"),
                ProgramEnrollment.program_id.label("program_id"),
            )
            .select_from(ProgramEnrollment)
            .where(ProgramEnrollment.student_id == student_id)
            .order_by(ProgramEnrollment.id.desc())
        )
        enrollments = [
            {"id": int(x["id"]), "program_id": int(x["program_id"]) if x["program_id"] else None}
            for x in s.execute(eq).mappings().all()
        ]
    except Exception:
        enrollments = []

    # ---- format dates ----
    def fd(v):
        return format_date_out(v) if v else None

    return {
        "id": student_id,
        "code": row["student_code"],
        "student_name": row["full_name"],
        "status": _status_bool_to_label(bool(row["is_enabled"])),
        "branch": {"id": int(row["branch_id"]), "name": row["branch_name"]},
        "student_information": {
            "joining_date": fd(row["joining_date"]),
            "student_email": row["student_email"],
            "date_of_birth": fd(row["date_of_birth"]),
            "blood_group": _enum_value(row["blood_group"]),
            "student_mobile_number": row["student_mobile_number"],
            "gender": _enum_value(row["gender"]),
            "nationality": row["nationality"],
            "orphan_status": _enum_value(row["orphan_status"]),
            "date_of_leaving": fd(row["date_of_leaving"]),
            "leaving_certificate_number": row["leaving_certificate_number"],
            "reason_for_leaving": row["reason_for_leaving"],
        },
        "parents_information": guardians,
        "program_enrollments": enrollments,
        "account": {
            "user_id": int(row["user_id"]) if row["user_id"] else None,
            "username": row["username"],
        },
        "created_at": fd(row["created_at"]),
        "updated_at": fd(row["updated_at"]),
    }


# --------------------------
# Guardian Detail Loader
# --------------------------
def load_guardian_detail(s: Session, ctx: AffiliationContext, identifier: Union[int, str]) -> Dict[str, Any]:
    """
    Guardian detail by ID or code (default_by=code).
    Returns:
      - Guardian Information (all fields)
      - Account (username)
      - Guardian Of (students list)
    """
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")

    q = (
        select(
            Guardian.id,
            Guardian.company_id,
            Guardian.branch_id,
            Branch.name.label("branch_name"),

            Guardian.guardian_code,
            Guardian.guardian_name,
            Guardian.email_address,
            Guardian.mobile_number,
            Guardian.alternate_number,
            Guardian.date_of_birth,
            Guardian.education,
            Guardian.occupation,
            Guardian.work_address,

            Guardian.user_id,
            User.username.label("username"),

            Guardian.created_at,
            Guardian.updated_at,
        )
        .select_from(Guardian)
        .outerjoin(Branch, Branch.id == Guardian.branch_id)
        .outerjoin(User, User.id == Guardian.user_id)
        .where(Guardian.company_id == int(co_id))
    )

    if isinstance(identifier, int):
        q = q.where(Guardian.id == int(identifier))
    else:
        q = q.where(Guardian.guardian_code == str(identifier))

    row = s.execute(q).mappings().first()
    if not row:
        raise NotFound("Guardian not found.")

    _ensure_company_scope(ctx, int(row["company_id"]))

    guardian_id = int(row["id"])

    # ---- Guardian Of (students list) ----
    sq = (
        select(
            Student.id.label("student_id"),
            Student.student_code.label("student_code"),
            Student.full_name.label("student_name"),
            StudentGuardian.relationship.label("relationship"),
            StudentGuardian.is_primary.label("is_primary"),
        )
        .select_from(StudentGuardian)
        .join(Student, Student.id == StudentGuardian.student_id)
        .where(StudentGuardian.guardian_id == guardian_id)
        .order_by(StudentGuardian.is_primary.desc(), func.lower(Student.full_name).asc())
    )

    guardian_of = []
    for r in s.execute(sq).mappings().all():
        guardian_of.append({
            "id": int(r["student_id"]),
            "code": r["student_code"],
            "name": r["student_name"],
            "relationship": _enum_value(r["relationship"]),
            "is_primary": bool(r["is_primary"]),
        })

    def fd(v):
        return format_date_out(v) if v else None

    return {
        "id": guardian_id,
        "code": row["guardian_code"],
        "guardian_name": row["guardian_name"],
        "branch": {"id": int(row["branch_id"]), "name": row["branch_name"]},
        "guardian_information": {
            "email_address": row["email_address"],
            "mobile_number": row["mobile_number"],
            "alternate_number": row["alternate_number"],
            "date_of_birth": fd(row["date_of_birth"]),
            "education": row["education"],
            "occupation": row["occupation"],
            "work_address": row["work_address"],
        },
        "account": {
            "user_id": int(row["user_id"]) if row["user_id"] else None,
            "username": row["username"],
        },
        "guardian_of": guardian_of,
        "created_at": fd(row["created_at"]),
        "updated_at": fd(row["updated_at"]),
    }
