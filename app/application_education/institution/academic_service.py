from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.business_validation.item_validation import BizValidationError

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope

from app.application_education.institution.academic_repo import EducationRepository
from app.application_education.institution.academic_model import (
    EducationSettings,
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)
from app.application_education.institution.schemas import (
    EducationSettingsCreate,
    EducationSettingsUpdate,
    AcademicYearCreate,
    AcademicYearUpdate,
    AcademicTermCreate,
    AcademicTermUpdate,
)

from app.business_validation.edu_validation import (
    validate_year_dates,
    validate_term_dates,
    validate_term_within_year,
    ERR_SETTINGS_EXISTS,
    ERR_SETTINGS_NOT_FOUND,
    ERR_YEAR_NOT_FOUND,
    ERR_TERM_NOT_FOUND,
    ERR_YEAR_NAME_EXISTS,
    ERR_TERM_NAME_EXISTS,
    ERR_INVALID_HOLIDAY_LIST,
    ERR_INVALID_DEFAULT_YEAR,
    ERR_INVALID_DEFAULT_TERM,
)

from app.application_hr.repository.hr_repo import HrRepository

log = logging.getLogger(__name__)


class EducationService:
    def __init__(self, repo: Optional[EducationRepository] = None, session: Optional[Session] = None):
        self.repo = repo or EducationRepository(session or db.session)
        self.s: Session = self.repo.s
        self.hr_repo = HrRepository(session=self.s)

    # --------------------------
    # Tx helpers (HR-style)
    # --------------------------

    @property
    def _in_nested_tx(self) -> bool:
        try:
            fn = getattr(self.s, "in_nested_transaction", None)
            if callable(fn):
                return bool(fn())
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
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        if self._in_nested_tx:
            return
        self.s.rollback()

    # --------------------------
    # Internal validations
    # --------------------------

    def _validate_holiday_list(self, company_id: int, holiday_list_id: Optional[int]) -> None:
        if holiday_list_id is None:
            return
        hl = self.hr_repo.get_holiday_list_by_id(holiday_list_id)
        if not hl or hl.company_id != company_id:
            raise BizValidationError(ERR_INVALID_HOLIDAY_LIST)

    def _validate_default_year(self, company_id: int, year_id: Optional[int]) -> None:
        if year_id is None:
            return
        y = self.repo.get_year(year_id)
        if not y or y.company_id != company_id:
            raise BizValidationError(ERR_INVALID_DEFAULT_YEAR)

    def _validate_default_term(self, company_id: int, term_id: Optional[int]) -> None:
        if term_id is None:
            return
        t = self.repo.get_term(term_id)
        if not t or t.company_id != company_id:
            raise BizValidationError(ERR_INVALID_DEFAULT_TERM)

    def _update_defaults_if_open(self, *, company_id: int, year: Optional[AcademicYear] = None, term: Optional[AcademicTerm] = None) -> None:
        """
        ERPNext-like behavior:
        - If a year becomes OPEN => set as default_academic_year
        - If a term becomes OPEN => set as default_academic_term (+ ensure default year)
        """
        try:
            settings = self.repo.ensure_settings(company_id)
            changed = False

            if year and year.status == AcademicStatusEnum.OPEN:
                settings.default_academic_year_id = year.id
                changed = True

            if term and term.status == AcademicStatusEnum.OPEN:
                settings.default_academic_term_id = term.id
                if not settings.default_academic_year_id:
                    settings.default_academic_year_id = term.academic_year_id
                changed = True

            if changed:
                self.s.flush([settings])
        except Exception as e:
            # don't break main save
            log.warning("Defaults update failed: %s", e)

    def _handle_current_year(self, company_id: int, year: AcademicYear) -> None:
        # enforce one current year per company
        if year.is_current:
            self.repo.clear_other_current_years(company_id, year.id)

    # ============================================================
    # SETTINGS
    # ============================================================

    def create_settings(
        self,
        *,
        payload: EducationSettingsCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id, _ = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=None,
                get_branch_company_id=None,
                require_branch=False,
            )
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            existing = self.repo.get_settings(company_id)
            if existing:
                return False, ERR_SETTINGS_EXISTS, None

            self._validate_holiday_list(company_id, payload.default_holiday_list_id)
            self._validate_default_year(company_id, payload.default_academic_year_id)
            self._validate_default_term(company_id, payload.default_academic_term_id)

            row = EducationSettings(
                company_id=company_id,
                default_academic_year_id=payload.default_academic_year_id,
                default_academic_term_id=payload.default_academic_term_id,
                validate_batch_in_student_group=payload.validate_batch_in_student_group,
                attendance_based_on_course_schedule=payload.attendance_based_on_course_schedule,
                working_days=payload.working_days,
                weekly_off_days=payload.weekly_off_days,
                default_holiday_list_id=payload.default_holiday_list_id,
            )
            self.repo.create_settings(row)
            self._commit_or_flush()

            return True, "Settings created", {"id": row.id}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_SETTINGS_EXISTS, None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("create_settings failed: %s", e)
            return False, "Unexpected error.", None

    def update_settings(
        self,
        *,
        company_id: int,
        payload: EducationSettingsUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            row = self.repo.get_settings(company_id)
            if not row:
                return False, ERR_SETTINGS_NOT_FOUND, None

            data = payload.model_dump(exclude_unset=True)

            if "default_holiday_list_id" in data:
                self._validate_holiday_list(company_id, data["default_holiday_list_id"])

            if "default_academic_year_id" in data:
                self._validate_default_year(company_id, data["default_academic_year_id"])

            if "default_academic_term_id" in data:
                self._validate_default_term(company_id, data["default_academic_term_id"])

            self.repo.update_settings_fields(row, data)
            self._commit_or_flush()

            return True, "Settings updated", {"id": row.id}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("update_settings failed: %s", e)
            return False, "Unexpected error.", None


    # ============================================================
    # ACADEMIC YEAR
    # ============================================================

    def create_year(
        self,
        *,
        payload: AcademicYearCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id, _ = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=None,
                get_branch_company_id=None,
                require_branch=False,
            )
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            validate_year_dates(payload.start_date, payload.end_date)

            if self.repo.year_name_exists(company_id, payload.name):
                raise BizValidationError(ERR_YEAR_NAME_EXISTS)

            row = AcademicYear(
                company_id=company_id,
                name=payload.name.strip(),
                start_date=payload.start_date,
                end_date=payload.end_date,
                is_current=payload.is_current,
                status=payload.status,
            )
            self.repo.create_year(row)

            self._handle_current_year(company_id, row)
            self.repo.ensure_settings(company_id)
            self._update_defaults_if_open(company_id=company_id, year=row)

            self._commit_or_flush()
            return True, "Year created", {"id": row.id, "name": row.name}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_academic_year_per_company" in msg:
                return False, ERR_YEAR_NAME_EXISTS, None
            if "ix_current_year_per_company" in msg:
                return False, "Only one year can be current.", None
            return False, "Database error.", None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("create_year failed: %s", e)
            return False, "Unexpected error.", None

    def update_year(
        self,
        *,
        year_id: int,
        payload: AcademicYearUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            row = self.repo.get_year(year_id)
            if not row:
                return False, ERR_YEAR_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=row.company_id, target_branch_id=None)

            data = payload.model_dump(exclude_unset=True)

            start = data.get("start_date", row.start_date)
            end = data.get("end_date", row.end_date)
            validate_year_dates(start, end)

            if "name" in data and data["name"] and data["name"].strip() != row.name:
                if self.repo.year_name_exists(row.company_id, data["name"], exclude_id=row.id):
                    raise BizValidationError(ERR_YEAR_NAME_EXISTS)

            self.repo.update_year_fields(row, data)

            if data.get("is_current") is True:
                self._handle_current_year(row.company_id, row)

            if "status" in data:
                self._update_defaults_if_open(company_id=row.company_id, year=row)

            self._commit_or_flush()
            return True, "Year updated", {"id": row.id, "name": row.name}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_academic_year_per_company" in msg:
                return False, ERR_YEAR_NAME_EXISTS, None
            if "ix_current_year_per_company" in msg:
                return False, "Only one year can be current.", None
            return False, "Database error.", None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("update_year failed: %s", e)
            return False, "Unexpected error.", None


    # ============================================================
    # ACADEMIC TERM
    # ============================================================

    def create_term(
        self,
        *,
        payload: AcademicTermCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            company_id, _ = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=None,
                get_branch_company_id=None,
                require_branch=False,
            )
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

            year = self.repo.get_year(payload.academic_year_id)
            if not year or year.company_id != company_id:
                return False, ERR_YEAR_NOT_FOUND, None

            validate_term_dates(payload.start_date, payload.end_date)
            validate_term_within_year(
                term_start=payload.start_date,
                term_end=payload.end_date,
                year_start=year.start_date,
                year_end=year.end_date,
            )

            if self.repo.term_name_exists(company_id, payload.academic_year_id, payload.name):
                raise BizValidationError(ERR_TERM_NAME_EXISTS)

            row = AcademicTerm(
                company_id=company_id,
                academic_year_id=payload.academic_year_id,
                name=payload.name.strip(),
                start_date=payload.start_date,
                end_date=payload.end_date,
                status=payload.status,
            )
            self.repo.create_term(row)

            self.repo.ensure_settings(company_id)
            self._update_defaults_if_open(company_id=company_id, term=row)

            self._commit_or_flush()
            return True, "Term created", {"id": row.id, "name": row.name}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_term_name_per_year_per_company" in msg:
                return False, ERR_TERM_NAME_EXISTS, None
            return False, "Database error.", None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("create_term failed: %s", e)
            return False, "Unexpected error.", None

    def update_term(
        self,
        *,
        term_id: int,
        payload: AcademicTermUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            row = self.repo.get_term(term_id)
            if not row:
                return False, ERR_TERM_NOT_FOUND, None

            ensure_scope_by_ids(context=context, target_company_id=row.company_id, target_branch_id=None)

            year = self.repo.get_year(row.academic_year_id)
            if not year:
                return False, ERR_YEAR_NOT_FOUND, None

            data = payload.model_dump(exclude_unset=True)

            start = data.get("start_date", row.start_date)
            end = data.get("end_date", row.end_date)
            validate_term_dates(start, end)
            validate_term_within_year(term_start=start, term_end=end, year_start=year.start_date, year_end=year.end_date)

            if "name" in data and data["name"] and data["name"].strip() != row.name:
                if self.repo.term_name_exists(row.company_id, row.academic_year_id, data["name"], exclude_id=row.id):
                    raise BizValidationError(ERR_TERM_NAME_EXISTS)

            self.repo.update_term_fields(row, data)

            if "status" in data:
                self._update_defaults_if_open(company_id=row.company_id, term=row)

            self._commit_or_flush()
            return True, "Term updated", {"id": row.id, "name": row.name}

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = str(getattr(e, "orig", e)).lower()
            if "uq_term_name_per_year_per_company" in msg:
                return False, ERR_TERM_NAME_EXISTS, None
            return False, "Database error.", None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("update_term failed: %s", e)
            return False, "Unexpected error.", None



    # ============================================================
    # CONTEXT
    # ============================================================

    def get_academic_context(
        self,
        *,
        company_id: int,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[dict]]:
        try:
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)
            settings = self.repo.get_settings(company_id) or self.repo.ensure_settings(company_id)
            self._commit_or_flush()

            return True, "OK", {
                "settings": settings,
                "current_year": self.repo.get_current_year(company_id),
                "open_year": self.repo.get_open_year(company_id),
                "open_term": self.repo.get_open_term(company_id),
            }
        except Exception as e:
            log.exception("get_academic_context failed: %s", e)
            return False, "Unexpected error.", None
