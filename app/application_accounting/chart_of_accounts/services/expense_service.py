from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.generate_code.service import ensure_manual_code_is_next_and_bump, generate_next_code
from config.database import db
from app.common.timezone.service import get_company_timezone
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.business_validation.posting_date_validation import PostingDateValidator

from app.application_stock.stock_models import DocumentType, DocStatusEnum
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.engine.events import make_entry_type
from app.application_accounting.engine.locks import lock_doc
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_accounting.chart_of_accounts.finance_model import Expense, ExpenseItem, ExpenseType
from app.application_accounting.chart_of_accounts.Repository.expense_repo import ExpenseRepo

log = logging.getLogger(__name__)


class ExpenseService:
    EXP_PREFIX = "EXP"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = ExpenseRepo(self.s)

    def _dtid(self, code: str) -> int:
        rid = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not rid:
            raise BizValidationError(f"DocumentType '{code}' not found.")
        return int(rid)

    def _get_expense(self, expense_id: int, context: AffiliationContext, for_update: bool = False) -> Expense:
        exp = self.repo.get(expense_id)
        if not exp:
            raise BizValidationError("Expense not found.")
        ensure_scope_by_ids(context=context, target_company_id=exp.company_id, target_branch_id=exp.branch_id)
        if for_update:
            self.s.refresh(exp, with_for_update=True)
        return exp

    def _get_expense_type(self, expense_type_id: int, context: AffiliationContext) -> ExpenseType:
        exp_type = self.repo.get_expense_type(expense_type_id)
        if not exp_type:
            raise BizValidationError("Expense Type not found.")
        ensure_scope_by_ids(context=context, target_company_id=exp_type.company_id, target_branch_id=None)
        return exp_type

    def _gen_code(self, company_id: int, branch_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            if self.repo.code_exists_exp(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.EXP_PREFIX, company_id=company_id, branch_id=branch_id,
                                                code=code)
            return code
        return generate_next_code(prefix=self.EXP_PREFIX, company_id=company_id, branch_id=branch_id)

    # --------------------------- EXPENSE TYPE METHODS ---------------------------
    def create_expense_type(self, *, payload: Dict, context: AffiliationContext) -> ExpenseType:
        company_id = payload.get("company_id") or context.company_id
        if not company_id:
            raise BizValidationError("Company context is required to create Expense Type.")

        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

        if self.repo.expense_type_name_exists(company_id, payload["name"]):
            raise BizValidationError("Expense Type with this name already exists.")

        if payload.get("default_account_id"):
            self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=[payload["default_account_id"]])

        exp_type = ExpenseType(
            company_id=company_id,
            name=payload["name"],
            description=payload.get("description"),
            default_account_id=payload.get("default_account_id"),
            enabled=True,
        )

        self.repo.add_expense_type(exp_type)
        self.s.commit()
        return exp_type

    def update_expense_type(self, *, expense_type_id: int, payload: Dict, context: AffiliationContext) -> ExpenseType:
        exp_type = self._get_expense_type(expense_type_id, context)

        if "name" in payload and payload["name"] != exp_type.name:
            if self.repo.expense_type_name_exists(exp_type.company_id, payload["name"], exclude_id=expense_type_id):
                raise BizValidationError("Expense Type with this name already exists.")

        if "default_account_id" in payload and payload["default_account_id"]:
            self.repo.ensure_accounts_accessible(company_id=exp_type.company_id,
                                                 account_ids=[payload["default_account_id"]])

        self.repo.update_expense_type(exp_type, payload)
        self.s.commit()
        return exp_type

    # --------------------------- EXPENSE DOCUMENT METHODS ---------------------------
    def create(self, *, payload: Dict, context: AffiliationContext) -> Expense:
        company_id = payload.get("company_id") or context.company_id
        branch_id = payload.get("branch_id") or context.branch_id

        if not company_id or not branch_id:
            raise BizValidationError("Company and Branch context are required to create Expense.")

        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        code = self._gen_code(company_id, branch_id, payload.get("code"))

        # Validate posting date
        _ = PostingDateValidator.validate_standalone_document(
            self.s, payload["posting_date"], company_id, created_at=None, treat_midnight_as_date=True
        )

        # Validate all accounts
        all_account_ids = set()
        for item in payload["items"]:
            all_account_ids.add(item["account_id"])
            all_account_ids.add(item["paid_from_account_id"])

        self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=list(all_account_ids))

        # Validate expense types if provided
        for item in payload["items"]:
            if item.get("expense_type_id"):
                self.repo.ensure_expense_type_accessible(company_id=company_id, expense_type_id=item["expense_type_id"])

        exp = Expense(
            company_id=company_id,
            branch_id=branch_id,
            code=code,
            posting_date=payload["posting_date"],
            remarks=payload.get("remarks"),
            cost_center_id=payload.get("cost_center_id"),
            created_by_id=context.user_id,
            doc_status=DocStatusEnum.DRAFT,
        )
        self.repo.add(exp)

        for ln in payload["items"]:
            self.repo.add_line(exp.id, ln)

        self.repo.recompute_total(exp.id)
        self.s.commit()
        return exp

    def update(self, *, expense_id: int, payload: Dict, context: AffiliationContext) -> Expense:
        exp = self._get_expense(expense_id, context, for_update=True)
        if exp.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Expenses can be updated.")
        if "code" in payload and payload["code"] and payload["code"] != exp.code:
            raise BizValidationError("Code cannot be changed after creation.")

        if "posting_date" in payload and payload["posting_date"]:
            _ = PostingDateValidator.validate_standalone_document(
                self.s, payload["posting_date"], exp.company_id, created_at=exp.created_at, treat_midnight_as_date=True
            )

        self.repo.update_header(exp, payload)

        if "items" in payload and payload["items"] is not None:
            # Validate new accounts
            all_account_ids = set()
            for item in payload["items"]:
                all_account_ids.add(item["account_id"])
                all_account_ids.add(item["paid_from_account_id"])

            self.repo.ensure_accounts_accessible(company_id=exp.company_id, account_ids=list(all_account_ids))

            # Validate expense types if provided
            for item in payload["items"]:
                if item.get("expense_type_id"):
                    self.repo.ensure_expense_type_accessible(company_id=exp.company_id,
                                                             expense_type_id=item["expense_type_id"])

            self.repo.replace_lines(exp.id, payload["items"])
            self.repo.recompute_total(exp.id)

        self.s.commit()
        return exp

    def submit(self, *, expense_id: int, context: AffiliationContext) -> Expense:
        exp = self._get_expense(expense_id, context, for_update=False)
        if exp.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only draft Expenses can be submitted.")
        if not exp.items:
            raise BizValidationError("Expense requires at least one line.")

        tz = get_company_timezone(self.s, exp.company_id)
        posting_dt = resolve_posting_dt(exp.posting_date, created_at=exp.created_at, tz=tz, treat_midnight_as_date=True)
        doctype_id = self._dtid("EXPENSE_CLAIM")
        template_code = "EXPENSE_DIRECT_LINE"

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, exp.company_id, doctype_id, exp.id):
                    exp_locked = self._get_expense(expense_id, context, for_update=True)
                    if exp_locked.doc_status != DocStatusEnum.DRAFT:
                        raise BizValidationError("Only draft Expenses can be submitted.")

                    for ln in exp_locked.items:
                        payload = {"document_total": float(ln.amount)}
                        dyn = {
                            "expense_account_id": ln.account_id,
                            "cash_bank_account_id": ln.paid_from_account_id
                        }
                        ctx = PostingContext(
                            company_id=exp_locked.company_id,
                            branch_id=exp_locked.branch_id,
                            source_doctype_id=doctype_id,
                            source_doc_id=exp_locked.id,
                            posting_date=posting_dt,
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=make_entry_type(is_auto=True),
                            remarks=f"Expense {exp_locked.code} line {ln.id}",
                            template_code=template_code,
                            payload=payload,
                            runtime_accounts={},
                            dynamic_account_context=dyn,
                        )
                        PostingService(self.s).post(ctx)

                    self.repo.mark_submitted(exp_locked.id)

            self.s.commit()
            return exp

        except PostingValidationError as e:
            self.s.rollback()
            raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback()
            log.exception("Failed to submit Expense")
            raise BizValidationError("Failed to submit Expense.")

    def cancel(self, *, expense_id: int, context: AffiliationContext, reason: Optional[str] = None) -> Expense:
        exp = self._get_expense(expense_id, context, for_update=True)
        if exp.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only submitted Expenses can be cancelled.")

        tz = get_company_timezone(self.s, exp.company_id)
        posting_dt = resolve_posting_dt(exp.posting_date, created_at=exp.created_at, tz=tz, treat_midnight_as_date=True)
        doctype_id = self._dtid("EXPENSE_CLAIM")
        template_code = "EXPENSE_DIRECT_LINE"

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, exp.company_id, doctype_id, exp.id):
                    for ln in exp.items:
                        payload = {"document_total": float(-Decimal(ln.amount or 0))}
                        dyn = {
                            "expense_account_id": ln.account_id,
                            "cash_bank_account_id": ln.paid_from_account_id
                        }
                        ctx = PostingContext(
                            company_id=exp.company_id,
                            branch_id=exp.branch_id,
                            source_doctype_id=doctype_id,
                            source_doc_id=exp.id,
                            posting_date=posting_dt,
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=make_entry_type(is_auto=True, for_reversal=True),
                            remarks=f"Cancel Expense {exp.code} line {ln.id}" + (f" — {reason}" if reason else ""),
                            template_code=template_code,
                            payload=payload,
                            runtime_accounts={},
                            dynamic_account_context=dyn,
                        )
                        PostingService(self.s).post(ctx)

                    self.repo.mark_cancelled(exp.id)

            self.s.commit()
            return exp

        except PostingValidationError as e:
            self.s.rollback()
            raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback()
            log.exception("Failed to cancel Expense")
            raise BizValidationError("Failed to cancel Expense.")