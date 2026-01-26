from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, Any, List, Set

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db

from app.application_education.core.base_service import BaseEducationService
from app.application_education.student.student_repo import StudentRepo
from app.application_education.student.models import Student, Guardian, StudentGuardian
from app.common.cache.cache_invalidator import (
    bump_list_cache_company,
    bump_list_cache_branch,
)
from app.business_validation.item_validation import BizValidationError
from app.application_education.student.student_validation import (
    ERR_STUDENT_NOT_FOUND,
    ERR_GUARDIAN_NOT_FOUND,
    ERR_STUDENT_EXISTS,
    ERR_GUARDIAN_EXISTS,
    ERR_STUDENT_EMAIL_EXISTS,
    ERR_GUARDIAN_EMAIL_EXISTS,
    ERR_GUARDIAN_MOBILE_EXISTS,
    ERR_GUARDIAN_LINK_EXISTS,
    ERR_PRIMARY_GUARDIAN_EXISTS,
    ERR_USER_TYPE_NOT_FOUND,
    cannot_delete_linked,
    validate_student_dates,
    validate_enum_blood_group,
    validate_enum_orphan_status,
    validate_enum_gender, ERR_STUDENT_CODE_EXISTS, validate_enum_relationship,
)

from app.common.security.password_generator import generate_random_password
from app.common.security.passwords import hash_password
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
    preview_next_username_for_company,
    bump_username_counter_for_company,
)

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope
from app.application_org.models.company import Company

log = logging.getLogger(__name__)

STU_PREFIX = "STU"
GDN_PREFIX = "GDN"


class StudentService(BaseEducationService):
    """
    Uses BaseEducationService only for tx helpers.
    Domain logic lives here (like HR service style).
    """

    def __init__(self, repo: Optional[StudentRepo] = None, session: Optional[Session] = None):
        super().__init__(model_class=Student, session=session or db.session)
        self.repo = repo or StudentRepo(session or db.session)
        self.s: Session = self.repo.s

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_company_from_branch(self, *, context: AffiliationContext, branch_id: int) -> Tuple[int, int]:
        company_id, resolved_branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=None,
            branch_id=branch_id,
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )
        return int(company_id), int(resolved_branch_id)

    def _safe_company_prefix_for_username(self, company_id: int) -> Company:
        company: Optional[Company] = db.session.get(Company, company_id)
        if not company:
            raise BizValidationError(f"Company {company_id} does not exist.")
        if not company.prefix:
            raise BizValidationError(f"Company '{company.name}' is missing a user prefix.")
        return company

    def _provision_user(
            self,
            *,
            company_id: int,
            branch_id: int,
            linked_entity_id: int,
            user_type_name: str,
    ) -> Tuple[int, str, str]:
        ut = self.repo.get_user_type_by_name(user_type_name)
        if not ut:
            raise BizValidationError(ERR_USER_TYPE_NOT_FOUND)

        company = self._safe_company_prefix_for_username(company_id)

        temp_password = generate_random_password(length=8)
        pwd_hash = hash_password(temp_password)

        user = None
        username = None
        for _ in range(25):
            candidate = preview_next_username_for_company(company)
            try:
                with self.s.begin_nested():
                    user = self.repo.create_user_and_affiliation(
                        username=candidate,
                        password_hash=pwd_hash,
                        company_id=company_id,
                        branch_id=branch_id,
                        user_type=ut,
                        linked_entity_id=linked_entity_id,
                        make_primary=True,
                    )
                    self.s.flush([user])
                bump_username_counter_for_company(company, candidate)
                username = candidate
                break
            except IntegrityError:
                bump_username_counter_for_company(company, candidate)
                continue

        if not user or not username:
            raise BizValidationError("Could not allocate a unique username. Please retry.")

        return int(user.id), username, temp_password

    # ------------------------------------------------------------------
    # Guardian CRUD
    # ------------------------------------------------------------------
    def create_guardian(
        self,
        *,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            branch_id = int(payload["branch_id"])
            company_id, branch_id = self._resolve_company_from_branch(context=context, branch_id=branch_id)

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            name = (payload.get("guardian_name") or "").strip()
            if not name:
                raise BizValidationError("Guardian name is required.")

            # pre-check by name (you requested)
            if self.repo.guardian_name_exists(company_id=company_id, branch_id=branch_id, name=name):
                raise BizValidationError(ERR_GUARDIAN_EXISTS)

            email = (payload.get("email_address") or "").strip() or None
            if email and self.repo.guardian_email_exists(company_id=company_id, branch_id=branch_id, email=email):
                raise BizValidationError(ERR_GUARDIAN_EMAIL_EXISTS)

            mobile = (payload.get("mobile_number") or "").strip() or None
            if mobile and self.repo.guardian_mobile_exists(company_id=company_id, branch_id=branch_id, mobile=mobile):
                raise BizValidationError(ERR_GUARDIAN_MOBILE_EXISTS)

            # code
            manual_code = (payload.get("guardian_code") or "").strip() or None
            if manual_code:
                ensure_manual_code_is_next_and_bump(prefix=GDN_PREFIX, company_id=company_id, branch_id=None, code=manual_code)
                if self.repo.guardian_code_exists(company_id=company_id, branch_id=branch_id, code=manual_code):
                    raise BizValidationError("Guardian code already exists.")
                code = manual_code
            else:
                code = generate_next_code(prefix=GDN_PREFIX, company_id=company_id, branch_id=None)

            g = Guardian(
                company_id=company_id,
                branch_id=branch_id,
                guardian_code=code,
                guardian_name=name,
                email_address=email,
                mobile_number=mobile,
                alternate_number=(payload.get("alternate_number") or None),
                date_of_birth=payload.get("date_of_birth"),
                education=payload.get("education"),
                occupation=payload.get("occupation"),
                work_address=payload.get("work_address"),
            )
            self.s.add(g)
            self.s.flush([g])


            # ALWAYS provision user (required)
            if not g.user_id:
                uid, username, temp_password = self._provision_user(
                    company_id=company_id,
                    branch_id=branch_id,
                    linked_entity_id=g.id,
                    user_type_name="Guardian",
                )
                g.user_id = uid
                self.s.flush([g])

            self._commit_or_flush()

            # cache bumps (best effort)
            try:
                bump_list_cache_company("education", "guardians", company_id)
                bump_list_cache_branch("education", "guardians", company_id, int(branch_id))
            except Exception:
                log.exception("[cache] failed to bump guardians list cache")

            return True, "Guardian created", {
                "id": g.id,
                "guardian_code": g.guardian_code,
                "user": {
                    "id": g.user_id,
                    "username": username,
                    "temp_password": temp_password,
                },
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_guardian_email_per_branch" in msg:
                return False, ERR_GUARDIAN_EMAIL_EXISTS, None
            if "uq_guardian_mobile_per_branch" in msg:
                return False, ERR_GUARDIAN_MOBILE_EXISTS, None
            if "uq_guardian_code_per_branch" in msg:
                return False, "Guardian code already exists.", None
            return False, "Integrity error while creating guardian.", None
        except Exception as e:
            log.exception("create_guardian failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating guardian.", None

    def update_guardian(
        self,
        *,
        guardian_id: int,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            g = self.repo.guardians.get(guardian_id)
            if not g:
                return False, ERR_GUARDIAN_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=g.company_id, target_branch_id=g.branch_id)

            data = dict(payload)

            if "guardian_name" in data and data["guardian_name"] is not None:
                name = data["guardian_name"].strip()
                if not name:
                    raise BizValidationError("Guardian name is required.")
                if self.repo.guardian_name_exists(company_id=g.company_id, branch_id=g.branch_id, name=name, exclude_id=g.id):
                    raise BizValidationError(ERR_GUARDIAN_EXISTS)
                g.guardian_name = name

            if "email_address" in data and data["email_address"] is not None:
                email = data["email_address"].strip() or None
                if email and self.repo.guardian_email_exists(company_id=g.company_id, branch_id=g.branch_id, email=email, exclude_id=g.id):
                    raise BizValidationError(ERR_GUARDIAN_EMAIL_EXISTS)
                g.email_address = email

            if "mobile_number" in data and data["mobile_number"] is not None:
                mobile = data["mobile_number"].strip() or None
                if mobile and self.repo.guardian_mobile_exists(company_id=g.company_id, branch_id=g.branch_id, mobile=mobile, exclude_id=g.id):
                    raise BizValidationError(ERR_GUARDIAN_MOBILE_EXISTS)
                g.mobile_number = mobile

            # other fields
            for f in ("alternate_number", "date_of_birth", "education", "occupation", "work_address"):
                if f in data:
                    setattr(g, f, data[f])

            # optional user creation on update
            if data.get("create_user") is True and not g.user_id:
                g.user_id = self._provision_user(
                    company_id=g.company_id,
                    branch_id=g.branch_id,
                    linked_entity_id=g.id,
                    user_type_name="Guardian",
                )

            self.s.flush([g])
            self._commit_or_flush()
            return True, "Guardian updated", {"id": g.id, "guardian_code": g.guardian_code}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_guardian failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating guardian.", None

    def delete_guardians_bulk(
            self,
            *,
            ids: List[int],
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        deleted: List[int] = []
        failed: List[Dict[str, Any]] = []

        # collect user_ids to disable (bulk)
        user_ids_to_disable: Set[int] = set()

        try:
            rows = [self.repo.guardians.get(int(i)) for i in ids]

            # scope check for found only
            for r in rows:
                if r is not None:
                    ensure_scope_by_ids(
                        context=context,
                        target_company_id=r.company_id,
                        target_branch_id=r.branch_id
                    )

            for req_id, r in zip(ids, rows):
                rid = int(req_id)

                if r is None:
                    failed.append({"id": rid, "error": ERR_GUARDIAN_NOT_FOUND})
                    continue

                # ERPNext behavior: prevent deleting Guardian if linked to any Student
                if self.repo.count_guardian_links(r.id) > 0:
                    failed.append({"id": rid, "error": cannot_delete_linked("Guardian", "Student Guardian")})
                    continue

                try:
                    # capture user before delete (object may detach)
                    uid = int(r.user_id) if getattr(r, "user_id", None) else None

                    self.s.delete(r)
                    self.s.flush()
                    deleted.append(rid)

                    if uid:
                        user_ids_to_disable.add(uid)

                except Exception as e:
                    failed.append({"id": rid, "error": str(e)})

            # bulk disable users after deletions (fast, avoids N updates)
            if user_ids_to_disable:
                self.repo.disable_users_and_affiliations_bulk(user_ids_to_disable)

            self._commit_or_flush()

            # message style
            msg = "Delete completed"
            if deleted and not failed:
                msg = f"Deleted {len(deleted)} record(s)."
            elif failed and not deleted:
                msg = f"Nothing deleted. Failed {len(failed)} record(s)."
            else:
                msg = f"Deleted {len(deleted)} record(s). Failed {len(failed)} record(s)."

            return True, msg, {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }

        except Exception as e:
            log.exception("delete_guardians_bulk failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting guardians.", None

    # ------------------------------------------------------------------
    # Student CRUD + Link add
    # ------------------------------------------------------------------
    def _apply_student_enums(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # map enums to real Enum instances for SQLAlchemy
        if "blood_group" in data:
            data["blood_group"] = validate_enum_blood_group(data["blood_group"])
        if "orphan_status" in data:
            data["orphan_status"] = validate_enum_orphan_status(data["orphan_status"])
        if "gender" in data:
            data["gender"] = validate_enum_gender(data["gender"])
        return data

    def create_student(
        self,
        *,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            branch_id = int(payload["branch_id"])
            company_id, branch_id = self._resolve_company_from_branch(context=context, branch_id=branch_id)

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            full_name = (payload.get("full_name") or "").strip()
            if not full_name:
                raise BizValidationError("Student name is required.")

            # requested name duplicate message
            if self.repo.student_name_exists(company_id=company_id, branch_id=branch_id, full_name=full_name):
                raise BizValidationError(ERR_STUDENT_EXISTS)

            email = (payload.get("student_email") or "").strip() or None
            if email and self.repo.student_email_exists(company_id=company_id, branch_id=branch_id, email=email):
                raise BizValidationError(ERR_STUDENT_EMAIL_EXISTS)

            # date validations
            validate_student_dates(
                joining_date=payload.get("joining_date"),
                leaving_date=payload.get("date_of_leaving"),
                birth_date=payload.get("date_of_birth"),
            )

            # student code
            manual = (payload.get("student_code") or "").strip() or None
            if manual:
                ensure_manual_code_is_next_and_bump(prefix=STU_PREFIX, company_id=company_id, branch_id=None, code=manual)
                if self.repo.student_code_exists(company_id=company_id, branch_id=branch_id, code=manual):
                    raise BizValidationError(ERR_STUDENT_CODE_EXISTS)
                code = manual
            else:
                code = generate_next_code(prefix=STU_PREFIX, company_id=company_id, branch_id=None)

            data = {
                "company_id": company_id,
                "branch_id": branch_id,
                "is_enabled": True,
                "student_code": code,
                "full_name": full_name,
                "joining_date": payload.get("joining_date"),
                "student_email": email,
                "date_of_birth": payload.get("date_of_birth"),
                "blood_group": payload.get("blood_group"),
                "student_mobile_number": payload.get("student_mobile_number"),
                "gender": payload.get("gender"),
                "nationality": payload.get("nationality"),
                "orphan_status": payload.get("orphan_status"),
                "date_of_leaving": payload.get("date_of_leaving"),
                "leaving_certificate_number": payload.get("leaving_certificate_number"),
                "reason_for_leaving": payload.get("reason_for_leaving"),
            }
            data = self._apply_student_enums(data)

            srow = Student(**data)
            self.s.add(srow)
            self.s.flush([srow])

            # optional guardians linking (bulk)
            guardians = payload.get("guardians") or []
            if guardians:
                for g in guardians:
                    gid = int(g["guardian_id"])
                    rel = g["relationship"]
                    is_primary = bool(g.get("is_primary", False))

                    guardian = self.repo.guardians.get(gid)
                    if not guardian or guardian.company_id != company_id:
                        raise BizValidationError(ERR_GUARDIAN_NOT_FOUND)

                    if self.repo.guardian_link_exists(student_id=srow.id, guardian_id=gid, branch_id=branch_id):
                        raise BizValidationError(ERR_GUARDIAN_LINK_EXISTS)

                    if is_primary and self.repo.student_has_primary_guardian(student_id=srow.id):
                        raise BizValidationError(ERR_PRIMARY_GUARDIAN_EXISTS)

                    rel_enum = validate_enum_relationship(rel)

                    link = StudentGuardian(
                        company_id=company_id,
                        branch_id=branch_id,
                        student_id=srow.id,
                        guardian_id=gid,
                        relationship=rel_enum,
                        is_primary=is_primary,
                    )
                    self.s.add(link)
                self.s.flush()

            # ALWAYS provision user (required)
            if not srow.user_id:
                uid, username, temp_password = self._provision_user(
                    company_id=company_id,
                    branch_id=branch_id,
                    linked_entity_id=srow.id,
                    user_type_name="Student",
                )
                srow.user_id = uid
                self.s.flush([srow])

            self._commit_or_flush()

            try:
                bump_list_cache_company("education", "students", company_id)
                bump_list_cache_branch("education", "students", company_id, int(branch_id))
            except Exception:
                log.exception("[cache] failed to bump students list cache")

            return True, "Student created", {
                "id": srow.id,
                "student_code": srow.student_code,
                "user": {
                    "id": srow.user_id,
                    "username": username,
                    "temp_password": temp_password,
                },
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_student_email_per_branch" in msg:
                return False, ERR_STUDENT_EMAIL_EXISTS, None
            if "uq_student_code_per_branch" in msg:
                return False, ERR_STUDENT_CODE_EXISTS, None
            if "uq_student_primary_guardian" in msg:
                return False, ERR_PRIMARY_GUARDIAN_EXISTS, None
            if "uq_student_guardian_link_per_branch" in msg:
                return False, ERR_GUARDIAN_LINK_EXISTS, None
            return False, "Integrity error while creating student.", None
        except Exception as e:
            log.exception("create_student failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating student.", None

    def update_student(
        self,
        *,
        student_id: int,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            srow = self.repo.students.get(student_id)
            if not srow:
                return False, ERR_STUDENT_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=srow.company_id, target_branch_id=srow.branch_id)

            data = dict(payload)

            # name duplicate check
            if "full_name" in data and data["full_name"] is not None:
                name = data["full_name"].strip()
                if not name:
                    raise BizValidationError("Student name is required.")
                if self.repo.student_name_exists(company_id=srow.company_id, branch_id=srow.branch_id, full_name=name, exclude_id=srow.id):
                    raise BizValidationError(ERR_STUDENT_EXISTS)
                srow.full_name = name

            # email duplicate check
            if "student_email" in data and data["student_email"] is not None:
                email = data["student_email"].strip() or None
                if email and self.repo.student_email_exists(company_id=srow.company_id, branch_id=srow.branch_id, email=email, exclude_id=srow.id):
                    raise BizValidationError(ERR_STUDENT_EMAIL_EXISTS)
                srow.student_email = email

            # apply enums if provided
            if "blood_group" in data:
                srow.blood_group = validate_enum_blood_group(data.get("blood_group"))
            if "orphan_status" in data:
                srow.orphan_status = validate_enum_orphan_status(data.get("orphan_status"))
            if "gender" in data:
                srow.gender = validate_enum_gender(data.get("gender"))

            # date validations using final values
            joining_date = data.get("joining_date", srow.joining_date)
            leaving_date = data.get("date_of_leaving", srow.date_of_leaving)
            birth_date = data.get("date_of_birth", srow.date_of_birth)
            validate_student_dates(joining_date=joining_date, leaving_date=leaving_date, birth_date=birth_date)

            # simple fields
            for f in (
                "is_enabled",
                "joining_date",
                "date_of_birth",
                "student_mobile_number",
                "nationality",
                "date_of_leaving",
                "leaving_certificate_number",
                "reason_for_leaving",
            ):
                if f in data:
                    setattr(srow, f, data[f])

            # append guardians (bulk)
            if data.get("guardians_add"):
                for g in data["guardians_add"]:
                    gid = int(g["guardian_id"])
                    rel = g["relationship"]
                    is_primary = bool(g.get("is_primary", False))

                    guardian = self.repo.guardians.get(gid)
                    if not guardian or guardian.company_id != srow.company_id:
                        raise BizValidationError("Guardian not found.")

                    if self.repo.guardian_link_exists(student_id=srow.id, guardian_id=gid, branch_id=srow.branch_id):
                        raise BizValidationError(ERR_GUARDIAN_LINK_EXISTS)

                    if is_primary and self.repo.student_has_primary_guardian(student_id=srow.id):
                        raise BizValidationError(ERR_PRIMARY_GUARDIAN_EXISTS)

                    link = StudentGuardian(
                        company_id=srow.company_id,
                        branch_id=srow.branch_id,
                        student_id=srow.id,
                        guardian_id=gid,
                        relationship=rel,
                        is_primary=is_primary,
                    )
                    self.s.add(link)
                self.s.flush()

            # optional user creation on update
            if data.get("create_user") is True and not srow.user_id:
                srow.user_id = self._provision_user(
                    company_id=srow.company_id,
                    branch_id=srow.branch_id,
                    linked_entity_id=srow.id,
                    user_type_name="Student",
                )

            self.s.flush([srow])
            self._commit_or_flush()
            return True, "Student updated", {"id": srow.id, "student_code": srow.student_code}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_student_email_per_branch" in msg:
                return False, ERR_STUDENT_EMAIL_EXISTS, None
            if "uq_student_primary_guardian" in msg:
                return False, ERR_PRIMARY_GUARDIAN_EXISTS, None
            if "uq_student_guardian_link_per_branch" in msg:
                return False, ERR_GUARDIAN_LINK_EXISTS, None
            return False, "Integrity error while updating student.", None
        except Exception as e:
            log.exception("update_student failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating student.", None

    def delete_students_bulk(
            self,
            *,
            ids: List[int],
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        deleted: List[int] = []
        failed: List[Dict[str, Any]] = []

        user_ids_to_disable: Set[int] = set()

        try:
            rows = [self.repo.students.get(int(i)) for i in ids]

            # scope check for found only
            for r in rows:
                if r is not None:
                    ensure_scope_by_ids(
                        context=context,
                        target_company_id=r.company_id,
                        target_branch_id=r.branch_id
                    )

            for req_id, r in zip(ids, rows):
                rid = int(req_id)

                if r is None:
                    failed.append({"id": rid, "error": ERR_STUDENT_NOT_FOUND})
                    continue

                # ERPNext-style: block delete if important documents exist (audit)
                if self.repo.student_has_sales_invoices(student_id=r.id):
                    failed.append({"id": rid, "error": cannot_delete_linked("Student", "Sales Invoice")})
                    continue

                if self.repo.student_has_sales_quotations(student_id=r.id):
                    failed.append({"id": rid, "error": cannot_delete_linked("Student", "Sales Quotation")})
                    continue

                try:
                    uid = int(r.user_id) if getattr(r, "user_id", None) else None

                    # ✅ remove only links (guardians remain)
                    self.repo.delete_student_guardian_links(student_id=r.id)

                    # delete student (enrollments cascade delete-orphan)
                    self.s.delete(r)
                    self.s.flush()
                    deleted.append(rid)

                    if uid:
                        user_ids_to_disable.add(uid)

                except Exception as e:
                    failed.append({"id": rid, "error": str(e)})

            # bulk disable users after deletions
            if user_ids_to_disable:
                self.repo.disable_users_and_affiliations_bulk(user_ids_to_disable)

            self._commit_or_flush()

            msg = "Delete completed"
            if deleted and not failed:
                msg = f"Deleted {len(deleted)} record(s)."
            elif failed and not deleted:
                msg = f"Nothing deleted. Failed {len(failed)} record(s)."
            else:
                msg = f"Deleted {len(deleted)} record(s). Failed {len(failed)} record(s)."

            return True, msg, {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }

        except Exception as e:
            log.exception("delete_students_bulk failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting students.", None
