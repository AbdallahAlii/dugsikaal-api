
# app/application_hr/services/services.py

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException, BadRequest

from app.business_validation.item_validation import BizValidationError
from config.database import db
from app.application_media.service import save_image_for
from app.application_media.utils import MediaFolder
from app.application_hr.repository.hr_repo import HrRepository
from app.application_hr.models.hr import Employee, EmployeeCheckin, HolidayList, ShiftType, Attendance, ShiftAssignment
from app.application_hr.schemas.schemas import (
    EmployeeCreate,
    EmployeeCreateResponse,
    CreatedUserOut,
    EmployeeMinimalOut,
    EmployeeUpdate,
    HolidayListCreate,
    HolidayListUpdate,
    ShiftTypeCreate,
    ShiftTypeUpdate,
    ShiftAssignmentCreate,
    ShiftAssignmentUpdate,
    AttendanceCreate,
    EmployeeCheckinCreate,

    CreatedUserOut, EmployeeMinimalOut, EmployeeUpdate,
)
from app.common.models.base import GenderEnum, StatusEnum
from app.common.security.password_generator import generate_random_password
from app.common.security.passwords import hash_password
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc
# Employee code helpers (per-company series)
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)

# Company-prefixed username helpers (per-company series using Company.prefix)
from app.common.generate_code.service import (
    preview_next_username_for_company,
    bump_username_counter_for_company,
)
from app.common.cache.cache_invalidator import (
    bump_list_cache_company,
    bump_list_cache_branch,
    bump_list_cache_with_context,  # optional, if you want param-aware bumps
    bump_detail,                   # optional (use on updates; not needed on create)
)
from app.business_validation.hr_validation import (
    validate_employee_basic,
    validate_employee_assignments,
    validate_holiday_list_range,
    validate_holiday_rows_within_range,
    validate_shift_assignment_range,
    validate_attendance_basic,
    validate_checkin_basic,
    ERR_ATTENDANCE_DUPLICATE,
    ERR_CHECKIN_EMP_NOT_FOUND,
ERR_CHECKIN_DUPLICATE,
)
from app.application_org.models.company import Company

log = logging.getLogger(__name__)

# Employee document code series (per-company)
EMP_PREFIX = "HR-EMP"


class HrService:
    def __init__(self, repo: Optional[HrRepository] = None, session: Optional[Session] = None):
        self.repo = repo or HrRepository(session or db.session)
        self.s = self.repo.s

    # def create_employee(
    #     self,
    #     *,
    #     payload: EmployeeCreate,
    #     context: AffiliationContext,
    #     file_storage=None,
    #     bytes_: Optional[bytes] = None,
    #     filename: Optional[str] = None,
    #     content_type: Optional[str] = None,
    # ) -> Tuple[bool, str, Optional[EmployeeCreateResponse]]:
    #
    #     # Log incoming payload safely (Pydantic v1/v2 compatible)
    #     try:
    #         payload_dump = payload.dict()
    #     except Exception:
    #         try:
    #             payload_dump = payload.model_dump()
    #         except Exception:
    #             payload_dump = repr(payload)
    #     log.info("User %s attempting employee creation. Payload: %s", getattr(context, "user_id", "?"), payload_dump)
    #
    #     try:
    #         # ---- Basic validation ----
    #         if not payload.assignments or not any(getattr(a, "is_primary", False) for a in payload.assignments):
    #             return False, "At least one primary assignment is required.", None
    #
    #         # ---- Resolve company via primary assignment's branch ----
    #         primary_assignment = next(a for a in payload.assignments if a.is_primary)
    #         primary_branch = self.repo.get_branch_by_id(primary_assignment.branch_id)
    #         if not primary_branch:
    #             log.warning("BadRequest: Primary branch with ID %s not found.", primary_assignment.branch_id)
    #             raise BadRequest(f"Primary branch with ID {primary_assignment.branch_id} does not exist.")
    #
    #         company_id = primary_branch.company_id
    #
    #         # Fetch company row to read its `prefix` (for username series)
    #         company: Optional[Company] = db.session.get(Company, company_id)
    #         if not company:
    #             raise BadRequest(f"Company with ID {company_id} does not exist.")
    #         if not company.prefix:
    #             return False, f"Company '{company.name}' does not have a user prefix configured.", None
    #
    #         log.info(
    #             "Resolved primary company_id=%s (company prefix='%s') via branch %s.",
    #             company_id, company.prefix, primary_branch.id
    #         )
    #
    #         # ---- Validate ownership and scope for EVERY assignment ----
    #         for a in payload.assignments:
    #             # FIX: don't use a.branch.* (it doesn't exist on the schema). Load the branch first.
    #             branch = self.repo.get_branch_by_id(a.branch_id)
    #             if not branch:
    #                 log.warning("BadRequest: Branch with ID %s in assignments not found.", a.branch_id)
    #                 raise BadRequest(f"Branch with ID {a.branch_id} in assignments does not exist.")
    #
    #             ensure_scope_by_ids(
    #                 context=context,
    #                 target_company_id=branch.company_id,
    #                 target_branch_id=a.branch_id,
    #             )
    #
    #         # ---- Employee code (strict if manual, else generated) ----
    #         if payload.code:
    #             manual = payload.code.strip()
    #             ensure_manual_code_is_next_and_bump(
    #                 prefix=EMP_PREFIX,
    #                 company_id=company_id,
    #                 branch_id=None,
    #                 code=manual,
    #             )
    #             # double-check uniqueness in company scope
    #             if self.repo.employee_code_exists(company_id, manual):
    #                 return False, "Employee code already exists in this company.", None
    #             emp_code = manual
    #         else:
    #             emp_code = generate_next_code(prefix=EMP_PREFIX, company_id=company_id, branch_id=None)
    #
    #         # ---- Build employee model ----
    #         sex_enum = None
    #         if payload.sex:
    #             sex_enum = GenderEnum[payload.sex] if isinstance(payload.sex, str) else payload.sex
    #
    #         emp = Employee(
    #             company_id=company_id,
    #             code=emp_code,
    #             full_name=payload.full_name,
    #             personal_email=payload.personal_email,
    #             phone_number=payload.phone_number,
    #             dob=payload.dob,
    #             date_of_joining=payload.date_of_joining,
    #             sex=sex_enum,
    #             status=StatusEnum.ACTIVE,
    #         )
    #         self.repo.create_employee(emp)  # flush -> emp.id
    #
    #         # ---- Assignments ----
    #         self.repo.create_assignments(
    #             employee_id=emp.id,
    #             company_id=company_id,
    #             rows=[a.dict() for a in payload.assignments],
    #         )
    #
    #         # ---- Emergency contacts (optional) ----
    #         if payload.emergency_contacts:
    #             self.repo.create_emergency_contacts(emp.id, [e.dict() for e in payload.emergency_contacts])
    #
    #         # ---- Provision login (USERNAME uses company.prefix with per-company counter) ----
    #         ut = self.repo.get_user_type_by_name("System User")
    #         if not ut:
    #             self.s.rollback()
    #             return False, "UserType 'System User' not configured.", None
    #
    #         temp_password = generate_random_password(length=8)
    #         pwd_hash = hash_password(temp_password)
    #
    #         # PREVIEW → TRY INSERT → BUMP → RETRY
    #         username = None
    #         user = None
    #         for _ in range(20):
    #             candidate = preview_next_username_for_company(company)
    #             try:
    #                 # Savepoint so we can retry without losing the outer transaction
    #                 with self.s.begin_nested():
    #                     user = self.repo.create_user_and_affiliation(
    #                         username=candidate,
    #                         password_hash=pwd_hash,
    #                         company_id=company_id,
    #                         branch_id=primary_assignment.branch_id,
    #                         user_type=ut,
    #                         linked_entity_id=emp.id,
    #                         make_primary=True,
    #                     )
    #                     self.s.flush([user])  # triggers uniqueness constraints
    #                 # success -> bump counter up to candidate (keeps series tight)
    #                 bump_username_counter_for_company(company, candidate)
    #                 username = candidate
    #                 break
    #             except IntegrityError:
    #                 # username already taken (e.g., HJI-0001 existed from old test)
    #                 self.s.rollback()  # rollback savepoint only
    #                 # bump past the conflicting candidate and try again
    #                 bump_username_counter_for_company(company, candidate)
    #                 continue
    #
    #         if not username or not user:
    #             self.s.rollback()
    #             return False, "Could not allocate a unique username. Please retry.", None
    #
    #         emp.user_id = user.id
    #         self.s.flush([emp])
    #
    #         # ---- Optional encrypted image ----
    #         new_key = save_image_for(
    #             folder=MediaFolder.EMPLOYEES,
    #             item_id=emp.id,
    #             file=file_storage,
    #             bytes_=bytes_,
    #             filename=filename,
    #             content_type=content_type,
    #             old_img_key=emp.img_key,
    #         )
    #         if new_key:
    #             self.repo.update_employee_img_key(emp, new_key)
    #
    #         # ---- Commit & response ----
    #         self.s.commit()
    #         log.info("Successfully created employee %s for company %s.", emp.id, company_id)
    #         # -------------- CACHE BUMPS (best-effort) --------------
    #         try:
    #             # Company-scoped employees list (your HR list uses cache_scope=COMPANY)
    #             bump_list_cache_company("hr", "employees", company_id)
    #
    #             # If you ever change the list scope to BRANCH or your UI keeps a branch-filtered list,
    #             # also bump the branch scope version to be extra safe:
    #             if primary_assignment and getattr(primary_assignment, "branch_id", None):
    #                 bump_list_cache_branch("hr", "employees", company_id, int(primary_assignment.branch_id))
    #
    #             # If your list read path computes scope based on params/context, you can mirror it:
    #             # bump_list_cache_with_context("hr", "employees", context, params={})
    #         except Exception:
    #             log.exception("[cache] failed to bump employees list cache after create")
    #
    #         resp = EmployeeCreateResponse(
    #             employee=EmployeeMinimalOut(  # <-- Change this line to use EmployeeMinimalOut
    #                 id=emp.id,
    #                 code=emp.code,
    #             )
    #         )
    #         return True, "Employee created", resp
    #
    #     except HTTPException as e:
    #         log.warning(
    #             "HTTPException during employee creation for user %s: %s - %s",
    #             getattr(context, "user_id", "?"),
    #             getattr(e, "code", "?"),
    #             getattr(e, "description", str(e)),
    #         )
    #         self.s.rollback()
    #         raise
    #     except KeyError as e:
    #         self.s.rollback()
    #         invalid_type = str(e).strip("'")
    #         return False, f"'{invalid_type}' is not a valid relationship type.", None
    #
    #     except IntegrityError as e:
    #         log.error(
    #             "IntegrityError during employee creation for user %s: %s",
    #             getattr(context, "user_id", "?"),
    #             getattr(e, "orig", e),
    #         )
    #         self.s.rollback()
    #         msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
    #         if "uq_employee_code_per_company" in msg:
    #             return False, "Employee code conflict in this company.", None
    #         if "uq_emp_branch_from" in msg:
    #             return False, "Duplicate assignment for the same branch/from_date.", None
    #         if "uq_emp_primary_assignment" in msg:
    #             return False, "Only one active primary assignment is allowed.", None
    #         if ("unique" in msg and "username" in msg) or "ix_users_username" in msg:
    #             return False, "Username already exists. Please retry.", None
    #         return False, "Integrity error while creating employee.", None
    #
    #     except Exception as e:
    #         log.exception("Unexpected error creating employee: %s", e)
    #         self.s.rollback()
    #         return False, "Unexpected server error while creating employee.", None
    #
    # def update_employee(
    #         self,
    #         *,
    #         employee_id: int,
    #         payload: EmployeeUpdate,
    #         context: AffiliationContext,
    #         file_storage=None,
    #         bytes_: Optional[bytes] = None,
    #         filename: Optional[str] = None,
    #         content_type: Optional[str] = None,
    # ) -> Tuple[bool, str, Optional[EmployeeCreateResponse]]:
    #     log.info(f"User {getattr(context, 'user_id', '?')} attempting employee update for employee {employee_id}")
    #
    #     try:
    #         # Fetch existing employee record
    #         emp = self.repo.get_employee_by_id(employee_id)
    #         if not emp:
    #             return False, "Employee not found.", None
    #
    #         # Validate ownership or permissions (this would need to be based on roles)
    #         # This can be expanded to check if the user has permission to edit this employee.
    #
    #         # ---- Update only the fields provided in the payload ----
    #         update_fields = ["full_name", "personal_email", "phone_number", "dob", "status", "img_key"]
    #
    #         # Loop through the provided payload and update the respective fields
    #         for field, value in payload.dict(exclude_unset=True).items():
    #             if field in update_fields:
    #                 setattr(emp, field, value)
    #
    #         # ---- Handle assignments ----
    #         if payload.assignments:
    #             self.repo.update_assignments(
    #                 employee_id=emp.id,
    #                 company_id=emp.company_id,
    #                 rows=[a.dict() for a in payload.assignments]
    #             )
    #
    #         # ---- Handle emergency contacts ----
    #         if payload.emergency_contacts:
    #             self.repo.update_emergency_contacts(emp.id, [e.dict() for e in payload.emergency_contacts])
    #
    #         # ---- Optional encrypted image ----
    #         if file_storage:
    #             new_key = save_image_for(
    #                 folder=MediaFolder.EMPLOYEES,
    #                 item_id=emp.id,
    #                 file=file_storage,
    #                 bytes_=bytes_,
    #                 filename=filename,
    #                 content_type=content_type,
    #                 old_img_key=emp.img_key,
    #             )
    #             if new_key:
    #                 self.repo.update_employee_img_key(emp, new_key)
    #
    #         # ---- Commit the changes ----
    #         self.s.commit()
    #         log.info(f"Successfully updated employee {emp.id}.")
    #
    #         # -------------- CACHE BUMPS (best-effort) --------------
    #         try:
    #             bump_list_cache_company("hr", "employees", emp.company_id)
    #             if emp.primary_assignment and getattr(emp.primary_assignment, "branch_id", None):
    #                 bump_list_cache_branch("hr", "employees", emp.company_id, int(emp.primary_assignment.branch_id))
    #         except Exception:
    #             log.exception("[cache] failed to bump employees list cache after update")
    #
    #         # ---- Response ----
    #         resp = EmployeeCreateResponse(
    #             employee=EmployeeMinimalOut(
    #                 id=emp.id,
    #                 code=emp.code,
    #             )
    #         )
    #
    #         return True, "Employee updated", resp
    #
    #     except Exception as e:
    #         log.exception(f"Error during employee update for employee {employee_id}: {e}")
    #         self.s.rollback()
    #         return False, "Unexpected error while updating employee.", None
    # ------------------------------------------------------------------
    # Employee creation / update
    # ------------------------------------------------------------------

    def create_employee(
        self,
        *,
        payload: EmployeeCreate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[EmployeeCreateResponse]]:
        """
        Create an Employee + assignments + emergency contacts + user login.
        Inspired by ERPNext, but adapted to our schema.
        """

        # Log incoming payload safely (Pydantic v1/v2 compatible)
        try:
            payload_dump = payload.dict()
        except Exception:
            try:
                payload_dump = payload.model_dump()
            except Exception:
                payload_dump = repr(payload)
        log.info(
            "User %s attempting employee creation. Payload: %s",
            getattr(context, "user_id", "?"),
            payload_dump,
        )

        try:
            # ---- Basic HR validations ----
            validate_employee_basic(
                dob=payload.dob,
                date_of_joining=payload.date_of_joining,
            )
            validate_employee_assignments([a.dict() for a in payload.assignments])

            # ---- Resolve company via primary assignment's branch ----
            primary_assignment = next(a for a in payload.assignments if a.is_primary)
            primary_branch = self.repo.get_branch_by_id(primary_assignment.branch_id)
            if not primary_branch:
                log.warning("BadRequest: Primary branch with ID %s not found.", primary_assignment.branch_id)
                raise BadRequest(f"Primary branch with ID {primary_assignment.branch_id} does not exist.")

            company_id = primary_branch.company_id

            # Fetch company row to read its `prefix` (for username series)
            company: Optional[Company] = db.session.get(Company, company_id)
            if not company:
                raise BadRequest(f"Company with ID {company_id} does not exist.")
            if not company.prefix:
                return False, f"Company '{company.name}' does not have a user prefix configured.", None

            log.info(
                "Resolved primary company_id=%s (company prefix='%s') via branch %s.",
                company_id,
                company.prefix,
                primary_branch.id,
            )

            # ---- Validate scope for EVERY assignment ----
            for a in payload.assignments:
                branch = self.repo.get_branch_by_id(a.branch_id)
                if not branch:
                    log.warning("BadRequest: Branch with ID %s in assignments not found.", a.branch_id)
                    raise BadRequest(f"Branch with ID {a.branch_id} in assignments does not exist.")

                ensure_scope_by_ids(
                    context=context,
                    target_company_id=branch.company_id,
                    target_branch_id=a.branch_id,
                )

            # ---- Employee code (strict if manual, else generated) ----
            if payload.code:
                manual = payload.code.strip()
                ensure_manual_code_is_next_and_bump(
                    prefix=EMP_PREFIX,
                    company_id=company_id,
                    branch_id=None,
                    code=manual,
                )
                # double-check uniqueness in company scope
                if self.repo.employee_code_exists(company_id, manual):
                    return False, "Employee code already exists in this company.", None
                emp_code = manual
            else:
                emp_code = generate_next_code(prefix=EMP_PREFIX, company_id=company_id, branch_id=None)

            # ---- Build employee model ----
            sex_enum = None
            if payload.sex:
                sex_enum = GenderEnum[payload.sex] if isinstance(payload.sex, str) else payload.sex

            emp = Employee(
                company_id=company_id,
                code=emp_code,
                full_name=payload.full_name,
                personal_email=payload.personal_email,
                phone_number=payload.phone_number,
                dob=payload.dob,
                date_of_joining=payload.date_of_joining,
                sex=sex_enum,
                status=StatusEnum.ACTIVE,
                employment_type=payload.employment_type,
                holiday_list_id=payload.holiday_list_id,
                default_shift_type_id=payload.default_shift_type_id,
            )
            self.repo.create_employee(emp)  # flush -> emp.id

            # ---- Assignments ----
            self.repo.create_assignments(
                employee_id=emp.id,
                company_id=company_id,
                rows=[a.dict() for a in payload.assignments],
            )

            # ---- Emergency contacts (optional) ----
            if payload.emergency_contacts:
                self.repo.create_emergency_contacts(emp.id, [e.dict() for e in payload.emergency_contacts])

            # ---- Provision login (USERNAME uses company.prefix with per-company counter) ----
            ut = self.repo.get_user_type_by_name("System User")
            if not ut:
                self.s.rollback()
                return False, "UserType 'System User' not configured.", None

            temp_password = generate_random_password(length=8)
            pwd_hash = hash_password(temp_password)

            # PREVIEW → TRY INSERT → BUMP → RETRY
            username = None
            user = None
            for _ in range(20):
                candidate = preview_next_username_for_company(company)
                try:
                    # Savepoint so we can retry without losing the outer transaction
                    with self.s.begin_nested():
                        user = self.repo.create_user_and_affiliation(
                            username=candidate,
                            password_hash=pwd_hash,
                            company_id=company_id,
                            branch_id=primary_assignment.branch_id,
                            user_type=ut,
                            linked_entity_id=emp.id,
                            make_primary=True,
                        )
                        self.s.flush([user])  # triggers uniqueness constraints
                    # success -> bump counter up to candidate (keeps series tight)
                    bump_username_counter_for_company(company, candidate)
                    username = candidate
                    break
                except IntegrityError:
                    # username already taken
                    self.s.rollback()  # rollback savepoint only
                    bump_username_counter_for_company(company, candidate)
                    continue

            if not username or not user:
                self.s.rollback()
                return False, "Could not allocate a unique username. Please retry.", None

            emp.user_id = user.id
            self.s.flush([emp])

            # ---- Optional encrypted image ----
            new_key = save_image_for(
                folder=MediaFolder.EMPLOYEES,
                item_id=emp.id,
                file=file_storage,
                bytes_=bytes_,
                filename=filename,
                content_type=content_type,
                old_img_key=emp.img_key,
            )
            if new_key:
                self.repo.update_employee_img_key(emp, new_key)

            # ---- Commit & response ----
            self.s.commit()
            log.info("Successfully created employee %s for company %s.", emp.id, company_id)

            # -------------- CACHE BUMPS (best-effort) --------------
            try:
                bump_list_cache_company("hr", "employees", company_id)
                if primary_assignment and getattr(primary_assignment, "branch_id", None):
                    bump_list_cache_branch(
                        "hr",
                        "employees",
                        company_id,
                        int(primary_assignment.branch_id),
                    )
            except Exception:
                log.exception("[cache] failed to bump employees list cache after create")

            resp = EmployeeCreateResponse(
                employee=EmployeeMinimalOut(
                    id=emp.id,
                    code=emp.code,
                ),
                user=CreatedUserOut(
                    id=user.id,
                    username=username,
                    temp_password=temp_password,
                ),
            )
            return True, "Employee created", resp

        except HTTPException as e:
            log.warning(
                "HTTPException during employee creation for user %s: %s - %s",
                getattr(context, "user_id", "?"),
                getattr(e, "code", "?"),
                getattr(e, "description", str(e)),
            )
            self.s.rollback()
            raise
        except KeyError as e:
            self.s.rollback()
            invalid_type = str(e).strip("'")
            return False, f"'{invalid_type}' is not a valid relationship type.", None

        except IntegrityError as e:
            log.error(
                "IntegrityError during employee creation for user %s: %s",
                getattr(context, "user_id", "?"),
                getattr(e, "orig", e),
            )
            self.s.rollback()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_employee_code_per_company" in msg:
                return False, "Employee code conflict in this company.", None
            if "uq_emp_branch_from" in msg:
                return False, "Duplicate assignment for the same branch/from_date.", None
            if "uq_emp_primary_assignment" in msg:
                return False, "Only one active primary assignment is allowed.", None
            if ("unique" in msg and "username" in msg) or "ix_users_username" in msg:
                return False, "Username already exists. Please retry.", None
            return False, "Integrity error while creating employee.", None

        except Exception as e:
            log.exception("Unexpected error creating employee: %s", e)
            self.s.rollback()
            return False, "Unexpected server error while creating employee.", None

    def update_employee(
        self,
        *,
        employee_id: int,
        payload: EmployeeUpdate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[EmployeeCreateResponse]]:
        """
        Update basic Employee fields + assignments + emergency contacts.
        Code, ID, username, etc. are immutable here.
        """

        log.info(
            "User %s attempting employee update for employee %s",
            getattr(context, "user_id", "?"),
            employee_id,
        )

        try:
            emp = self.repo.get_employee_by_id(employee_id)
            if not emp:
                return False, "Employee not found.", None

            # Scope check: user must be allowed in employee's company
            ensure_scope_by_ids(
                context=context,
                target_company_id=emp.company_id,
                target_branch_id=None,
            )

            # ---- Update only the fields provided in the payload ----
            data = payload.dict(exclude_unset=True)

            # Validate basic HR rules if date fields are changing
            dob = data.get("dob", emp.dob)
            doj = data.get("date_of_joining", emp.date_of_joining)
            if dob or doj:
                validate_employee_basic(dob=dob, date_of_joining=doj)

            # Simple list of fields allowed to update directly
            update_fields = [
                "full_name",
                "personal_email",
                "phone_number",
                "dob",
                "date_of_joining",
                "sex",
                "status",
                "employment_type",
                "holiday_list_id",
                "default_shift_type_id",
                "img_key",
            ]
            for field in update_fields:
                if field in data:
                    setattr(emp, field, data[field])

            # ---- Handle assignments ----
            if "assignments" in data and data["assignments"] is not None:
                assignments = [a.dict() for a in payload.assignments] if payload.assignments else []
                validate_employee_assignments(assignments)
                self.repo.update_assignments(
                    employee_id=emp.id,
                    company_id=emp.company_id,
                    rows=assignments,
                )

            # ---- Handle emergency contacts ----
            if "emergency_contacts" in data and data["emergency_contacts"] is not None:
                contacts = (
                    [e.dict() for e in payload.emergency_contacts] if payload.emergency_contacts else []
                )
                self.repo.update_emergency_contacts(emp.id, contacts)

            # ---- Optional encrypted image ----
            if file_storage:
                new_key = save_image_for(
                    folder=MediaFolder.EMPLOYEES,
                    item_id=emp.id,
                    file=file_storage,
                    bytes_=bytes_,
                    filename=filename,
                    content_type=content_type,
                    old_img_key=emp.img_key,
                )
                if new_key:
                    self.repo.update_employee_img_key(emp, new_key)

            # ---- Commit the changes ----
            self.s.commit()
            log.info("Successfully updated employee %s.", emp.id)

            # -------------- CACHE BUMPS (best-effort) --------------
            try:
                bump_list_cache_company("hr", "employees", emp.company_id)
                if emp.primary_assignment and getattr(emp.primary_assignment, "branch_id", None):
                    bump_list_cache_branch(
                        "hr",
                        "employees",
                        emp.company_id,
                        int(emp.primary_assignment.branch_id),
                    )
            except Exception:
                log.exception("[cache] failed to bump employees list cache after update")

            resp = EmployeeCreateResponse(
                employee=EmployeeMinimalOut(
                    id=emp.id,
                    code=emp.code,
                ),
                user=None,
            )

            return True, "Employee updated", resp

        except BizValidationError as e:
            log.warning("BizValidationError during employee update: %s", e)
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("Error during employee update for employee %s: %s", employee_id, e)
            self.s.rollback()
            return False, "Unexpected error while updating employee.", None


    # ------------------------------------------------------------------
    # Holiday List + Holidays
    # ------------------------------------------------------------------

    def create_holiday_list(
        self,
        *,
        payload: HolidayListCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[HolidayList]]:
        try:
            # Resolve company
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Holiday List.", None

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            validate_holiday_list_range(payload.from_date, payload.to_date)
            validate_holiday_rows_within_range(payload.from_date, payload.to_date, [h.dict() for h in payload.holidays])

            hl = HolidayList(
                company_id=company_id,
                name=payload.name,
                from_date=payload.from_date,
                to_date=payload.to_date,
                is_default=payload.is_default or False,
            )

            self.repo.create_holiday_list(hl, [h.dict() for h in payload.holidays])
            self.s.commit()
            return True, "Holiday List created", hl

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("create_holiday_list failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while creating Holiday List.", None

    def update_holiday_list(
        self,
        *,
        holiday_list_id: int,
        payload: HolidayListUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[HolidayList]]:
        try:
            hl = self.repo.get_holiday_list_by_id(holiday_list_id)
            if not hl:
                return False, "Holiday List not found.", None

            ensure_scope_by_ids(context=context, target_company_id=hl.company_id, target_branch_id=None)

            data = payload.dict(exclude_unset=True)
            from_date = data.get("from_date", hl.from_date)
            to_date = data.get("to_date", hl.to_date)
            validate_holiday_list_range(from_date, to_date)

            # update fields
            hl.name = data.get("name", hl.name)
            hl.from_date = from_date
            hl.to_date = to_date
            if "is_default" in data and data["is_default"] is not None:
                hl.is_default = data["is_default"]

            self.s.flush([hl])

            # replace holiday rows if provided
            if payload.holidays is not None:
                hlist = [h.dict() for h in payload.holidays]
                validate_holiday_rows_within_range(hl.from_date, hl.to_date, hlist)
                self.repo.replace_holiday_list_rows(hl, hlist)

            self.s.commit()
            return True, "Holiday List updated", hl

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_holiday_list failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while updating Holiday List.", None

    # ------------------------------------------------------------------
    # Shift Type + Assignment
    # ------------------------------------------------------------------

    def _parse_hhmm(self, s: str) -> datetime.time:
        h, m = s.split(":")
        from datetime import time as dtime
        return dtime(int(h), int(m), 0)

    def create_shift_type(
        self,
        *,
        payload: ShiftTypeCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[ShiftType]]:
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Shift Type.", None

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            st = ShiftType(
                company_id=company_id,
                name=payload.name,
                start_time=self._parse_hhmm(payload.start_time),
                end_time=self._parse_hhmm(payload.end_time),
                enable_auto_attendance=payload.enable_auto_attendance,
                process_attendance_after=payload.process_attendance_after,
                is_night_shift=payload.is_night_shift,
                holiday_list_id=payload.holiday_list_id,
            )
            self.repo.create_shift_type(st)
            self.s.commit()
            return True, "Shift Type created", st

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("create_shift_type failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while creating Shift Type.", None

    def update_shift_type(
        self,
        *,
        shift_type_id: int,
        payload: ShiftTypeUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[ShiftType]]:
        try:
            st = self.repo.get_shift_type_by_id(shift_type_id)
            if not st:
                return False, "Shift Type not found.", None

            ensure_scope_by_ids(context=context, target_company_id=st.company_id, target_branch_id=None)

            data = payload.dict(exclude_unset=True)
            if "start_time" in data and data["start_time"]:
                data["start_time"] = self._parse_hhmm(data["start_time"])
            if "end_time" in data and data["end_time"]:
                data["end_time"] = self._parse_hhmm(data["end_time"])

            self.repo.update_shift_type_fields(st, data)
            self.s.commit()
            return True, "Shift Type updated", st

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_shift_type failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while updating Shift Type.", None

    def create_shift_assignment(
        self,
        *,
        payload: ShiftAssignmentCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[ShiftAssignment]]:
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Shift Assignment.", None

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            validate_shift_assignment_range(payload.from_date, payload.to_date)

            sa = ShiftAssignment(
                employee_id=payload.employee_id,
                company_id=company_id,
                shift_type_id=payload.shift_type_id,
                from_date=payload.from_date,
                to_date=payload.to_date,
                is_active=payload.is_active,
            )
            self.repo.create_shift_assignment(sa)
            self.s.commit()
            return True, "Shift Assignment created", sa

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("create_shift_assignment failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while creating Shift Assignment.", None

    def update_shift_assignment(
        self,
        *,
        shift_assignment_id: int,
        payload: ShiftAssignmentUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[ShiftAssignment]]:
        try:
            sa = self.repo.get_shift_assignment_by_id(shift_assignment_id)
            if not sa:
                return False, "Shift Assignment not found.", None

            ensure_scope_by_ids(context=context, target_company_id=sa.company_id, target_branch_id=None)

            data = payload.dict(exclude_unset=True)
            from_date = data.get("from_date", sa.from_date)
            to_date = data.get("to_date", sa.to_date)
            validate_shift_assignment_range(from_date, to_date)

            self.repo.update_shift_assignment_fields(sa, data)
            self.s.commit()
            return True, "Shift Assignment updated", sa

        except BizValidationError as e:
            self.s.rollback()
            return False, str(e), None
        except Exception as e:
            log.exception("update_shift_assignment failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while updating Shift Assignment.", None
        # ------------------------------------------------------------------
        # Attendance (manual)  → used when company doesn't use devices
        # ------------------------------------------------------------------

    def create_manual_attendance(
            self,
            *,
            payload: AttendanceCreate,
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Attendance]]:
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

            # prevent duplicates
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
            log.exception("create_manual_attendance failed: %s", e)
            self.s.rollback()
            return False, "Unexpected error while creating Attendance.", None

        # ------------------------------------------------------------------
        # Employee Checkin (device / mobile / manual)
        # ------------------------------------------------------------------

    def create_employee_checkin(
            self,
            *,
            payload: EmployeeCheckinCreate,
            context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[EmployeeCheckin]]:
        """
        Inspired by ERPNext's add_log_based_on_employee_field + biometric sync tool.

        - Allows identifying employee by ID or by code.
        - Uses company's timezone to normalize log_time → UTC.
        - Checks for duplicate checkins (same employee, same timestamp).
        """
        try:
            # Resolve company
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Employee Checkin.", None

            validate_checkin_basic(
                log_time=payload.log_time,
                log_type=payload.log_type.value if payload.log_type else None,
                source=payload.source.value if payload.source else None,
            )

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            # Resolve employee by id OR by code (like ERPNext employee_field_value)
            employee = None
            if payload.employee_id:
                employee = self.repo.get_employee_by_id(payload.employee_id)
                if not employee or employee.company_id != company_id:
                    employee = None
            if not employee and payload.employee_code:
                employee = self.repo.find_employee_by_code(company_id=company_id, code=payload.employee_code)

            if not employee:
                raise BizValidationError(ERR_CHECKIN_EMP_NOT_FOUND)

            # Timezone normalization: log_time is assumed to be in company local time
            tz = get_company_timezone(self.s, company_id)
            aware_local = ensure_aware(payload.log_time, tz)
            log_time_utc = to_utc(aware_local)

            # Duplicate checkin (same timestamp for same employee)
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
            log.exception("create_employee_checkin failed: %s", e)
            self.s.rollback()
            return False, "Unexpected server error while creating Employee Checkin.", None