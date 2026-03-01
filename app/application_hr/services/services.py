# app/application_hr/services/services.py
from __future__ import annotations

import logging
from datetime import datetime, time as dtime
from typing import Optional, Tuple, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException, BadRequest, Forbidden, NotFound

from app.application_rbac.service import RbacService
from app.business_validation.item_validation import BizValidationError
from config.database import db
from app.application_media.service import save_image_for
from app.application_media.utils import MediaFolder
from app.application_hr.repository.hr_repo import HrRepository
from app.application_hr.models.hr import (
    Employee,
    EmployeeCheckin,
    HolidayList,
    ShiftType,
    Attendance,
    ShiftAssignment,
    EmploymentTypeEnum,
)
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
)
from app.common.models.base import GenderEnum, StatusEnum
from app.common.security.password_generator import generate_random_password
from app.common.security.passwords import hash_password
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope
from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
    preview_next_username_for_company,
    bump_username_counter_for_company,
)
from app.common.cache.invalidation import bump_company_list, bump_dropdown_for_context, bump_detail
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
    ERR_EMP_ASSIGNMENT_COMPANY_MISMATCH,
    ERR_EMP_SHIFT_TYPE_INVALID,
    ERR_EMP_HOLIDAY_LIST_INVALID,
    ERR_EMP_GENDER_INVALID,
)
from app.application_org.models.company import Company

log = logging.getLogger(__name__)

# Employee document code series (per-company)
EMP_PREFIX = "HR-EMP"


class HrService:
    def __init__(self, repo: Optional[HrRepository] = None, session: Optional[Session] = None):
        self.repo = repo or HrRepository(session or db.session)
        self.s: Session = self.repo.s

    # --------------------------
    # Transaction helpers (nested-friendly)
    # --------------------------

    @property
    def _in_nested_tx(self) -> bool:
        """
        True if current Session is inside a nested SAVEPOINT transaction
        (e.g. session.begin_nested() from Data Import runner).

        Same pattern as StockReconciliationService.
        """
        try:
            in_nested = getattr(self.s, "in_nested_transaction", None)
            if callable(in_nested):
                return bool(in_nested())
        except Exception:
            pass

        tx = getattr(self.s, "transaction", None)
        if tx is None:
            return False

        if getattr(tx, "nested", False):
            return True

        parent = getattr(tx, "parent", None)
        while parent is not None:
            if getattr(parent, "nested", False):
                return True
            parent = parent.parent

        return False

    def _commit_or_flush(self) -> None:
        """
        - If inside nested tx (Data Import) → only flush(), outer context manages commit.
        - Else → normal commit() for HTTP API.
        """
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        """
        - If inside nested tx (Data Import row) → let outer runner rollback its savepoint.
        - Else → rollback() the Session.
        """
        if self._in_nested_tx:
            return
        self.s.rollback()

    # --------------------------
    # Private helpers
    # --------------------------

    def _resolve_gender(self, value) -> Optional[GenderEnum]:
        """
        Map incoming sex to GenderEnum.

        Accepts:
          - None
          - GenderEnum instance
          - "Male"/"Female" (any case)
          - "MALE"/"FEMALE"
        """
        if value is None:
            return None

        if isinstance(value, GenderEnum):
            return value

        if isinstance(value, str):
            raw = value.strip()

            # Match by enum value first ("Male", "Female")
            for member in GenderEnum:
                if raw.lower() == member.value.lower():
                    return member

            # Then try by enum name ("MALE", "FEMALE")
            try:
                return GenderEnum[raw.upper()]
            except KeyError:
                pass

        # ERP-style clean message
        raise BizValidationError(ERR_EMP_GENDER_INVALID)

    def _resolve_employment_type(self, value) -> Optional[EmploymentTypeEnum]:
        """
        Map incoming employment_type to EmploymentTypeEnum.

        Accepts:
        - Enum member (EmploymentTypeEnum.FULL_TIME)
        - Nice text like "Full-time"
        - Name text like "FULL_TIME"
        """
        if value is None:
            return None

        if isinstance(value, EmploymentTypeEnum):
            return value

        # Normalise to string
        s = str(value).strip()

        # Try match by value (Full-time) or name (FULL_TIME)
        for choice in EmploymentTypeEnum:
            if s.lower() == choice.value.lower() or s.upper() == choice.name:
                return choice

        # ERP style short error
        raise BizValidationError("Invalid Employment Type.")

    def _validate_employee_links(
        self,
        *,
        company_id: int,
        holiday_list_id: Optional[int],
        default_shift_type_id: Optional[int],
    ) -> None:
        """
        Ensure Holiday List and Shift Type (if provided) exist
        and belong to the same company.

        Raises BizValidationError with ERP-style messages instead of
        raw FK/DB errors.
        """
        # Holiday List check
        if holiday_list_id:
            hl = self.repo.get_holiday_list_by_id(holiday_list_id)
            if not hl or hl.company_id != company_id:
                # ERR_EMP_HOLIDAY_LIST_INVALID from hr_validation.py
                raise BizValidationError(ERR_EMP_HOLIDAY_LIST_INVALID)

        # Default Shift Type check
        if default_shift_type_id:
            st = self.repo.get_shift_type_by_id(default_shift_type_id)
            if not st or st.company_id != company_id:
                # ERR_EMP_SHIFT_TYPE_INVALID from hr_validation.py
                raise BizValidationError(ERR_EMP_SHIFT_TYPE_INVALID)

    def _set_roles_for_user(
        self,
        *,
        user_id: int,
        role_ids: Optional[List[int]],
        context: AffiliationContext,
    ) -> None:
        """
        Assign roles to a user via RBAC service.

        - If role_ids is None: do nothing.
        - If role_ids is empty list: do nothing (we don't clear roles from here).
        - Otherwise: call set_user_roles_for_user.
        """
        if role_ids is None:
            return

        ids = [int(r) for r in role_ids if r is not None]
        if not ids:
            return

        rbac = RbacService()
        rbac.set_user_roles_for_user(
            target_user_id=user_id,
            role_ids=ids,
            context=context,
        )

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
        Create an Employee + assignments + emergency contacts + user login + roles.
        Inspired by ERPNext, but adapted to our schema.

        NOTE: Now transaction-safe for Data Import (nested) and normal API calls.
        """
        # log payload (pydantic v1/v2 safe)
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
            # ---- Basic validations ----
            validate_employee_basic(
                dob=payload.dob,
                date_of_joining=payload.date_of_joining,
            )
            validate_employee_assignments([a.dict() for a in payload.assignments])

            # ---- Resolve primary branch & company (with scope) ----
            primary_assignment = next(a for a in payload.assignments if a.is_primary)

            company_id, primary_branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=primary_assignment.branch_id,
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )

            primary_branch = self.repo.get_branch_by_id(primary_branch_id)
            if not primary_branch:
                log.warning("Primary branch with ID %s not found.", primary_branch_id)
                raise BizValidationError(
                    f"Branch {primary_branch_id} does not exist."
                )

            # Fetch company row to read its `prefix` (for username series)
            company: Optional[Company] = db.session.get(Company, company_id)
            if not company:
                raise BizValidationError(f"Company {company_id} does not exist.")
            if not company.prefix:
                return (
                    False,
                    f"Company '{company.name}' is missing a user prefix.",
                    None,
                )

            log.info(
                "Resolved primary company_id=%s (company prefix='%s') via branch %s.",
                company_id,
                company.prefix,
                primary_branch.id,
            )

            # ---- Validate each assignment (branch + scope) ----
            for a in payload.assignments:
                branch = self.repo.get_branch_by_id(a.branch_id)
                if not branch:
                    log.warning("Branch with ID %s in assignments not found.", a.branch_id)
                    raise BizValidationError(
                        f"Branch {a.branch_id} does not exist."
                    )

                if branch.company_id != company_id:
                    raise BizValidationError(ERR_EMP_ASSIGNMENT_COMPANY_MISMATCH)

                ensure_scope_by_ids(
                    context=context,
                    target_company_id=branch.company_id,
                    target_branch_id=a.branch_id,
                )

            # ---- Validate linked Holiday List + Shift Type ---
            self._validate_employee_links(
                company_id=company_id,
                holiday_list_id=payload.holiday_list_id,
                default_shift_type_id=payload.default_shift_type_id,
            )

            # ---- Employee code ----
            if payload.code:
                manual = payload.code.strip()
                ensure_manual_code_is_next_and_bump(
                    prefix=EMP_PREFIX,
                    company_id=company_id,
                    branch_id=None,
                    code=manual,
                )
                if self.repo.employee_code_exists(company_id, manual):
                    return False, "Employee code already exists in this company.", None
                emp_code = manual
            else:
                emp_code = generate_next_code(
                    prefix=EMP_PREFIX,
                    company_id=company_id,
                    branch_id=None,
                )

            # ---- Gender + Employment Type mapping ----
            sex_enum = self._resolve_gender(payload.sex)
            emp_type_enum = self._resolve_employment_type(payload.employment_type)

            # ---- Build employee model ----
            emp = Employee(
                company_id=company_id,
                code=emp_code,
                full_name=payload.full_name,
                personal_email=payload.personal_email,
                phone_number=payload.phone_number,
                dob=payload.dob,
                date_of_joining=payload.date_of_joining,
                # store enum VALUE ("Male"/"Female")
                sex=sex_enum.value if sex_enum else None,
                status=StatusEnum.ACTIVE,
                # store enum VALUE ("Full-time"/"Part-time"/...)
                employment_type=emp_type_enum.value if emp_type_enum else None,
                holiday_list_id=payload.holiday_list_id,
                default_shift_type_id=payload.default_shift_type_id,
                attendance_device_id=payload.attendance_device_id,
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
                self.repo.create_emergency_contacts(
                    emp.id, [e.dict() for e in payload.emergency_contacts]
                )

            # ---- Provision login (System User) ----
            ut = self.repo.get_user_type_by_name("System User")
            if not ut:
                self._rollback_if_top_level()
                return False, "UserType 'System User' is not configured.", None

            temp_password = generate_random_password(length=8)
            pwd_hash = hash_password(temp_password)

            username = None
            user = None
            for _ in range(20):
                candidate = preview_next_username_for_company(company)
                try:
                    # nested tx for uniqueness retries
                    with self.s.begin_nested():
                        user = self.repo.create_user_and_affiliation(
                            username=candidate,
                            password_hash=pwd_hash,
                            company_id=company_id,
                            branch_id=primary_branch_id,
                            user_type=ut,
                            linked_entity_id=emp.id,
                            make_primary=True,
                        )
                        self.s.flush([user])
                    bump_username_counter_for_company(company, candidate)
                    username = candidate
                    break
                except IntegrityError:
                    # Savepoint rolled back; just bump and retry
                    log.warning(
                        "Username %s conflict while creating employee %s, retrying...",
                        candidate,
                        emp.id,
                    )
                    bump_username_counter_for_company(company, candidate)
                    continue

            if not username or not user:
                self._rollback_if_top_level()
                return False, "Could not allocate a unique username. Please retry.", None

            emp.user_id = user.id
            self.s.flush([emp])

            # ---- Assign roles (optional) ----
            try:
                self._set_roles_for_user(
                    user_id=user.id,
                    role_ids=payload.roles,
                    context=context,
                )
            except (BadRequest, Forbidden, NotFound) as e:
                log.warning(
                    "Role assignment failed for new employee %s (user %s): %s",
                    emp.id,
                    user.id,
                    e,
                )
                self._rollback_if_top_level()
                msg = getattr(e, "description", str(e))
                return False, f"Failed to assign roles: {msg}", None

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

            # ---- Commit or flush (nested-safe) ----
            self._commit_or_flush()
            log.info("Successfully created employee %s for company %s.", emp.id, company_id)

            # ---- Cache bumps (best effort) ----
            try:
                # Company-scoped list (your HR_LIST_CONFIGS sets cache_scope="COMPANY")
                bump_company_list("hr", "employees", context, company_id)

                # Dropdown also COMPANY-scoped (HR_DROPDOWN_CONFIGS employees cache_scope=COMPANY)
                bump_dropdown_for_context(
                    "hr",
                    "employees",
                    context,
                    params={"company_id": company_id},
                )

                # If you cache employee detail anywhere:
                bump_detail("hr:employees", emp.id)

            except Exception:
                log.exception("[cache] failed to bump HR employee caches after create")

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

        except BizValidationError as e:
            log.warning("BizValidationError during employee creation: %s", e)
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            # scope, forbidden, not found
            log.warning(
                "HTTPException during employee creation for user %s: %s - %s",
                getattr(context, "user_id", "?"),
                getattr(e, "code", "?"),
                getattr(e, "description", str(e)),
            )
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None
        except IntegrityError as e:
            log.error(
                "IntegrityError during employee creation for user %s: %s",
                getattr(context, "user_id", "?"),
                getattr(e, "orig", e),
            )
            self._rollback_if_top_level()
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
            self._rollback_if_top_level()
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
        Update basic Employee fields + assignments + emergency contacts + roles.
        Code, ID, username, etc. are immutable here.

        Transaction-safe for Data Import and HTTP.
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

            data = payload.dict(exclude_unset=True)

            # ---- Gender mapping → store enum.value ----
            if "sex" in data and data["sex"] is not None:
                sex_enum = self._resolve_gender(data["sex"])
                data["sex"] = sex_enum.value if sex_enum else None

            # ---- Employment Type mapping → store enum.value ----
            if "employment_type" in data and data["employment_type"] is not None:
                emp_type_enum = self._resolve_employment_type(data["employment_type"])
                data["employment_type"] = (
                    emp_type_enum.value if emp_type_enum else None
                )

            # ---- Basic HR date validations ----
            dob = data.get("dob", emp.dob)
            doj = data.get("date_of_joining", emp.date_of_joining)
            if dob or doj:
                validate_employee_basic(dob=dob, date_of_joining=doj)

            # ---- Linked Holiday List / Shift Type if changing ----
            holiday_list_id = data.get("holiday_list_id", emp.holiday_list_id)
            default_shift_type_id = data.get(
                "default_shift_type_id", emp.default_shift_type_id
            )
            self._validate_employee_links(
                company_id=emp.company_id,
                holiday_list_id=holiday_list_id,
                default_shift_type_id=default_shift_type_id,
            )

            # ---- Simple fields update ----
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
                "attendance_device_id",
            ]
            for field in update_fields:
                if field in data:
                    setattr(emp, field, data[field])

            # ---- Assignments (ERP-style replace all) ----
            if "assignments" in data and data["assignments"] is not None:
                assignments_models = payload.assignments or []
                assignments = [a.dict() for a in assignments_models]
                validate_employee_assignments(assignments)

                # validate branches + scope
                for a in assignments_models:
                    branch = self.repo.get_branch_by_id(a.branch_id)
                    if not branch:
                        raise BizValidationError(
                            f"Branch {a.branch_id} does not exist."
                        )
                    if branch.company_id != emp.company_id:
                        raise BizValidationError(ERR_EMP_ASSIGNMENT_COMPANY_MISMATCH)

                    ensure_scope_by_ids(
                        context=context,
                        target_company_id=branch.company_id,
                        target_branch_id=a.branch_id,
                    )

                self.repo.update_assignments(
                    employee_id=emp.id,
                    company_id=emp.company_id,
                    rows=assignments,
                )

            # ---- Emergency contacts (ERP-style replace all) ----
            if "emergency_contacts" in data and data["emergency_contacts"] is not None:
                contacts = (
                    [e.dict() for e in payload.emergency_contacts]
                    if payload.emergency_contacts
                    else []
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

            # ---- Roles: optional update ----
            # If payload.roles is None → do not touch roles.
            if payload.roles is not None and emp.user_id:
                try:
                    self._set_roles_for_user(
                        user_id=emp.user_id,
                        role_ids=payload.roles,
                        context=context,
                    )
                except (BadRequest, Forbidden, NotFound) as e:
                    log.warning(
                        "Role assignment failed during employee update %s (user %s): %s",
                        emp.id,
                        emp.user_id,
                        e,
                    )
                    self._rollback_if_top_level()
                    msg = getattr(e, "description", str(e))
                    return False, f"Failed to update roles: {msg}", None

            # ---- Commit / flush ----
            self._commit_or_flush()
            log.info("Successfully updated employee %s.", emp.id)

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("hr", "employees", context, emp.company_id)

                bump_dropdown_for_context(
                    "hr",
                    "employees",
                    context,
                    params={"company_id": emp.company_id},
                )

                bump_detail("hr:employees", emp.id)

            except Exception:
                log.exception("[cache] failed to bump HR employee caches after update")

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
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            log.warning(
                "HTTPException during employee update for user %s: %s - %s",
                getattr(context, "user_id", "?"),
                getattr(e, "code", "?"),
                getattr(e, "description", str(e)),
            )
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None
        except Exception as e:
            log.exception(
                "Error during employee update for employee %s: %s", employee_id, e
            )
            self._rollback_if_top_level()
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
            # Resolve company (context or explicit)
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Holiday List.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None,
            )

            validate_holiday_list_range(payload.from_date, payload.to_date)
            validate_holiday_rows_within_range(
                payload.from_date,
                payload.to_date,
                [h.dict() for h in payload.holidays],
            )

            hl = HolidayList(
                company_id=company_id,
                name=payload.name,
                from_date=payload.from_date,
                to_date=payload.to_date,
                is_default=payload.is_default or False,
            )

            self.repo.create_holiday_list(hl, [h.dict() for h in payload.holidays])
            self._commit_or_flush()
            return True, "Holiday List created", hl

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None

        except HTTPException as e:
            # Out-of-scope / forbidden etc.
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None

        except IntegrityError as e:
            log.error("IntegrityError during create_holiday_list: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()

            if "uq_holiday_list_company_name" in msg:
                # Your specific unique constraint
                return False, "Holiday List name already exists in this Company.", None

            return False, "Integrity error while creating Holiday List.", None

        except Exception as e:
            log.exception("create_holiday_list failed: %s", e)
            self._rollback_if_top_level()
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

            ensure_scope_by_ids(
                context=context,
                target_company_id=hl.company_id,
                target_branch_id=None,
            )

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

            self._commit_or_flush()
            return True, "Holiday List updated", hl

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None

        except HTTPException as e:
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None

        except IntegrityError as e:
            log.error("IntegrityError during update_holiday_list: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()

            if "uq_holiday_list_company_name" in msg:
                return False, "Holiday List name already exists in this Company.", None

            return False, "Integrity error while updating Holiday List.", None

        except Exception as e:
            log.exception("update_holiday_list failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Holiday List.", None

    # ------------------------------------------------------------------
    # Shift Type + Assignment
    # ------------------------------------------------------------------

    def _parse_time_hhmm(self, value) -> dtime:
        """
        Robust time parser for ShiftType.

        Accepts:
          - datetime.time instance → returned as-is
          - "HH:MM"
          - "HH:MM:SS"
          - "H:MM AM"/"H:MM PM"
          - "H:MM:SS AM"/"H:MM:SS PM"
        """
        if value is None:
            raise BizValidationError("Time is required.")

        if isinstance(value, dtime):
            return value

        if not isinstance(value, str):
            raise BizValidationError("Invalid time format. Use HH:MM or HH:MM:SS.")

        s = value.strip().upper()

        # 12-hour with AM/PM
        if s.endswith("AM") or s.endswith("PM"):
            if " " not in s:
                # "8:30PM" -> "8:30 PM"
                s = s[:-2] + " " + s[-2:]
            for fmt in ("%I:%M %p", "%I:%M:%S %p"):
                try:
                    return datetime.strptime(s, fmt).time()
                except ValueError:
                    continue
            raise BizValidationError("Invalid time format. Use HH:MM or HH:MM:SS.")

        # 24-hour forms
        parts = s.split(":")
        try:
            if len(parts) == 2:
                h, m = parts
                sec = 0
            elif len(parts) == 3:
                h, m, sec = parts
            else:
                raise BizValidationError("Invalid time format. Use HH:MM or HH:MM:SS.")
            return dtime(int(h), int(m), int(sec))
        except ValueError:
            raise BizValidationError("Invalid time format. Use HH:MM or HH:MM:SS.")

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

            # Validate Holiday List before hitting FK
            if payload.holiday_list_id is not None:
                hl = self.repo.get_holiday_list_by_id(payload.holiday_list_id)
                if not hl:
                    raise BizValidationError("Holiday List not found.")
                if hl.company_id != company_id:
                    raise BizValidationError("Invalid Holiday List for this Company.")

            st = ShiftType(
                company_id=company_id,
                name=payload.name,
                start_time=self._parse_time_hhmm(payload.start_time),
                end_time=self._parse_time_hhmm(payload.end_time),
                enable_auto_attendance=payload.enable_auto_attendance,
                process_attendance_after=payload.process_attendance_after,
                is_night_shift=payload.is_night_shift,
                holiday_list_id=payload.holiday_list_id,
            )
            self.repo.create_shift_type(st)
            self._commit_or_flush()
            return True, "Shift Type created", st

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            log.error("IntegrityError during shift type create: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_shift_type_company_name" in msg:
                return False, "Shift Type name already exists in this Company.", None
            if "holiday_list_id" in msg and "holiday_lists" in msg:
                return False, "Invalid Holiday List for this Company.", None
            return False, "Integrity error while creating Shift Type.", None
        except Exception as e:
            log.exception("create_shift_type failed: %s", e)
            self._rollback_if_top_level()
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

            # Time fields
            if "start_time" in data and data["start_time"]:
                data["start_time"] = self._parse_time_hhmm(data["start_time"])
            if "end_time" in data and data["end_time"]:
                data["end_time"] = self._parse_time_hhmm(data["end_time"])

            # Holiday List validation
            if "holiday_list_id" in data and data["holiday_list_id"] is not None:
                hl = self.repo.get_holiday_list_by_id(data["holiday_list_id"])
                if not hl:
                    raise BizValidationError("Holiday List not found.")
                if hl.company_id != st.company_id:
                    raise BizValidationError("Invalid Holiday List for this Company.")

            self.repo.update_shift_type_fields(st, data)
            self._commit_or_flush()
            return True, "Shift Type updated", st

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            log.error("IntegrityError during shift type update: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_shift_type_company_name" in msg:
                return False, "Shift Type name already exists in this Company.", None
            if "holiday_list_id" in msg and "holiday_lists" in msg:
                return False, "Invalid Holiday List for this Company.", None
            return False, "Integrity error while updating Shift Type.", None
        except Exception as e:
            log.exception("update_shift_type failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Shift Type.", None

    def create_shift_assignment(
        self,
        *,
        payload: ShiftAssignmentCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[ShiftAssignment]]:
        """
        Create Shift Assignment for an employee.
        """
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Shift Assignment.", None

            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            validate_shift_assignment_range(payload.from_date, payload.to_date)

            # Validate employee + shift type within same company
            emp = self.repo.get_employee_by_id(payload.employee_id)
            if not emp or emp.company_id != company_id:
                raise BizValidationError("Employee not found in this Company.")

            st = self.repo.get_shift_type_by_id(payload.shift_type_id)
            if not st or st.company_id != company_id:
                raise BizValidationError("Invalid Shift Type for this Company.")

            sa = ShiftAssignment(
                employee_id=payload.employee_id,
                company_id=company_id,
                shift_type_id=payload.shift_type_id,
                from_date=payload.from_date,
                to_date=payload.to_date,
                is_active=payload.is_active,
            )
            self.repo.create_shift_assignment(sa)
            self._commit_or_flush()
            return True, "Shift Assignment created", sa

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_shift_assignment failed: %s", e)
            self._rollback_if_top_level()
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
            self._commit_or_flush()
            return True, "Shift Assignment updated", sa

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_shift_assignment failed: %s", e)
            self._rollback_if_top_level()
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
            self._commit_or_flush()
            return True, "Attendance recorded", att

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_manual_attendance failed: %s", e)
            self._rollback_if_top_level()
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

            # Resolve employee by id OR by code
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
            self._commit_or_flush()
            return True, "Employee Checkin created", ec

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_employee_checkin failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected server error while creating Employee Checkin.", None
