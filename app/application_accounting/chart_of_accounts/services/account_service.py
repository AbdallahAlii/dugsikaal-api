from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from app.application_accounting.chart_of_accounts.models import Account
from app.application_accounting.chart_of_accounts.Repository.account_repo import AccountRepository
from app.application_accounting.chart_of_accounts.schemas.account_schemas import (
    AccountCreate,
    AccountUpdate,
    AccountOut,
)
from app.application_accounting.chart_of_accounts.validators.account_validators import (
    AccountValidator,
    ERR_ACCOUNT_EXISTS, ERR_PARENT_REQUIRED, ERR_ACCOUNT_NAME_EXISTS,
)
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from config.database import db

from app.common.cache.cache_invalidator import (
    bump_accounts_list_company,
    bump_account_detail,
    bump_coa_structure_company,
)
from app.application_reports.hook.invalidation import (
    invalidate_financial_reports_for_company,
)

log = logging.getLogger(__name__)


class AccountService:
    def __init__(self, repo: Optional[AccountRepository] = None, session=None):
        self.repo = repo or AccountRepository(session or db.session)
        self.s = self.repo.s

        # --- Create ---

    def create_account(self, payload: AccountCreate, ctx: AffiliationContext) -> AccountOut:
        """
        Business rules:
          - parent_account_id is required and must be a group
          - account_type must match parent.account_type
          - code:
              * if provided: validate format, prefix, range, uniqueness
              * if omitted: auto-generate under parent
          - name: must be unique per company
          - report_type must match type (BS vs P&L)
        """
        log.info(
            "AccountService.create_account: company_id=%s user_id=%s payload=%s",
            ctx.company_id,
            getattr(ctx, "user_id", None),
            payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
        )

        ensure_scope_by_ids(context=ctx, target_company_id=ctx.company_id)

        # 1) Require & load parent
        if payload.parent_account_id is None:
            raise BizValidationError(ERR_PARENT_REQUIRED)

        log.info(
            "AccountService.create_account: looking up parent_account_id=%s",
            payload.parent_account_id,
        )
        parent = self.repo.get_by_id(payload.parent_account_id)
        if parent is None:
            raise BizValidationError("Parent account not found.")

        AccountValidator.validate_parent_on_create(parent=parent, account_type=payload.account_type)

        # 2) Validate report_type vs account_type
        AccountValidator.validate_report_type(payload.account_type, payload.report_type)

        # 3) Enforce name uniqueness per company
        # (name already stripped by Pydantic, but we normalize anyway)
        name = payload.name.strip()
        existing_by_name = self.repo.get_by_name(ctx.company_id, name)
        if existing_by_name:
            raise BizValidationError(
                ERR_ACCOUNT_NAME_EXISTS.format(name=name)
            )

        # 4) Resolve / generate account code
        code: Optional[str] = (payload.code or None)
        if code:
            code = code.strip()
            AccountValidator.validate_code_format_and_prefix(code, payload.account_type)

            existing = self.repo.get_by_code(ctx.company_id, code)
            if existing:
                raise BizValidationError(
                    ERR_ACCOUNT_EXISTS.format(code=code, name=existing.name)
                )
        else:
            child_codes = self.repo.get_child_codes(ctx.company_id, parent.id)
            code = AccountValidator.generate_next_code(
                parent=parent,
                existing_child_codes=child_codes,
                account_type=payload.account_type,
            )

            existing = self.repo.get_by_code(ctx.company_id, code)
            if existing:
                raise BizValidationError(
                    ERR_ACCOUNT_EXISTS.format(code=code, name=existing.name)
                )

        try:
            acc = Account(
                company_id=ctx.company_id,
                parent_account_id=payload.parent_account_id,
                code=code,
                name=name,
                account_type=payload.account_type,
                report_type=payload.report_type,
                is_group=payload.is_group,
                debit_or_credit=payload.debit_or_credit,
                enabled=True,
            )
            self.repo.add(acc)
            self.s.commit()

            bump_accounts_list_company(ctx.company_id)
            bump_account_detail(acc.id)
            bump_coa_structure_company(ctx.company_id)
            invalidate_financial_reports_for_company(ctx.company_id)

            log.info("Account created: id=%s code=%s", acc.id, acc.code)
            return AccountOut.model_validate(acc)

        except IntegrityError:
            self.s.rollback()
            existing = self.repo.get_by_code(ctx.company_id, code)
            if existing:
                raise BizValidationError(
                    ERR_ACCOUNT_EXISTS.format(code=code, name=existing.name)
                )
            log.exception("IntegrityError while creating account")
            raise BizValidationError("Database error while creating account.")
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception:
            self.s.rollback()
            log.exception("Unexpected error creating account")
            raise BizValidationError("Unexpected error while creating account.")

        # --- Update ---

    def update_account(self, account_id: int, payload: AccountUpdate, ctx: AffiliationContext) -> AccountOut:
        acc = self.repo.get_by_id(account_id)
        if not acc:
            raise NotFound("Account not found.")

        ensure_scope_by_ids(context=ctx, target_company_id=acc.company_id)

        updates: dict = {}

        # code change
        if payload.code is not None and payload.code.strip() and payload.code != acc.code:
            new_code = payload.code.strip()
            AccountValidator.validate_code_format_and_prefix(new_code, acc.account_type)
            existing = self.repo.get_by_code(acc.company_id, new_code)
            if existing and existing.id != acc.id:
                raise BizValidationError(
                    ERR_ACCOUNT_EXISTS.format(code=new_code, name=existing.name)
                )
            updates["code"] = new_code

        # name change (must be unique per company)
        if payload.name is not None and payload.name.strip() and payload.name != acc.name:
            new_name = payload.name.strip()
            existing_by_name = self.repo.get_by_name(acc.company_id, new_name)
            if existing_by_name and existing_by_name.id != acc.id:
                raise BizValidationError(
                    ERR_ACCOUNT_NAME_EXISTS.format(name=new_name)
                )
            updates["name"] = new_name

        if payload.account_type is not None and payload.account_type != acc.account_type:
            updates["account_type"] = payload.account_type

        if payload.report_type is not None and payload.report_type != acc.report_type:
            updates["report_type"] = payload.report_type

        if payload.is_group is not None and payload.is_group != acc.is_group:
            updates["is_group"] = payload.is_group

        if payload.debit_or_credit is not None and payload.debit_or_credit != acc.debit_or_credit:
            updates["debit_or_credit"] = payload.debit_or_credit

        if payload.parent_account_id is not None and payload.parent_account_id != acc.parent_account_id:
            parent = self.repo.get_by_id(payload.parent_account_id)
            AccountValidator.validate_parent_on_create(parent=parent, account_type=acc.account_type)
            updates["parent_account_id"] = payload.parent_account_id

        if payload.enabled is not None and payload.enabled != acc.enabled:
            updates["enabled"] = payload.enabled

        if not updates:
            raise BizValidationError("No changes provided.")

        new_type = updates.get("account_type", acc.account_type)
        new_report_type = updates.get("report_type", acc.report_type)
        AccountValidator.validate_report_type(new_type, new_report_type)

        has_children = self.repo.has_children(acc.company_id, acc.id)
        has_txn = self.repo.has_transactions(acc.company_id, acc.id)
        AccountValidator.ensure_safe_update(
            account=acc,
            updates=updates,
            has_transactions=has_txn,
            has_children=has_children,
        )

        try:
            self.repo.update(acc, updates)
            self.s.commit()

            bump_accounts_list_company(acc.company_id)
            bump_account_detail(acc.id)
            bump_coa_structure_company(acc.company_id)
            invalidate_financial_reports_for_company(acc.company_id)

            log.info("Account updated: id=%s", acc.id)
            return AccountOut.model_validate(acc)

        except IntegrityError:
            self.s.rollback()
            if "code" in updates:
                existing = self.repo.get_by_code(acc.company_id, updates["code"])
                if existing and existing.id != acc.id:
                    raise BizValidationError(
                        ERR_ACCOUNT_EXISTS.format(code=updates["code"], name=existing.name)
                    )
            if "name" in updates:
                existing_by_name = self.repo.get_by_name(acc.company_id, updates["name"])
                if existing_by_name and existing_by_name.id != acc.id:
                    raise BizValidationError(
                        ERR_ACCOUNT_NAME_EXISTS.format(name=updates["name"])
                    )
            raise BizValidationError("Database error while updating account.")
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error updating account: %s", e)
            raise BizValidationError("Unexpected error while updating account.")
    # --- Delete --- (as you already had, just kept) ---

    def delete_account(self, account_id: int, ctx: AffiliationContext) -> None:
        acc = self.repo.get_by_id(account_id)
        if not acc:
            raise NotFound("Account not found.")

        ensure_scope_by_ids(context=ctx, target_company_id=acc.company_id)

        has_children = self.repo.has_children(acc.company_id, acc.id)
        has_txn = self.repo.has_transactions(acc.company_id, acc.id)
        AccountValidator.ensure_deletable(
            account=acc,
            has_children=has_children,
            has_transactions=has_txn,
        )

        company_id = acc.company_id

        try:
            self.repo.delete(acc)
            self.s.commit()

            bump_accounts_list_company(company_id)
            bump_coa_structure_company(company_id)
            invalidate_financial_reports_for_company(company_id)

            log.info("Account deleted: id=%s", account_id)
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Account with existing transaction can not be deleted.")
        except BizValidationError:
            self.s.rollback()
            raise
        except Exception as e:
            self.s.rollback()
            log.exception("Unexpected error deleting account: %s", e)
            raise BizValidationError("Unexpected error while deleting account.")
