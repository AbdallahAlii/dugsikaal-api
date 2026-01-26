# from __future__ import annotations
#
# import logging
# import datetime as dt
# from typing import Optional
# from sqlalchemy.exc import IntegrityError
# from werkzeug.exceptions import Forbidden, NotFound
#
# from app.application_accounting.chart_of_accounts.models import FiscalYear, FiscalYearStatusEnum
# from app.application_accounting.chart_of_accounts.Repository.fiscal_year_repo import FiscalYearRepository
# from app.application_accounting.chart_of_accounts.schemas.fiscal_year_schemas import (
#     FiscalYearCreate,
#     FiscalYearUpdate,
#     FiscalYearOut,
# )
# from app.application_accounting.chart_of_accounts.validators.fiscal_year_validators import FiscalYearValidator
# from app.business_validation.item_validation import BizValidationError
# from app.common.cache.cache_invalidator import bump_list_cache_company, bump_fiscal_years_list_company, \
#     bump_fiscal_year_detail
# from app.security.rbac_guards import ensure_scope_by_ids
# from app.security.rbac_effective import AffiliationContext
# from config.database import db
#
# log = logging.getLogger(__name__)
#
#
# class FiscalYearService:
#     def __init__(self, repo: Optional[FiscalYearRepository] = None, session=None):
#         self.repo = repo or FiscalYearRepository(session or db.session)
#         self.s = self.repo.s
#
#     def create_fiscal_year(self, payload: FiscalYearCreate, context: AffiliationContext) -> FiscalYearOut:
#         """Create Fiscal Year with comprehensive validation"""
#         log.info("Creating fiscal year: name='%s', company_id=%d", payload.name, context.company_id)
#
#         # Permission check
#         if not FISCAL_YEAR_MANAGER_ROLES.intersection(context.roles):
#             raise Forbidden("Not authorized to create a fiscal year.")
#
#         # Scope check - user can only create for their company
#         ensure_scope_by_ids(context=context, target_company_id=context.company_id)
#
#         # Duplicate name (per company)
#         if self.repo.get_fiscal_year_by_name(context.company_id, payload.name):
#             raise BizValidationError("Fiscal year with this name already exists.")
#
#         # Only one open year at a time
#         if self.repo.get_open_fiscal_year(context.company_id):
#             raise BizValidationError("Another fiscal year is already open.")
#
#         # Normalize dates to datetime at 00:00
#         start_dt = payload.start_date if isinstance(payload.start_date, dt.datetime) else dt.datetime.combine(payload.start_date, dt.time.min)
#         end_dt = payload.end_date if isinstance(payload.end_date, dt.datetime) else dt.datetime.combine(payload.end_date, dt.time.min)
#
#         # Validate range & length
#         FiscalYearValidator.validate_date_range(start_dt, end_dt)
#
#         # Overlap check
#         if self.repo.check_date_overlap(context.company_id, start_dt, end_dt):
#             raise BizValidationError("Fiscal year dates overlap with an existing fiscal year.")
#
#         try:
#             fy = FiscalYear(
#                 company_id=context.company_id,
#                 name=payload.name,
#                 start_date=start_dt,
#                 end_date=end_dt,
#                 status=FiscalYearStatusEnum.OPEN,
#                 is_short_year=payload.is_short_year,
#             )
#             self.repo.create_fiscal_year(fy)
#             self.s.commit()
#
#             # 🔄 Cache bumps: list (company) and detail
#             bump_fiscal_years_list_company(context.company_id)
#             bump_fiscal_year_detail(fy.id)
#             log.info("Fiscal year created successfully: id=%d", fy.id)
#             return FiscalYearOut.model_validate(fy)
#
#         except IntegrityError:
#             self.s.rollback()
#             # Unique constraint on (company_id, name)
#             raise BizValidationError("Fiscal year with this name already exists.")
#         except Exception as e:
#             self.s.rollback()
#             log.error("Error creating fiscal year: %s", str(e))
#             raise BizValidationError("Failed to create fiscal year.")
#
#     def update_fiscal_year(self, fiscal_year_id: int, payload: FiscalYearUpdate, context: AffiliationContext) -> FiscalYearOut:
#         """Update fiscal year (name and/or status)."""
#         fy = self.repo.get_fiscal_year_by_id(fiscal_year_id)
#         if not fy:
#             raise NotFound("Fiscal year not found.")
#
#         # Permission
#         if not FISCAL_YEAR_MANAGER_ROLES.intersection(context.roles):
#             raise Forbidden("Not authorized to update a fiscal year.")
#
#         # Scope
#         ensure_scope_by_ids(context=context, target_company_id=fy.company_id)
#
#         updates: dict = {}
#
#         # Name change
#         if payload.name is not None and payload.name.strip() and payload.name != fy.name:
#             if self.repo.get_fiscal_year_by_name(fy.company_id, payload.name):
#                 raise BizValidationError("Fiscal year with this name already exists.")
#             updates["name"] = payload.name.strip()
#
#         # Status change
#         if payload.status is not None and payload.status != fy.status:
#             # Validate allowed transition
#             FiscalYearValidator.validate_status_transition(fy.status.value, payload.status.value)
#
#             if payload.status == FiscalYearStatusEnum.OPEN:
#                 existing_open = self.repo.get_open_fiscal_year(fy.company_id)
#                 if existing_open and existing_open.id != fiscal_year_id:
#                     raise BizValidationError("Another fiscal year is already open.")
#             updates["status"] = payload.status
#
#         if not updates:
#             raise BizValidationError("No changes provided.")
#
#         try:
#             self.repo.update_fiscal_year(fy, updates)
#             self.s.commit()
#
#             # 🔄 Cache bumps: list (company) and detail
#             bump_fiscal_years_list_company(fy.company_id)
#             bump_fiscal_year_detail(fy.id)
#             log.info("Fiscal year updated successfully: id=%d", fiscal_year_id)
#             return FiscalYearOut.model_validate(fy)
#
#         except IntegrityError:
#             self.s.rollback()
#             raise BizValidationError("Fiscal year with this name already exists.")
#         except Exception as e:
#             self.s.rollback()
#             log.error("Error updating fiscal year: %s", str(e))
#             raise BizValidationError("Failed to update fiscal year.")
#
from __future__ import annotations

import logging
import datetime as dt
from typing import Optional
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import Forbidden, NotFound

from app.application_accounting.chart_of_accounts.models import FiscalYear, FiscalYearStatusEnum
from app.application_accounting.chart_of_accounts.Repository.fiscal_year_repo import FiscalYearRepository
from app.application_accounting.chart_of_accounts.schemas.fiscal_year_schemas import (
    FiscalYearCreate,
    FiscalYearUpdate,
    FiscalYearOut,
)
from app.application_accounting.chart_of_accounts.validators.fiscal_year_validators import (
    FiscalYearValidator,
)
from app.business_validation.item_validation import BizValidationError
from app.common.cache.cache_invalidator import (
    bump_fiscal_years_list_company,
    bump_fiscal_year_detail,
)
from app.security.rbac_guards import ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext
from config.database import db

log = logging.getLogger(__name__)


class FiscalYearService:
    def __init__(self, repo: Optional[FiscalYearRepository] = None, session=None):
        self.repo = repo or FiscalYearRepository(session or db.session)
        self.s = self.repo.s

    # ------------------------------------------------------------------ #
    # CREATE
    # ------------------------------------------------------------------ #
    def create_fiscal_year(self, payload: FiscalYearCreate, context: AffiliationContext) -> FiscalYearOut:
        """Create Fiscal Year with comprehensive validation"""
        log.info("Creating fiscal year: name='%s', company_id=%d", payload.name, context.company_id)

        # Scope check - user can only create for their company
        ensure_scope_by_ids(context=context, target_company_id=context.company_id)

        # Duplicate name (per company)
        if self.repo.get_fiscal_year_by_name(context.company_id, payload.name):
            raise BizValidationError("Fiscal year with this name already exists.")

        # Only one open year at a time
        if self.repo.get_open_fiscal_year(context.company_id):
            raise BizValidationError("Another fiscal year is already open.")

        # Normalize dates to datetime at 00:00
        start_dt = (
            payload.start_date
            if isinstance(payload.start_date, dt.datetime)
            else dt.datetime.combine(payload.start_date, dt.time.min)
        )
        end_dt = (
            payload.end_date
            if isinstance(payload.end_date, dt.datetime)
            else dt.datetime.combine(payload.end_date, dt.time.min)
        )

        # Validate range & length
        FiscalYearValidator.validate_date_range(start_dt, end_dt)

        # Overlap check
        if self.repo.check_date_overlap(context.company_id, start_dt, end_dt):
            raise BizValidationError("Fiscal year dates overlap with an existing fiscal year.")

        try:
            fy = FiscalYear(
                company_id=context.company_id,
                name=payload.name,
                start_date=start_dt,
                end_date=end_dt,
                status=FiscalYearStatusEnum.OPEN,
                is_short_year=payload.is_short_year,
            )
            self.repo.create_fiscal_year(fy)
            self.s.commit()

            bump_fiscal_years_list_company(context.company_id)
            bump_fiscal_year_detail(fy.id)
            log.info("Fiscal year created successfully: id=%d", fy.id)
            return FiscalYearOut.model_validate(fy)

        except IntegrityError:
            self.s.rollback()
            # Unique constraint on (company_id, name)
            raise BizValidationError("Fiscal year with this name already exists.")
        except Exception as e:
            self.s.rollback()
            log.error("Error creating fiscal year: %s", str(e))
            raise BizValidationError("Failed to create fiscal year.")

    # ------------------------------------------------------------------ #
    # UPDATE (name, status)
    # ------------------------------------------------------------------ #
    def update_fiscal_year(
        self, fiscal_year_id: int, payload: FiscalYearUpdate, context: AffiliationContext
    ) -> FiscalYearOut:
        """Update fiscal year (name and/or status)."""
        fy = self.repo.get_fiscal_year_by_id(fiscal_year_id)
        if not fy:
            raise NotFound("Fiscal year not found.")

        # Scope
        ensure_scope_by_ids(context=context, target_company_id=fy.company_id)

        updates: dict = {}

        # Name change
        if payload.name is not None and payload.name.strip() and payload.name != fy.name:
            if self.repo.get_fiscal_year_by_name(fy.company_id, payload.name):
                raise BizValidationError("Fiscal year with this name already exists.")
            updates["name"] = payload.name.strip()

        # Status change
        if payload.status is not None and payload.status != fy.status:
            FiscalYearValidator.validate_status_transition(fy.status.value, payload.status.value)

            if payload.status == FiscalYearStatusEnum.OPEN:
                existing_open = self.repo.get_open_fiscal_year(fy.company_id)
                if existing_open and existing_open.id != fiscal_year_id:
                    raise BizValidationError("Another fiscal year is already open.")

            updates["status"] = payload.status

        if not updates:
            raise BizValidationError("No changes provided.")

        try:
            self.repo.update_fiscal_year(fy, updates)
            self.s.commit()

            bump_fiscal_years_list_company(fy.company_id)
            bump_fiscal_year_detail(fy.id)
            log.info("Fiscal year updated successfully: id=%d", fiscal_year_id)
            return FiscalYearOut.model_validate(fy)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Fiscal year with this name already exists.")
        except Exception as e:
            self.s.rollback()
            log.error("Error updating fiscal year: %s", str(e))
            raise BizValidationError("Failed to update fiscal year.")

    # ------------------------------------------------------------------ #
    # DELETE
    # ------------------------------------------------------------------ #
    def delete_fiscal_year(self, fiscal_year_id: int, context: AffiliationContext) -> None:
        """
        Delete a fiscal year only if there are no related journal entries
        or general ledger entries (and optionally no closing vouchers).
        """
        fy = self.repo.get_fiscal_year_by_id(fiscal_year_id)
        if not fy:
            raise NotFound("Fiscal year not found.")

        ensure_scope_by_ids(context=context, target_company_id=fy.company_id)

        has_je = self.repo.has_journal_entries(fy.company_id, fy.id)
        has_gle = self.repo.has_general_ledger_entries(fy.company_id, fy.id)
        has_pcv = self.repo.has_period_closing_vouchers(fy.company_id, fy.id)

        FiscalYearValidator.ensure_deletable(
            has_journal_entries=has_je,
            has_gl_entries=has_gle,
            has_closing_vouchers=has_pcv,
        )

        company_id = fy.company_id

        try:
            self.repo.delete_fiscal_year(fy)
            self.s.commit()

            bump_fiscal_years_list_company(company_id)
            log.info("Fiscal year deleted: id=%s", fiscal_year_id)
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error deleting fiscal year: %s", e)
            raise BizValidationError("Unexpected error while deleting fiscal year.")
