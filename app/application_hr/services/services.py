
# app/application_hr/services/services.py

from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException, BadRequest

from config.database import db
from app.application_media.service import save_image_for
from app.application_media.utils import MediaFolder
from app.application_hr.repository.hr_repo import HrRepository
from app.application_hr.models.hr import Employee
from app.application_hr.schemas.schemas import (
    EmployeeCreate,
    EmployeeCreateResponse,

    CreatedUserOut, EmployeeMinimalOut,
)
from app.common.models.base import GenderEnum, StatusEnum
from app.common.security.password_generator import generate_random_password
from app.common.security.passwords import hash_password
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

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

from app.application_org.models.company import Company

log = logging.getLogger(__name__)

# Employee document code series (per-company)
EMP_PREFIX = "HR-EMP"


class HrService:
    def __init__(self, repo: Optional[HrRepository] = None, session: Optional[Session] = None):
        self.repo = repo or HrRepository(session or db.session)
        self.s = self.repo.s

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

        # Log incoming payload safely (Pydantic v1/v2 compatible)
        try:
            payload_dump = payload.dict()
        except Exception:
            try:
                payload_dump = payload.model_dump()
            except Exception:
                payload_dump = repr(payload)
        log.info("User %s attempting employee creation. Payload: %s", getattr(context, "user_id", "?"), payload_dump)

        try:
            # ---- Basic validation ----
            if not payload.assignments or not any(getattr(a, "is_primary", False) for a in payload.assignments):
                return False, "At least one primary assignment is required.", None

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
                company_id, company.prefix, primary_branch.id
            )

            # ---- Validate ownership and scope for EVERY assignment ----
            for a in payload.assignments:
                # FIX: don't use a.branch.* (it doesn't exist on the schema). Load the branch first.
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
                    # username already taken (e.g., HJI-0001 existed from old test)
                    self.s.rollback()  # rollback savepoint only
                    # bump past the conflicting candidate and try again
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

            resp = EmployeeCreateResponse(
                employee=EmployeeMinimalOut(  # <-- Change this line to use EmployeeMinimalOut
                    id=emp.id,
                    code=emp.code,
                )
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
