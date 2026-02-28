# app/application_education/groups/group_service.py
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional, Tuple, List, Set

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.business_validation.item_validation import BizValidationError

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope

from app.application_education.groups.group_repo import GroupRepo
from app.application_education.groups.student_group_model import Batch, StudentCategory, StudentGroup, StudentGroupMembership, GroupBasedOnEnum
from app.application_education.groups.validation import (
    ERR_BATCH_NAME_REQUIRED,
    ERR_CATEGORY_NAME_REQUIRED,
    ERR_BATCH_EXISTS,
    ERR_CATEGORY_EXISTS,
    ERR_GROUP_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_STUDENT_CATEGORY_NOT_FOUND,
    ERR_DELETE_FORBIDDEN,
    validate_student_group_basics,
    validate_group_based_on,
    validate_uniqueness,
    validate_can_delete_group,
    validate_group_capacity,
    ERR_INVALID_GROUP_TYPE,
)

log = logging.getLogger(__name__)


class GroupService:
    def __init__(self, repo: Optional[GroupRepo] = None, session: Optional[Session] = None):
        self.repo = repo or GroupRepo(session or db.session)
        self.s: Session = self.repo.s

    # ----------------------------
    # Scope helpers (same style as StudentService)
    # ----------------------------
    def _resolve_company_from_branch(self, *, context: AffiliationContext, branch_id: Optional[int]) -> Tuple[int, Optional[int]]:
        if branch_id is None:
            # company-only scope: use active company from context (if your resolve helper supports it)
            company_id, resolved_branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=None,
                branch_id=None,
                get_branch_company_id=None,
                require_branch=False,
            )
            return int(company_id), None

        company_id, resolved_branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=None,
            branch_id=int(branch_id),
            get_branch_company_id=self.repo.s.scalar,  # not used; kept for signature compatibility in your project
            require_branch=True,
        )
        return int(company_id), int(resolved_branch_id)

    # ----------------------------
    # Batch
    # ----------------------------
    def create_batch(self, *, payload: Dict[str, Any], context: AffiliationContext):
        try:
            name = (payload.get("batch_name") or "").strip()
            if not name:
                raise BizValidationError(ERR_BATCH_NAME_REQUIRED)

            branch_id = payload.get("branch_id")
            # resolve company by branch if provided; otherwise use context company
            company_id, resolved_branch = self._resolve_company_from_branch(context=context, branch_id=branch_id)

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=resolved_branch)

            if self.repo.batch_name_exists(company_id=company_id, branch_id=resolved_branch, batch_name=name):
                raise BizValidationError(ERR_BATCH_EXISTS)

            b = Batch(company_id=company_id, branch_id=resolved_branch, batch_name=name, is_enabled=True)
            self.s.add(b)
            self.s.flush([b])
            self.s.commit()

            return True, "Batch created successfully", {"id": b.id, "batch_name": b.batch_name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except IntegrityError:
            self.s.rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            log.exception("create_batch failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def update_batch(self, *, batch_id: int, payload: Dict[str, Any], context: AffiliationContext):
        try:
            b: Optional[Batch] = self.repo.batches.get(int(batch_id))
            if not b:
                return False, ERR_BATCH_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=b.company_id, target_branch_id=b.branch_id)

            if "batch_name" in payload and payload["batch_name"] is not None:
                name = payload["batch_name"].strip()
                if not name:
                    raise BizValidationError(ERR_BATCH_NAME_REQUIRED)
                if self.repo.batch_name_exists(company_id=b.company_id, branch_id=b.branch_id, batch_name=name, exclude_id=b.id):
                    raise BizValidationError(ERR_BATCH_EXISTS)
                b.batch_name = name

            if "is_enabled" in payload:
                b.is_enabled = bool(payload["is_enabled"])

            self.s.flush([b])
            self.s.commit()
            return True, "Batch updated successfully", {"id": b.id, "batch_name": b.batch_name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_batch failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def delete_batches_bulk(self, *, ids: List[int], context: AffiliationContext):
        # soft delete recommended
        deleted: List[int] = []
        failed: List[Dict[str, Any]] = []
        try:
            rows = [self.repo.batches.get(int(i)) for i in ids]
            for r in rows:
                if r is not None:
                    ensure_scope_by_ids(context=context, target_company_id=r.company_id, target_branch_id=r.branch_id)

            for req_id, r in zip(ids, rows):
                rid = int(req_id)
                if r is None:
                    failed.append({"id": rid, "error": ERR_BATCH_NOT_FOUND})
                    continue
                r.is_enabled = False
                self.s.flush([r])
                deleted.append(rid)

            self.s.commit()
            return True, "Delete completed", {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }
        except Exception as e:
            log.exception("delete_batches_bulk failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    # ----------------------------
    # StudentCategory
    # ----------------------------
    def create_category(self, *, payload: Dict[str, Any], context: AffiliationContext):
        try:
            name = (payload.get("name") or "").strip()
            if not name:
                raise BizValidationError(ERR_CATEGORY_NAME_REQUIRED)

            # categories are company-scoped (no branch field in your model)
            company_id, _ = self._resolve_company_from_branch(context=context, branch_id=None)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            if self.repo.category_name_exists(company_id=company_id, name=name):
                raise BizValidationError(ERR_CATEGORY_EXISTS)

            c = StudentCategory(
                company_id=company_id,
                name=name,
                description=payload.get("description"),
                is_default=bool(payload.get("is_default", False)),
            )
            self.s.add(c)
            self.s.flush([c])
            self.s.commit()
            return True, "Student category created successfully", {"id": c.id, "name": c.name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except IntegrityError:
            self.s.rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            log.exception("create_category failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def update_category(self, *, category_id: int, payload: Dict[str, Any], context: AffiliationContext):
        try:
            c: Optional[StudentCategory] = self.repo.categories.get(int(category_id))
            if not c:
                return False, ERR_STUDENT_CATEGORY_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=c.company_id, target_branch_id=None)

            if "name" in payload and payload["name"] is not None:
                name = payload["name"].strip()
                if not name:
                    raise BizValidationError(ERR_CATEGORY_NAME_REQUIRED)
                if self.repo.category_name_exists(company_id=c.company_id, name=name, exclude_id=c.id):
                    raise BizValidationError(ERR_CATEGORY_EXISTS)
                c.name = name

            for f in ("description", "is_default", "is_enabled"):
                if f in payload:
                    setattr(c, f, payload[f])

            self.s.flush([c])
            self.s.commit()
            return True, "Student category updated successfully", {"id": c.id, "name": c.name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_category failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def delete_categories_bulk(self, *, ids: List[int], context: AffiliationContext):
        deleted: List[int] = []
        failed: List[Dict[str, Any]] = []
        try:
            rows = [self.repo.categories.get(int(i)) for i in ids]
            for r in rows:
                if r is not None:
                    ensure_scope_by_ids(context=context, target_company_id=r.company_id, target_branch_id=None)

            for req_id, r in zip(ids, rows):
                rid = int(req_id)
                if r is None:
                    failed.append({"id": rid, "error": ERR_STUDENT_CATEGORY_NOT_FOUND})
                    continue
                # soft disable if you add is_enabled on category; otherwise hard delete
                if hasattr(r, "is_enabled"):
                    r.is_enabled = False
                    self.s.flush([r])
                else:
                    self.s.delete(r)
                    self.s.flush()
                deleted.append(rid)

            self.s.commit()
            return True, "Delete completed", {
                "deleted_ids": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }

        except Exception as e:
            log.exception("delete_categories_bulk failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    # ----------------------------
    # StudentGroup (Frappe-style)
    # ----------------------------
    def create_student_group(self, *, payload: Dict[str, Any], context: AffiliationContext):
        """
        Required fields:
          - program_id
          - academic_year_id
          - group_based_on
          - name
        NO members here.
        """
        try:
            program_id = payload.get("program_id")
            academic_year_id = payload.get("academic_year_id")
            group_based_on = validate_group_based_on(payload.get("group_based_on"))

            name = validate_student_group_basics(
                name=payload.get("name"),
                program_id=program_id,
                capacity=payload.get("capacity"),
            )

            if not academic_year_id:
                raise BizValidationError("Academic year is required.")
            if not group_based_on:
                # you required it
                raise BizValidationError(ERR_INVALID_GROUP_TYPE)

            # branch optional (your model allows NULL)
            branch_id = payload.get("branch_id")
            company_id, resolved_branch = self._resolve_company_from_branch(context=context, branch_id=branch_id)
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=resolved_branch)

            # duplicates (pre-check like your Student service)
            name_taken = self.repo.group_name_exists(
                company_id=company_id,
                program_id=int(program_id),
                academic_year_id=int(academic_year_id),
                name=name,
            )
            setup_taken = self.repo.group_setup_exists(
                company_id=company_id,
                program_id=int(program_id),
                academic_year_id=int(academic_year_id),
                section_id=payload.get("section_id"),
            )
            validate_uniqueness(name_taken=name_taken, setup_taken=setup_taken)

            g = StudentGroup(
                company_id=company_id,
                branch_id=resolved_branch,
                program_id=int(program_id),
                academic_year_id=int(academic_year_id),
                academic_term_id=payload.get("academic_term_id"),
                batch_id=payload.get("batch_id"),
                section_id=payload.get("section_id"),
                student_category_id=payload.get("student_category_id"),
                name=name,
                group_based_on=GroupBasedOnEnum(group_based_on),
                capacity=payload.get("capacity"),
                is_enabled=bool(payload.get("is_enabled", True)),
            )
            self.s.add(g)
            self.s.flush([g])
            self.s.commit()

            return True, "Student group created successfully", {"id": g.id, "name": g.name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except IntegrityError:
            self.s.rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            log.exception("create_student_group failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def update_student_group(self, *, group_id: int, payload: Dict[str, Any], context: AffiliationContext):
        """
        Master data only.
        """
        try:
            g: Optional[StudentGroup] = self.repo.groups.get(int(group_id))
            if not g:
                return False, ERR_GROUP_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=g.company_id, target_branch_id=g.branch_id)

            if "name" in payload and payload["name"] is not None:
                name = validate_student_group_basics(
                    name=payload.get("name"),
                    program_id=g.program_id,
                    capacity=payload.get("capacity", g.capacity),
                )
                # pre-check duplicates for name
                if self.repo.group_name_exists(company_id=g.company_id, program_id=g.program_id, academic_year_id=g.academic_year_id, name=name, exclude_id=g.id):
                    raise BizValidationError("A Student Group with this name already exists.")
                g.name = name

            if "capacity" in payload and payload["capacity"] is not None:
                # extra safety: if lowering capacity below current active count
                active_count = len(self.repo.get_active_member_ids(group_id=g.id))
                validate_group_capacity(current_count=active_count, capacity=payload["capacity"])
                g.capacity = payload["capacity"]

            for f in ("academic_term_id", "batch_id", "section_id", "student_category_id", "is_enabled"):
                if f in payload:
                    setattr(g, f, payload[f])

            self.s.flush([g])
            self.s.commit()
            return True, "Student group updated successfully", {"id": g.id, "name": g.name}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_student_group failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    def delete_student_group(self, *, group_id: int, context: AffiliationContext):
        """
        ERPNext-style: don't delete if membership history exists.
        """
        try:
            g: Optional[StudentGroup] = self.repo.groups.get(int(group_id))
            if not g:
                return False, ERR_GROUP_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=g.company_id, target_branch_id=g.branch_id)

            member_count = self.repo.count_membership_history(group_id=g.id)
            validate_can_delete_group(member_count=member_count)  # raises ERR_DELETE_FORBIDDEN

            self.s.delete(g)
            self.s.flush()
            self.s.commit()
            return True, "Student group deleted successfully", {"id": g.id}

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("delete_student_group failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    # ----------------------------
    # Button: Get Students (preview only)
    # ----------------------------
    def get_students_preview(self, *, group_id: int, payload: Dict[str, Any], context: AffiliationContext):
        try:
            g: Optional[StudentGroup] = self.repo.groups.get(int(group_id))
            if not g:
                return False, ERR_GROUP_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=g.company_id, target_branch_id=g.branch_id)

            if g.group_based_on and str(g.group_based_on.value).upper() == "ACTIVITY":
                return False, "Get Students is not available for ACTIVITY groups.", None

            # ERPNext uses filters from the form; you pass them in payload.
            # We also default program/year from the group if not provided.
            academic_year_id = int(payload.get("academic_year_id") or g.academic_year_id)
            academic_term_id = payload.get("academic_term_id") or g.academic_term_id
            program_id = payload.get("program_id") or g.program_id
            batch_id = payload.get("batch_id") or g.batch_id
            student_category_id = payload.get("student_category_id") or g.student_category_id

            students = self.repo.get_students_from_enrollments(
                company_id=g.company_id,
                branch_id=g.branch_id,  # ERPNext doesn't have this, but you do
                academic_year_id=academic_year_id,
                academic_term_id=academic_term_id,
                program_id=program_id,
                batch_id=batch_id,
                student_category_id=student_category_id,
            )

            return True, "Students fetched successfully", {"students": students}

        except Exception as e:
            log.exception("get_students_preview failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None

    # ----------------------------
    # Save roster (final list semantics)
    # ----------------------------
    def save_students_list(self, *, group_id: int, effective_on: date, students: List[int], context: AffiliationContext):
        """
        Final list semantics:
          - Add missing -> create membership(joined_on=effective_on)
          - Remove missing -> set left_on=effective_on
          - Do NOT delete history
        """
        try:
            g: Optional[StudentGroup] = self.repo.groups.get(int(group_id))
            if not g:
                return False, ERR_GROUP_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=g.company_id, target_branch_id=g.branch_id)

            desired: Set[int] = {int(x) for x in (students or []) if x}
            current: Set[int] = self.repo.get_active_member_ids(group_id=g.id)

            to_add = sorted(list(desired - current))
            to_remove = sorted(list(current - desired))

            # capacity check (based on resulting size)
            resulting_count = len(current) - len(to_remove) + len(to_add)
            validate_group_capacity(current_count=resulting_count - 1, capacity=g.capacity) if to_add else None
            # (simple: if adding pushes over cap, block)
            if g.capacity and g.capacity > 0 and resulting_count > int(g.capacity):
                raise BizValidationError("Group capacity reached. Cannot add more students.")

            # remove first (close memberships)
            removed_count = self.repo.set_left_on_bulk(
                company_id=g.company_id,
                group_id=g.id,
                student_ids=to_remove,
                left_on=effective_on,
            )

            # add new rows
            if to_add:
                rows = []
                for sid in to_add:
                    rows.append({
                        "company_id": g.company_id,
                        "group_id": g.id,
                        "student_id": int(sid),
                        "joined_on": effective_on,
                        "left_on": None,
                    })
                self.repo.memberships.create_many(rows)

            self.s.commit()

            active_count = len(self.repo.get_active_member_ids(group_id=g.id))
            return True, "Student list saved successfully", {
                "added_count": len(to_add),
                "removed_count": int(removed_count),
                "active_count": int(active_count),
            }

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except IntegrityError:
            self.s.rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            log.exception("save_students_list failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error.", None