# app/application_accounting/chart_of_accounts/services/fiscal_year_service.py
from __future__ import annotations

import logging
import datetime as dt
from typing import Optional

from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

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
from app.security.rbac_guards import ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext
from config.database import db

# ✅ NEW cache invalidation (no old cache_invalidator imports)
from app.common.cache.invalidation import (
    bump_company_list,
    bump_dropdown_for_context,
    bump_detail,
)

log = logging.getLogger(__name__)


class FiscalYearService:
    def __init__(self, repo: Optional[FiscalYearRepository] = None, session=None):
        self.repo = repo or FiscalYearRepository(session or db.session)
        self.s = self.repo.s

    # ------------------------------------------------------------------ #
    # CREATE
    # ------------------------------------------------------------------ #
    def create_fiscal_year(self, payload: FiscalYearCreate, context: AffiliationContext) -> FiscalYearOut:
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
                name=payload.name.strip(),
                start_date=start_dt,
                end_date=end_dt,
                status=FiscalYearStatusEnum.OPEN,
                is_short_year=payload.is_short_year,
            )
            self.repo.create_fiscal_year(fy)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                # Company list (assumes you registered ListConfig entity_name="fiscal_years")
                bump_company_list("accounting", "fiscal_years", context, context.company_id)

                # If you have a dropdown (optional)
                # bump_dropdown_for_context("accounting", "fiscal_years", context, params={"company_id": context.company_id})

                # Detail (if cached anywhere)
                bump_detail("accounting:fiscal_years", int(fy.id))
            except Exception:
                log.exception("[cache] failed to bump fiscal_year caches after create")

            log.info("Fiscal year created successfully: id=%d", fy.id)
            return FiscalYearOut.model_validate(fy)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Fiscal year with this name already exists.")
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Error creating fiscal year: %s", e)
            raise BizValidationError("Failed to create fiscal year.")

    # ------------------------------------------------------------------ #
    # UPDATE (name, status)
    # ------------------------------------------------------------------ #
    def update_fiscal_year(self, fiscal_year_id: int, payload: FiscalYearUpdate, context: AffiliationContext) -> FiscalYearOut:
        fy = self.repo.get_fiscal_year_by_id(fiscal_year_id)
        if not fy:
            raise NotFound("Fiscal year not found.")

        ensure_scope_by_ids(context=context, target_company_id=fy.company_id)

        updates: dict = {}

        # Name change
        if payload.name is not None and payload.name.strip() and payload.name.strip() != fy.name:
            if self.repo.get_fiscal_year_by_name(fy.company_id, payload.name.strip()):
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

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("accounting", "fiscal_years", context, int(fy.company_id))
                bump_detail("accounting:fiscal_years", int(fy.id))
            except Exception:
                log.exception("[cache] failed to bump fiscal_year caches after update")

            log.info("Fiscal year updated successfully: id=%d", fiscal_year_id)
            return FiscalYearOut.model_validate(fy)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Fiscal year with this name already exists.")
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Error updating fiscal year: %s", e)
            raise BizValidationError("Failed to update fiscal year.")

    # ------------------------------------------------------------------ #
    # DELETE
    # ------------------------------------------------------------------ #
    def delete_fiscal_year(self, fiscal_year_id: int, context: AffiliationContext) -> None:
        fy = self.repo.get_fiscal_year_by_id(fiscal_year_id)
        if not fy:
            raise NotFound("Fiscal year not found.")

        ensure_scope_by_ids(context=context, target_company_id=fy.company_id)

        # These repo methods must exist (you referenced them)
        has_je = self.repo.has_journal_entries(fy.company_id, fy.id)
        has_gle = self.repo.has_general_ledger_entries(fy.company_id, fy.id)
        has_pcv = self.repo.has_period_closing_vouchers(fy.company_id, fy.id)

        FiscalYearValidator.ensure_deletable(
            has_journal_entries=has_je,
            has_gl_entries=has_gle,
            has_closing_vouchers=has_pcv,
        )

        company_id = int(fy.company_id)

        try:
            self.repo.delete_fiscal_year(fy)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("accounting", "fiscal_years", context, company_id)
                # No need to bump detail after delete, but harmless if you do:
                bump_detail("accounting:fiscal_years", int(fiscal_year_id))
            except Exception:
                log.exception("[cache] failed to bump fiscal_year caches after delete")

            log.info("Fiscal year deleted: id=%s", fiscal_year_id)

        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error deleting fiscal year: %s", e)
            raise BizValidationError("Unexpected error while deleting fiscal year.")