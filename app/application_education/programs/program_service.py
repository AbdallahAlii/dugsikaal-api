from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, Any, List, Set

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import db
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_education.core.base_service import BaseEducationService
from app.application_education.programs.models.program_models import Program, Course, ProgramCourse
from app.application_education.programs.program_repo import ProgramRepo, CourseRepo, ProgramCourseRepo
from app.application_education.programs.schemas import (
    ProgramCreate, ProgramUpdate,
    CourseCreate, CourseUpdate,
    BulkIds,
)
from app.application_education.programs.validation import (
    ERR_PROGRAM_NOT_FOUND,
    ERR_COURSE_NOT_FOUND,
    ERR_PROGRAM_NAME_EXISTS,
    ERR_COURSE_NAME_EXISTS,
    ERR_COURSE_IN_USE,
    ERR_PROGRAM_IN_USE,
    ERR_DUPLICATE_COURSE_IN_LIST,
    validate_credit_hours,
)

log = logging.getLogger(__name__)


class ProgramService:
    """
    ERPNext style:
      - Program is a Doc
      - ProgramCourse is a child table
      - create/update can include child table
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

        self.programs = ProgramRepo(self.s)
        self.courses = CourseRepo(self.s)
        self.links = ProgramCourseRepo(self.s)

        self.program_doc = BaseEducationService(Program, self.s)
        self.course_doc = BaseEducationService(Course, self.s)

    def _company_id(self, ctx: AffiliationContext) -> int:
        co = getattr(ctx, "company_id", None)
        if not co:
            raise BizValidationError("Company is required.")
        return int(co)

    def _ensure_courses_exist(self, *, company_id: int, course_ids: List[int]) -> None:
        existing = self.courses.existing_course_ids_in_company(company_id=company_id, course_ids=course_ids)
        missing = [cid for cid in course_ids if int(cid) not in existing]
        if missing:
            raise BizValidationError(ERR_COURSE_NOT_FOUND)

    def _normalize_course_items(self, items) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen: Set[int] = set()

        for it in items or []:
            cid = int(it.course_id)
            if cid in seen:
                raise BizValidationError(ERR_DUPLICATE_COURSE_IN_LIST)
            seen.add(cid)

            out.append({
                "course_id": cid,
                "is_mandatory": bool(it.is_mandatory),
            })
        return out

    # =========================
    # Program
    # =========================
    def create_program(
        self,
        *,
        payload: ProgramCreate,
        context: AffiliationContext
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = self._company_id(context)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            name = (payload.name or "").strip()
            if not name:
                raise BizValidationError("Program name is required.")

            if self.programs.name_exists(company_id, name):
                raise BizValidationError(ERR_PROGRAM_NAME_EXISTS)

            items = self._normalize_course_items(payload.courses)
            if items:
                self._ensure_courses_exist(company_id=company_id, course_ids=[x["course_id"] for x in items])

            prog = Program(
                company_id=company_id,
                name=name,
                program_type=payload.program_type,
                is_enabled=bool(payload.is_enabled),
            )
            self.s.add(prog)
            self.s.flush([prog])

            for it in items:
                self.s.add(ProgramCourse(
                    company_id=company_id,
                    program_id=int(prog.id),
                    course_id=it["course_id"],
                    curriculum_version=1,      # fixed default
                    is_mandatory=it["is_mandatory"],
                    sequence_no=None,
                    effective_start=None,
                    effective_end=None,
                ))
            self.s.flush()

            # ✅ IMPORTANT: commit like BaseEducationService (avoids begin() issue)
            self.program_doc._commit_or_flush()

            return True, "Program created", {"id": int(prog.id), "name": prog.name}

        except BizValidationError as e:
            self.program_doc._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self.program_doc._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_program_name_per_company" in msg:
                return False, ERR_PROGRAM_NAME_EXISTS, None
            return False, "Database error.", None
        except Exception as e:
            self.program_doc._rollback_if_top_level()
            log.exception("create_program failed: %s", e)
            return False, "Unexpected error.", None

    def update_program(
        self,
        *,
        program_id: int,
        payload: ProgramUpdate,
        context: AffiliationContext
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            row = self.programs.get(int(program_id))
            if not row:
                return False, ERR_PROGRAM_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=int(row.company_id), target_branch_id=None)

            data = payload.model_dump(exclude_unset=True)

            # name uniqueness
            if "name" in data and data["name"] is not None:
                new_name = data["name"].strip()
                if not new_name:
                    raise BizValidationError("Program name is required.")
                if new_name != row.name and self.programs.name_exists(int(row.company_id), new_name, exclude_id=int(row.id)):
                    raise BizValidationError(ERR_PROGRAM_NAME_EXISTS)
                row.name = new_name

            if "program_type" in data and data["program_type"] is not None:
                row.program_type = data["program_type"]

            if "is_enabled" in data and data["is_enabled"] is not None:
                row.is_enabled = bool(data["is_enabled"])

            # If courses provided -> replace all child rows (ERPNext style)
            if payload.courses is not None:
                items = self._normalize_course_items(payload.courses)
                if items:
                    self._ensure_courses_exist(company_id=int(row.company_id), course_ids=[x["course_id"] for x in items])

                self.s.flush([row])

                self.links.delete_for_program(int(row.id))

                for it in items:
                    self.s.add(ProgramCourse(
                        company_id=int(row.company_id),
                        program_id=int(row.id),
                        course_id=it["course_id"],
                        curriculum_version=1,
                        is_mandatory=it["is_mandatory"],
                        sequence_no=None,
                        effective_start=None,
                        effective_end=None,
                    ))
                self.s.flush()
            else:
                self.s.flush([row])

            # ✅ commit like BaseEducationService
            self.program_doc._commit_or_flush()

            return True, "Program updated", {"id": int(row.id), "name": row.name}

        except BizValidationError as e:
            self.program_doc._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self.program_doc._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_program_name_per_company" in msg:
                return False, ERR_PROGRAM_NAME_EXISTS, None
            return False, "Database error.", None
        except Exception as e:
            self.program_doc._rollback_if_top_level()
            log.exception("update_program failed: %s", e)
            return False, "Unexpected error.", None

    def delete_program(self, *, program_id: int, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ok, msg, out = self.bulk_delete_programs(payload=BulkIds(ids=[int(program_id)]), context=context)
        if not ok or not out:
            return False, msg, None
        r = (out.get("results") or [{}])[0]
        if not r.get("ok"):
            return False, r.get("message") or "Failed", None
        return True, r.get("message") or "Program deleted", {"id": int(program_id)}

    def bulk_delete_programs(self, *, payload: BulkIds, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            ids = [int(x) for x in payload.ids if x]
            if not ids:
                return True, "OK", {"results": [], "deleted_any": False}

            rows = self.s.query(Program).filter(Program.id.in_(ids)).all()
            by_id = {int(r.id): r for r in rows}

            in_use = self.programs.programs_with_groups(ids) | self.programs.programs_with_enrollments(ids)

            results: List[Dict[str, Any]] = []
            deleted_any = False

            for pid in ids:
                r = by_id.get(pid)
                if not r:
                    results.append({"id": pid, "ok": False, "message": ERR_PROGRAM_NOT_FOUND})
                    continue

                try:
                    ensure_scope_by_ids(context=context, target_company_id=int(r.company_id), target_branch_id=None)
                except Exception:
                    results.append({"id": pid, "ok": False, "message": "Unauthorized"})
                    continue

                if pid in in_use:
                    results.append({"id": pid, "ok": False, "message": ERR_PROGRAM_IN_USE})
                    continue

                ok, _, _ = self.program_doc.delete_doc(r, soft=False)
                results.append({"id": pid, "ok": ok, "message": "Program deleted" if ok else "Failed"})
                deleted_any = deleted_any or ok

            return True, "OK", {"results": results, "deleted_any": deleted_any}

        except Exception as e:
            self.program_doc._rollback_if_top_level()
            log.exception("bulk_delete_programs failed: %s", e)
            return False, "Unexpected error.", None

    # =========================
    # Course (unchanged)
    # =========================
    def create_course(self, *, payload: CourseCreate, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id = self._company_id(context)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            name = (payload.name or "").strip()
            if not name:
                raise BizValidationError("Course name is required.")

            validate_credit_hours(payload.credit_hours)

            if self.courses.name_exists(company_id, name):
                raise BizValidationError(ERR_COURSE_NAME_EXISTS)

            data = payload.model_dump(exclude_unset=True)
            data["company_id"] = company_id
            data["name"] = name

            ok, _, out = self.course_doc.create_doc(data)
            if not ok or not out:
                return False, "Failed", None

            return True, "Course created", out

        except BizValidationError as e:
            self.course_doc._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self.course_doc._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_course_name_per_company" in msg:
                return False, ERR_COURSE_NAME_EXISTS, None
            return False, "Database error.", None
        except Exception as e:
            self.course_doc._rollback_if_top_level()
            log.exception("create_course failed: %s", e)
            return False, "Unexpected error.", None

    def update_course(self, *, course_id: int, payload: CourseUpdate, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            row = self.courses.get(int(course_id))
            if not row:
                return False, ERR_COURSE_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=int(row.company_id), target_branch_id=None)

            data = payload.model_dump(exclude_unset=True)

            if "credit_hours" in data:
                validate_credit_hours(data.get("credit_hours"))

            if "name" in data and data["name"] is not None:
                new_name = data["name"].strip()
                if not new_name:
                    raise BizValidationError("Course name is required.")
                if new_name != row.name and self.courses.name_exists(int(row.company_id), new_name, exclude_id=int(row.id)):
                    raise BizValidationError(ERR_COURSE_NAME_EXISTS)
                row.name = new_name
                data.pop("name", None)

            for k, v in data.items():
                setattr(row, k, v)

            self.s.flush([row])
            self.course_doc._commit_or_flush()

            return True, "Course updated", {"id": int(row.id), "name": row.name}

        except BizValidationError as e:
            self.course_doc._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            self.course_doc._rollback_if_top_level()
            log.exception("update_course failed: %s", e)
            return False, "Unexpected error.", None

    def delete_course(self, *, course_id: int, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ok, msg, out = self.bulk_delete_courses(payload=BulkIds(ids=[int(course_id)]), context=context)
        if not ok or not out:
            return False, msg, None
        r = (out.get("results") or [{}])[0]
        if not r.get("ok"):
            return False, r.get("message") or "Failed", None
        return True, r.get("message") or "Course deleted", {"id": int(course_id)}

    def bulk_delete_courses(self, *, payload: BulkIds, context: AffiliationContext) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            ids = [int(x) for x in payload.ids if x]
            if not ids:
                return True, "OK", {"results": [], "deleted_any": False}

            rows = self.s.query(Course).filter(Course.id.in_(ids)).all()
            by_id = {int(r.id): r for r in rows}

            in_use = self.courses.courses_with_program_links(ids)

            results: List[Dict[str, Any]] = []
            deleted_any = False

            for cid in ids:
                r = by_id.get(cid)
                if not r:
                    results.append({"id": cid, "ok": False, "message": ERR_COURSE_NOT_FOUND})
                    continue

                try:
                    ensure_scope_by_ids(context=context, target_company_id=int(r.company_id), target_branch_id=None)
                except Exception:
                    results.append({"id": cid, "ok": False, "message": "Unauthorized"})
                    continue

                if cid in in_use:
                    results.append({"id": cid, "ok": False, "message": ERR_COURSE_IN_USE})
                    continue

                ok, _, _ = self.course_doc.delete_doc(r, soft=False)
                results.append({"id": cid, "ok": ok, "message": "Course deleted" if ok else "Failed"})
                deleted_any = deleted_any or ok

            return True, "OK", {"results": results, "deleted_any": deleted_any}

        except Exception as e:
            self.course_doc._rollback_if_top_level()
            log.exception("bulk_delete_courses failed: %s", e)
            return False, "Unexpected error.", None
