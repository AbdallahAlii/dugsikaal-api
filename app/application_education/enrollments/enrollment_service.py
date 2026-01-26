from __future__ import annotations

import logging
from datetime import date
from typing import Optional, Dict, Any, Tuple, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.application_education.core.base_service import BaseEducationService
from app.business_validation.item_validation import BizValidationError

from app.application_education.enrollments.enrollment_repo import EnrollmentRepo
from app.application_education.enrollments.enrollment_model import (
    ProgramEnrollment,
    CourseEnrollment,
    EnrollmentStatusEnum,
    EnrollmentResultEnum,
)

from app.application_education.enrollments.enrollment_validation import (
    ERR_SELECTED_STUDENT_NOT_FOUND,
    ERR_SELECTED_PROGRAM_NOT_FOUND,
    ERR_SELECTED_ACADEMIC_YEAR_NOT_FOUND,
    ERR_SELECTED_ACADEMIC_TERM_NOT_FOUND,
    ERR_SELECTED_BRANCH_NOT_FOUND,
    ERR_SELECTED_BATCH_NOT_FOUND,
    ERR_SELECTED_GROUP_NOT_FOUND,
    ERR_INVALID_ENROLLMENT_STATUS,
    ERR_INVALID_RESULT_STATUS,
    ERR_GROUP_NOT_IN_PROGRAM,
    ERR_GROUP_YEAR_MISMATCH,
    ERR_GROUP_TERM_MISMATCH,
    ERR_COURSE_SELECTED_MULTIPLE_TIMES,
    ERR_COURSE_NOT_FOUND_IDS,
    ERR_COURSE_ENROLLMENT_EXISTS,
    ERR_NO_CURRICULUM_FOUND,
    err_student_already_enrolled,
    validate_enrollment_status,
    validate_result_status,
    validate_program_enrollment_dates,
    validate_course_enrollment_dates,
    ensure_no_duplicate_ids, ERR_SELECTED_COURSE_NOT_FOUND, ERR_PROGRAM_ENROLLMENT_NOT_FOUND,
    ERR_ONLY_DRAFT_CAN_BE_SUBMITTED, ERR_COURSE_ENROLLMENT_NOT_FOUND,
)

from app.common.generate_code.service import generate_next_code
from app.common.cache.cache_invalidator import bump_list_cache_company, bump_list_cache_branch

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope

log = logging.getLogger(__name__)

ENR_PREFIX = "ENR"
CE_PREFIX = "CE"


class EnrollmentService(BaseEducationService):
    def __init__(self, repo: Optional[EnrollmentRepo] = None, session: Optional[Session] = None):
        super().__init__(model_class=ProgramEnrollment, session=session or db.session)
        self.repo = repo or EnrollmentRepo(session or db.session)
        self.s: Session = self.repo.s

    # ----------------------------
    # helpers
    # ----------------------------
    def _resolve_company_branch(self, *, context: AffiliationContext, branch_id: int) -> Tuple[int, int]:
        company_id, resolved_branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=None,
            branch_id=branch_id,
            get_branch_company_id=lambda bid: self.s.scalar(
                # Branch model in org has company_id
                # (we use repo.get_branch later; this is just for resolver)
                # fallback if you already have helper in org repo, swap it
                # keep it minimal:
                __import__("sqlalchemy").select(__import__("app.application_org.models.company", fromlist=["Branch"]).Branch.company_id)
                .where(__import__("app.application_org.models.company", fromlist=["Branch"]).Branch.id == int(bid))
            ),
            require_branch=True,
        )
        return int(company_id), int(resolved_branch_id)

    def _bump_enrollment_caches(self, *, company_id: int, branch_id: int) -> None:
        try:
            bump_list_cache_company("education", "program_enrollments", company_id)
            bump_list_cache_branch("education", "program_enrollments", company_id, int(branch_id))
            bump_list_cache_company("education", "course_enrollments", company_id)
            bump_list_cache_branch("education", "course_enrollments", company_id, int(branch_id))
        except Exception:
            log.exception("[cache] failed bump enrollment caches")

    # ----------------------------
    # Curriculum endpoint logic
    # ----------------------------
    def get_program_curriculum_courses(
        self,
        *,
        program_id: int,
        context: AffiliationContext,
        curriculum_version: int = 1,
        on_date: Optional[date] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        For UI auto-fill: ProgramCourse -> Course list
        """
        try:
            # program must be in same company
            company_id = int(context.company_id)
            prog = self.repo.get_program(company_id=company_id, program_id=int(program_id))
            if not prog:
                return False, ERR_SELECTED_PROGRAM_NOT_FOUND, None

            rows = self.repo.get_program_curriculum(
                company_id=company_id,
                program_id=int(program_id),
                curriculum_version=int(curriculum_version),
                on_date=on_date,
            )
            if not rows:
                raise BizValidationError(ERR_NO_CURRICULUM_FOUND)

            enrolled_courses = []
            for pc, c in rows:
                enrolled_courses.append(
                    dict(
                        program_course_id=pc.id,
                        course_id=c.id,
                        course_name=c.name,
                        is_mandatory=bool(pc.is_mandatory),
                        sequence_no=pc.sequence_no,
                    )
                )

            return True, "Program curriculum courses", dict(
                program_id=int(program_id),
                curriculum_version=int(curriculum_version),
                enrolled_courses=enrolled_courses,
            )

        except BizValidationError as e:
            return False, str(e), None
        except Exception as e:
            log.exception("get_program_curriculum_courses failed: %s", e)
            return False, "Unexpected error while reading curriculum.", None

    # ----------------------------
    # Program Enrollment create
    # ----------------------------
    def create_program_enrollment(
        self,
        *,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            branch_id = int(payload["branch_id"])
            company_id, branch_id = self._resolve_company_branch(context=context, branch_id=branch_id)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            student_id = int(payload["student_id"])
            program_id = int(payload["program_id"])
            year_id = int(payload["academic_year_id"])
            term_id = payload.get("academic_term_id")
            if term_id is not None:
                term_id = int(term_id)

            # ---- load core entities (company scoped) ----
            student = self.repo.get_student(company_id=company_id, student_id=student_id)
            if not student:
                raise BizValidationError(ERR_SELECTED_STUDENT_NOT_FOUND)

            program = self.repo.get_program(company_id=company_id, program_id=program_id)
            if not program:
                raise BizValidationError(ERR_SELECTED_PROGRAM_NOT_FOUND)

            year = self.repo.get_year(company_id=company_id, year_id=year_id)
            if not year:
                raise BizValidationError(ERR_SELECTED_ACADEMIC_YEAR_NOT_FOUND)

            if term_id is not None:
                term = self.repo.get_term(company_id=company_id, term_id=term_id)
                if not term:
                    raise BizValidationError(ERR_SELECTED_ACADEMIC_TERM_NOT_FOUND)

            branch = self.repo.get_branch(company_id=company_id, branch_id=branch_id)
            if not branch:
                raise BizValidationError(ERR_SELECTED_BRANCH_NOT_FOUND)

            # batch optional
            batch_id = payload.get("batch_id")
            if batch_id is not None:
                batch = self.repo.get_batch(company_id=company_id, batch_id=int(batch_id))
                if not batch:
                    raise BizValidationError(ERR_SELECTED_BATCH_NOT_FOUND)

            # group optional + validations
            group_id = payload.get("student_group_id")
            if group_id is not None:
                grp = self.repo.get_group(company_id=company_id, group_id=int(group_id))
                if not grp:
                    raise BizValidationError(ERR_SELECTED_GROUP_NOT_FOUND)
                if int(grp.program_id) != int(program_id):
                    raise BizValidationError(ERR_GROUP_NOT_IN_PROGRAM)
                if grp.academic_year_id is not None and int(grp.academic_year_id) != int(year_id):
                    raise BizValidationError(ERR_GROUP_YEAR_MISMATCH)
                if term_id is not None and grp.academic_term_id is not None and int(grp.academic_term_id) != int(term_id):
                    raise BizValidationError(ERR_GROUP_TERM_MISMATCH)

            # ---- duplicate enrollment check ----
            if self.repo.program_enrollment_exists(
                company_id=company_id,
                student_id=student_id,
                program_id=program_id,
                academic_year_id=year_id,
            ):
                raise BizValidationError(err_student_already_enrolled(program.name, year.name))

            # ---- dates sanity ----
            validate_program_enrollment_dates(
                admission_date=payload.get("admission_date"),
                enrollment_date=payload.get("enrollment_date"),
                completion_date=payload.get("completion_date"),
                cancellation_date=payload.get("cancellation_date"),
            )

            # ---- status defaults (your rule) ----
            submit = bool(payload.get("submit", False))
            enrollment_status = EnrollmentStatusEnum.ENROLLED if submit else EnrollmentStatusEnum.DRAFT
            result_status = EnrollmentResultEnum.NONE  # your rule: default None

            # ---- code ----
            enrollment_code = generate_next_code(prefix=ENR_PREFIX, company_id=company_id, branch_id=None)

            pe = ProgramEnrollment(
                company_id=company_id,
                enrollment_code=enrollment_code,
                student_id=student_id,
                program_id=program_id,
                academic_year_id=year_id,
                academic_term_id=term_id,
                batch_id=payload.get("batch_id"),
                branch_id=branch_id,
                student_group_id=payload.get("student_group_id"),
                enrollment_status=enrollment_status,
                result_status=result_status,
                application_date=payload.get("application_date"),
                admission_date=payload.get("admission_date"),
                enrollment_date=payload.get("enrollment_date"),
                completion_date=payload.get("completion_date"),
                cancellation_date=payload.get("cancellation_date"),
                remarks=payload.get("remarks"),
            )
            self.s.add(pe)
            self.s.flush([pe])

            # ---- child courses creation (only if provided AND submit=True OR Draft allowed?) ----
            # Your requirement: Draft is allowed, but when submit happens it should enroll.
            # Here: if enrolled_course_ids are provided, we create them immediately with matching status to pe.
            course_ids = payload.get("enrolled_course_ids") or []
            # strict duplicate detection (you asked)
            course_ids = ensure_no_duplicate_ids(course_ids, err_msg=ERR_COURSE_SELECTED_MULTIPLE_TIMES)

            if course_ids:
                # bulk fetch
                courses = self.repo.get_courses_by_ids(company_id=company_id, course_ids=course_ids, only_enabled=True)
                found = {c.id for c in courses}
                missing = [cid for cid in course_ids if cid not in found]
                if missing:
                    raise BizValidationError(ERR_COURSE_NOT_FOUND_IDS.format(ids=", ".join(map(str, missing))))

                # create rows (bulk add)
                ce_status = EnrollmentStatusEnum.ENROLLED if submit else EnrollmentStatusEnum.DRAFT
                for cid in course_ids:
                    # avoid DB constraint hit with friendly error (fast exists check)
                    if self.repo.course_enrollment_exists(
                        company_id=company_id,
                        branch_id=branch_id,
                        student_id=student_id,
                        course_id=int(cid),
                        academic_year_id=year_id,
                        academic_term_id=term_id,
                    ):
                        raise BizValidationError(ERR_COURSE_ENROLLMENT_EXISTS)

                    ce_code = generate_next_code(prefix=CE_PREFIX, company_id=company_id, branch_id=None)
                    ce = CourseEnrollment(
                        company_id=company_id,
                        enrollment_code=ce_code,
                        student_id=student_id,
                        course_id=int(cid),
                        program_enrollment_id=pe.id,
                        academic_year_id=year_id,
                        academic_term_id=term_id,
                        branch_id=branch_id,
                        enrollment_status=ce_status,
                        enrollment_date=payload.get("enrollment_date"),
                        completion_date=None,
                        cancellation_date=None,
                        remarks=payload.get("remarks"),
                    )
                    self.s.add(ce)

                self.s.flush()

            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=branch_id)

            return True, "Program enrollment created", dict(
                program_enrollment_id=int(pe.id),
                enrollment_code=pe.enrollment_code,
                student_id=int(pe.student_id),
            )

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_enrollment_per_program_year" in msg:
                # fallback if race condition
                return False, "Student is already enrolled for this program and academic year.", None
            if "uq_ce_company_branch_student_course_year_term" in msg:
                return False, ERR_COURSE_ENROLLMENT_EXISTS, None
            return False, "Integrity error while creating enrollment.", None
        except Exception as e:
            log.exception("create_program_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating program enrollment.", None

    # ----------------------------
    # Program Enrollment update
    # ----------------------------
    def update_program_enrollment(
        self,
        *,
        program_enrollment_id: int,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)

            pe = self.repo.get_program_enrollment(company_id=company_id, enrollment_id=int(program_enrollment_id))
            if not pe:
                return False, "Selected program enrollment was not found.", None

            ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)

            # validate group changes if provided
            if "student_group_id" in payload and payload["student_group_id"] is not None:
                grp = self.repo.get_group(company_id=company_id, group_id=int(payload["student_group_id"]))
                if not grp:
                    raise BizValidationError(ERR_SELECTED_GROUP_NOT_FOUND)
                if int(grp.program_id) != int(pe.program_id):
                    raise BizValidationError(ERR_GROUP_NOT_IN_PROGRAM)
                if grp.academic_year_id is not None and int(grp.academic_year_id) != int(pe.academic_year_id):
                    raise BizValidationError(ERR_GROUP_YEAR_MISMATCH)
                if pe.academic_term_id is not None and grp.academic_term_id is not None and int(grp.academic_term_id) != int(pe.academic_term_id):
                    raise BizValidationError(ERR_GROUP_TERM_MISMATCH)

            # date sanity using new values
            admission_date = payload.get("admission_date", pe.admission_date)
            enrollment_date = payload.get("enrollment_date", pe.enrollment_date)
            completion_date = payload.get("completion_date", pe.completion_date)
            cancellation_date = payload.get("cancellation_date", pe.cancellation_date)
            validate_program_enrollment_dates(
                admission_date=admission_date,
                enrollment_date=enrollment_date,
                completion_date=completion_date,
                cancellation_date=cancellation_date,
            )

            # patch fields
            for f in (
                "academic_term_id",
                "batch_id",
                "student_group_id",
                "application_date",
                "admission_date",
                "enrollment_date",
                "completion_date",
                "cancellation_date",
                "remarks",
            ):
                if f in payload:
                    setattr(pe, f, payload[f])

            # enums (optional)
            if "enrollment_status" in payload and payload["enrollment_status"] is not None:
                pe.enrollment_status = validate_enrollment_status(payload["enrollment_status"])
            if "result_status" in payload and payload["result_status"] is not None:
                pe.result_status = validate_result_status(payload["result_status"])

            # submit action (preferred)
            if payload.get("submit") is True:
                pe.enrollment_status = EnrollmentStatusEnum.ENROLLED
                # when submitting, also submit any existing course rows linked
                for ce in (pe.course_enrollments or []):
                    if ce.enrollment_status == EnrollmentStatusEnum.DRAFT:
                        ce.enrollment_status = EnrollmentStatusEnum.ENROLLED

            # enrolled_course_ids update logic:
            # if provided, we treat as "set desired list" and add missing course enrollments (no auto-delete)
            course_ids = payload.get("enrolled_course_ids", None)
            if course_ids is not None:
                course_ids = ensure_no_duplicate_ids(course_ids, err_msg=ERR_COURSE_SELECTED_MULTIPLE_TIMES)

                if course_ids:
                    courses = self.repo.get_courses_by_ids(company_id=company_id, course_ids=course_ids, only_enabled=True)
                    found = {c.id for c in courses}
                    missing = [cid for cid in course_ids if cid not in found]
                    if missing:
                        raise BizValidationError(ERR_COURSE_NOT_FOUND_IDS.format(ids=", ".join(map(str, missing))))

                    # existing linked courses
                    existing = {int(x.course_id) for x in (pe.course_enrollments or [])}
                    to_add = [cid for cid in course_ids if int(cid) not in existing]

                    ce_status = EnrollmentStatusEnum.ENROLLED if pe.enrollment_status == EnrollmentStatusEnum.ENROLLED else EnrollmentStatusEnum.DRAFT

                    for cid in to_add:
                        if self.repo.course_enrollment_exists(
                            company_id=company_id,
                            branch_id=int(pe.branch_id),
                            student_id=int(pe.student_id),
                            course_id=int(cid),
                            academic_year_id=int(pe.academic_year_id),
                            academic_term_id=pe.academic_term_id,
                        ):
                            raise BizValidationError(ERR_COURSE_ENROLLMENT_EXISTS)

                        ce_code = generate_next_code(prefix=CE_PREFIX, company_id=company_id, branch_id=None)
                        ce = CourseEnrollment(
                            company_id=company_id,
                            enrollment_code=ce_code,
                            student_id=int(pe.student_id),
                            course_id=int(cid),
                            program_enrollment_id=int(pe.id),
                            academic_year_id=int(pe.academic_year_id),
                            academic_term_id=pe.academic_term_id,
                            branch_id=int(pe.branch_id),
                            enrollment_status=ce_status,
                            enrollment_date=pe.enrollment_date,
                            remarks=pe.remarks,
                        )
                        self.s.add(ce)

            self.s.flush([pe])
            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(pe.branch_id))

            return True, "Program enrollment updated", dict(
                program_enrollment_id=int(pe.id),
                enrollment_code=pe.enrollment_code,
                student_id=int(pe.student_id),
            )

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_ce_company_branch_student_course_year_term" in msg:
                return False, ERR_COURSE_ENROLLMENT_EXISTS, None
            return False, "Integrity error while updating program enrollment.", None
        except Exception as e:
            log.exception("update_program_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating program enrollment.", None

    # ----------------------------
    # Course Enrollment create (manual)
    # ----------------------------
    def create_course_enrollment(
        self,
        *,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            branch_id = int(payload["branch_id"])
            company_id, branch_id = self._resolve_company_branch(context=context, branch_id=branch_id)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

            student_id = int(payload["student_id"])
            course_id = int(payload["course_id"])
            year_id = int(payload["academic_year_id"])
            term_id = payload.get("academic_term_id")
            if term_id is not None:
                term_id = int(term_id)

            student = self.repo.get_student(company_id=company_id, student_id=student_id)
            if not student:
                raise BizValidationError(ERR_SELECTED_STUDENT_NOT_FOUND)

            course = self.repo.get_course(company_id=company_id, course_id=course_id)
            if not course:
                raise BizValidationError(ERR_SELECTED_COURSE_NOT_FOUND)

            year = self.repo.get_year(company_id=company_id, year_id=year_id)
            if not year:
                raise BizValidationError(ERR_SELECTED_ACADEMIC_YEAR_NOT_FOUND)

            if term_id is not None:
                term = self.repo.get_term(company_id=company_id, term_id=term_id)
                if not term:
                    raise BizValidationError(ERR_SELECTED_ACADEMIC_TERM_NOT_FOUND)

            branch = self.repo.get_branch(company_id=company_id, branch_id=branch_id)
            if not branch:
                raise BizValidationError(ERR_SELECTED_BRANCH_NOT_FOUND)

            # link to program_enrollment optional (must be in same company)
            pe_id = payload.get("program_enrollment_id")
            if pe_id is not None:
                pe = self.repo.get_program_enrollment(company_id=company_id, enrollment_id=int(pe_id))
                if not pe:
                    return False, "Selected program enrollment was not found.", None
                # also must match student + branch + year (+ term)
                if int(pe.student_id) != student_id:
                    return False, "Selected program enrollment does not belong to this student.", None
                if int(pe.branch_id) != branch_id:
                    return False, "Selected program enrollment does not match the selected branch.", None
                if int(pe.academic_year_id) != year_id:
                    return False, "Selected program enrollment does not match the selected academic year.", None
                if (pe.academic_term_id or None) != (term_id or None):
                    return False, "Selected program enrollment does not match the selected academic term.", None

            # exists check (friendly)
            if self.repo.course_enrollment_exists(
                company_id=company_id,
                branch_id=branch_id,
                student_id=student_id,
                course_id=course_id,
                academic_year_id=year_id,
                academic_term_id=term_id,
            ):
                raise BizValidationError(ERR_COURSE_ENROLLMENT_EXISTS)

            validate_course_enrollment_dates(
                enrollment_date=payload.get("enrollment_date"),
                completion_date=payload.get("completion_date"),
                cancellation_date=payload.get("cancellation_date"),
            )

            submit = bool(payload.get("submit", False))
            status = EnrollmentStatusEnum.ENROLLED if submit else EnrollmentStatusEnum.DRAFT

            ce_code = generate_next_code(prefix=CE_PREFIX, company_id=company_id, branch_id=None)
            ce = CourseEnrollment(
                company_id=company_id,
                enrollment_code=ce_code,
                student_id=student_id,
                course_id=course_id,
                program_enrollment_id=payload.get("program_enrollment_id"),
                academic_year_id=year_id,
                academic_term_id=term_id,
                branch_id=branch_id,
                enrollment_status=status,
                enrollment_date=payload.get("enrollment_date"),
                completion_date=payload.get("completion_date"),
                cancellation_date=payload.get("cancellation_date"),
                remarks=payload.get("remarks"),
            )
            self.s.add(ce)
            self.s.flush([ce])

            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=branch_id)

            return True, "Course enrollment created", dict(
                course_enrollment_id=int(ce.id),
                enrollment_code=ce.enrollment_code,
                student_id=int(ce.student_id),
            )

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_COURSE_ENROLLMENT_EXISTS, None
        except Exception as e:
            log.exception("create_course_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating course enrollment.", None

    # ----------------------------
    # Course Enrollment update
    # ----------------------------
    def update_course_enrollment(
        self,
        *,
        course_enrollment_id: int,
        payload: Dict[str, Any],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)
            ce = self.repo.get_course_enrollment(company_id=company_id, enrollment_id=int(course_enrollment_id))
            if not ce:
                return False, "Selected course enrollment was not found.", None

            ensure_scope_by_ids(context=context, target_company_id=ce.company_id, target_branch_id=ce.branch_id)

            # date sanity
            enrollment_date = payload.get("enrollment_date", ce.enrollment_date)
            completion_date = payload.get("completion_date", ce.completion_date)
            cancellation_date = payload.get("cancellation_date", ce.cancellation_date)
            validate_course_enrollment_dates(
                enrollment_date=enrollment_date,
                completion_date=completion_date,
                cancellation_date=cancellation_date,
            )

            # patch fields
            for f in ("academic_term_id", "program_enrollment_id", "enrollment_date", "completion_date", "cancellation_date", "remarks"):
                if f in payload:
                    setattr(ce, f, payload[f])

            # status (optional)
            if "enrollment_status" in payload and payload["enrollment_status"] is not None:
                ce.enrollment_status = validate_enrollment_status(payload["enrollment_status"])

            # submit action
            if payload.get("submit") is True:
                ce.enrollment_status = EnrollmentStatusEnum.ENROLLED

            self.s.flush([ce])
            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(ce.branch_id))

            return True, "Course enrollment updated", dict(
                course_enrollment_id=int(ce.id),
                enrollment_code=ce.enrollment_code,
                student_id=int(ce.student_id),
            )

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_course_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating course enrollment.", None

    # ----------------------------
    # Deletes (single + bulk)
    # ----------------------------
    def delete_program_enrollment_single(
        self,
        *,
        program_enrollment_id: int,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)
            pe = self.repo.get_program_enrollment(company_id=company_id, enrollment_id=int(program_enrollment_id))
            if not pe:
                return False, "Selected program enrollment was not found.", None

            ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)

            branch_id = int(pe.branch_id)
            self.s.delete(pe)
            self.s.flush()

            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=branch_id)

            return True, "Program enrollment deleted", {"id": int(program_enrollment_id)}
        except Exception as e:
            log.exception("delete_program_enrollment_single failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting program enrollment.", None

    def delete_program_enrollment_bulk(
        self,
        *,
        ids: List[int],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)
            # scope safety: verify each record belongs to user scope before delete
            rows = [self.repo.get_program_enrollment(company_id=company_id, enrollment_id=int(i)) for i in ids]

            deleted = []
            failed = []
            for req_id, pe in zip(ids, rows):
                rid = int(req_id)
                if not pe:
                    failed.append({"id": rid, "error": "Selected program enrollment was not found."})
                    continue
                ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)
                self.s.delete(pe)
                self.s.flush()
                deleted.append(rid)

            self._commit_or_flush()

            # bump company scope; branch-specific bump would need branches set, keep it simple
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(context.branch_id or 0) or 0)

            msg = f"Deleted {len(deleted)} record(s)."
            if failed:
                msg = f"Deleted {len(deleted)} record(s). Failed {len(failed)} record(s)."

            return True, msg, {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }
        except Exception as e:
            log.exception("delete_program_enrollment_bulk failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting program enrollments.", None

    def delete_course_enrollment_single(
        self,
        *,
        course_enrollment_id: int,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)
            ce = self.repo.get_course_enrollment(company_id=company_id, enrollment_id=int(course_enrollment_id))
            if not ce:
                return False, "Selected course enrollment was not found.", None

            ensure_scope_by_ids(context=context, target_company_id=ce.company_id, target_branch_id=ce.branch_id)

            branch_id = int(ce.branch_id)
            self.s.delete(ce)
            self.s.flush()

            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=branch_id)

            return True, "Course enrollment deleted", {"id": int(course_enrollment_id)}
        except Exception as e:
            log.exception("delete_course_enrollment_single failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting course enrollment.", None

    def delete_course_enrollment_bulk(
        self,
        *,
        ids: List[int],
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = int(context.company_id)
            rows = [self.repo.get_course_enrollment(company_id=company_id, enrollment_id=int(i)) for i in ids]

            deleted = []
            failed = []
            for req_id, ce in zip(ids, rows):
                rid = int(req_id)
                if not ce:
                    failed.append({"id": rid, "error": "Selected course enrollment was not found."})
                    continue
                ensure_scope_by_ids(context=context, target_company_id=ce.company_id, target_branch_id=ce.branch_id)
                self.s.delete(ce)
                self.s.flush()
                deleted.append(rid)

            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(context.branch_id or 0) or 0)

            msg = f"Deleted {len(deleted)} record(s)."
            if failed:
                msg = f"Deleted {len(deleted)} record(s). Failed {len(failed)} record(s)."

            return True, msg, {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }
        except Exception as e:
            log.exception("delete_course_enrollment_bulk failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while deleting course enrollments.", None

    def submit_program_enrollment(
            self,
            *,
            program_enrollment_id: int,
            enrolled_course_ids: Optional[List[int]],
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Submit ProgramEnrollment:
          - Draft -> Enrolled
          - Optionally add missing enrolled_course_ids at submit time
          - Ensure all child CourseEnrollments are Enrolled (create missing if provided)
        """
        try:
            company_id = int(context.company_id)

            pe = self.repo.get_program_enrollment(company_id=company_id, enrollment_id=int(program_enrollment_id))
            if not pe:
                return False, ERR_PROGRAM_ENROLLMENT_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)

            if pe.enrollment_status != EnrollmentStatusEnum.DRAFT:
                raise BizValidationError(ERR_ONLY_DRAFT_CAN_BE_SUBMITTED)

            # Set parent to Enrolled
            pe.enrollment_status = EnrollmentStatusEnum.ENROLLED

            # Step 1: submit existing child rows
            for ce in (pe.course_enrollments or []):
                if ce.enrollment_status == EnrollmentStatusEnum.DRAFT:
                    ce.enrollment_status = EnrollmentStatusEnum.ENROLLED

            # Step 2: if UI sends course list at submit time, add missing course enrollments
            if enrolled_course_ids is not None:
                course_ids = ensure_no_duplicate_ids(enrolled_course_ids, err_msg=ERR_COURSE_SELECTED_MULTIPLE_TIMES)

                if course_ids:
                    courses = self.repo.get_courses_by_ids(company_id=company_id, course_ids=course_ids,
                                                           only_enabled=True)
                    found = {c.id for c in courses}
                    missing = [cid for cid in course_ids if cid not in found]
                    if missing:
                        raise BizValidationError(ERR_COURSE_NOT_FOUND_IDS.format(ids=", ".join(map(str, missing))))

                    existing_course_ids = {int(x.course_id) for x in (pe.course_enrollments or [])}
                    to_add = [cid for cid in course_ids if int(cid) not in existing_course_ids]

                    for cid in to_add:
                        # friendly exists check (avoid IntegrityError)
                        if self.repo.course_enrollment_exists(
                                company_id=company_id,
                                branch_id=int(pe.branch_id),
                                student_id=int(pe.student_id),
                                course_id=int(cid),
                                academic_year_id=int(pe.academic_year_id),
                                academic_term_id=pe.academic_term_id,
                        ):
                            raise BizValidationError(ERR_COURSE_ENROLLMENT_EXISTS)

                        ce_code = generate_next_code(prefix=CE_PREFIX, company_id=company_id, branch_id=None)
                        ce = CourseEnrollment(
                            company_id=company_id,
                            enrollment_code=ce_code,
                            student_id=int(pe.student_id),
                            course_id=int(cid),
                            program_enrollment_id=int(pe.id),
                            academic_year_id=int(pe.academic_year_id),
                            academic_term_id=pe.academic_term_id,
                            branch_id=int(pe.branch_id),
                            enrollment_status=EnrollmentStatusEnum.ENROLLED,
                            enrollment_date=pe.enrollment_date,
                            remarks=pe.remarks,
                        )
                        self.s.add(ce)

            self.s.flush()
            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(pe.branch_id))

            return True, "Program enrollment submitted", {
                "program_enrollment_id": int(pe.id),
                "enrollment_code": pe.enrollment_code,
                "enrollment_status": pe.enrollment_status.value,
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_ce_company_branch_student_course_year_term" in msg:
                return False, ERR_COURSE_ENROLLMENT_EXISTS, None
            return False, "Integrity error while submitting program enrollment.", None
        except Exception as e:
            log.exception("submit_program_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while submitting program enrollment.", None

    def submit_course_enrollment(
            self,
            *,
            course_enrollment_id: int,
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Submit CourseEnrollment:
          - Draft -> Enrolled
        """
        try:
            company_id = int(context.company_id)

            ce = self.repo.get_course_enrollment(company_id=company_id, enrollment_id=int(course_enrollment_id))
            if not ce:
                return False, ERR_COURSE_ENROLLMENT_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=ce.company_id, target_branch_id=ce.branch_id)

            if ce.enrollment_status != EnrollmentStatusEnum.DRAFT:
                raise BizValidationError(ERR_ONLY_DRAFT_CAN_BE_SUBMITTED)

            ce.enrollment_status = EnrollmentStatusEnum.ENROLLED

            self.s.flush()
            self._commit_or_flush()
            self._bump_enrollment_caches(company_id=company_id, branch_id=int(ce.branch_id))

            return True, "Course enrollment submitted", {
                "course_enrollment_id": int(ce.id),
                "enrollment_code": ce.enrollment_code,
                "enrollment_status": ce.enrollment_status.value,
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("submit_course_enrollment failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while submitting course enrollment.", None
