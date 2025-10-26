from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.generate_code.service import ensure_manual_code_is_next_and_bump, generate_next_code
from config.database import db

from app.application_stock.stock_models import DocumentType, DocStatusEnum
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.engine.events import make_entry_type
from app.application_accounting.engine.locks import lock_doc
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids


from app.application_accounting.chart_of_accounts.finance_model import Expense, ExpenseItem
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

    def _get(self, expense_id: int, context: AffiliationContext, for_update: bool = False) -> Expense:
        exp = self.repo.get(expense_id)
        if not exp:
            raise BizValidationError("Expense not found.")
        ensure_scope_by_ids(context=context, target_company_id=exp.company_id, target_branch_id=exp.branch_id)
        if for_update:
            self.s.refresh(exp, with_for_update=True)
        return exp

    def _gen_code(self, company_id: int, branch_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            if self.repo.code_exists_exp(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.EXP_PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.EXP_PREFIX, company_id=company_id, branch_id=branch_id)

    # --------------------------- CREATE
    def create(self, *, payload: Dict, context: AffiliationContext) -> Expense:
        company_id = int(payload["company_id"]); branch_id = int(payload["branch_id"])
        code = self._gen_code(company_id, branch_id, payload.get("code"))

        exp = Expense(
            company_id=company_id, branch_id=branch_id, code=code,
            posting_date=payload["posting_date"],
            remarks=payload.get("remarks"),
            created_by_id=context.user_id,
            doc_status=DocStatusEnum.DRAFT,
        )
        self.repo.add(exp)

        for ln in payload["items"]:
            self.repo.add_line(exp.id, ln)

        self.repo.recompute_total(exp.id)
        self.s.commit()
        return exp

    # --------------------------- UPDATE (Draft only; code immutable)
    def update(self, *, expense_id: int, payload: Dict, context: AffiliationContext) -> Expense:
        exp = self._get(expense_id, context, for_update=True)
        if exp.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Expenses can be updated.")
        if "code" in payload and payload["code"] and payload["code"] != exp.code:
            raise BizValidationError("Code cannot be changed after creation.")

        self.repo.update_header(exp, payload)
        if "items" in payload and payload["items"] is not None:
            self.repo.replace_lines(exp.id, payload["items"])

        self.repo.recompute_total(exp.id)
        self.s.commit()
        return exp

    # --------------------------- SUBMIT
    def submit(self, *, expense_id: int, context: AffiliationContext) -> Expense:
        exp = self._get(expense_id, context, for_update=False)
        if exp.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only draft Expenses can be submitted.")
        if not exp.items:
            raise BizValidationError("Expense requires at least one line.")

        doctype_id = self._dtid("EXPENSE")
        template_code = "EXPENSE_DIRECT_LINE"  # ensure seeded in GL templates

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, exp.company_id, doctype_id, exp.id):
                    exp_locked = self._get(expense_id, context, for_update=True)
                    for ln in exp_locked.items:
                        payload = {"document_total": float(ln.amount)}
                        dyn = {"expense_account_id": ln.account_id, "cash_bank_account_id": ln.paid_from_account_id}
                        ctx = PostingContext(
                            company_id=exp_locked.company_id,
                            branch_id=exp_locked.branch_id,
                            source_doctype_id=doctype_id,
                            source_doc_id=exp_locked.id,
                            posting_date=exp_locked.posting_date,
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=make_entry_type(is_auto=True),
                            remarks=f"Expense {exp_locked.code} line {ln.id}",
                            template_code=template_code,
                            payload=payload,
                            dynamic_account_context=dyn,
                        )
                        PostingService(self.s).post(ctx)

                    self.repo.mark_submitted(exp_locked.id)

            self.s.commit()
            return exp

        except PostingValidationError as e:
            self.s.rollback(); raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback(); log.exception("Failed to submit Expense")
            raise BizValidationError("Failed to submit Expense.")

    # --------------------------- CANCEL
    def cancel(self, *, expense_id: int, context: AffiliationContext, reason: Optional[str] = None) -> Expense:
        exp = self._get(expense_id, context, for_update=True)
        if exp.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only submitted Expenses can be cancelled.")

        doctype_id = self._dtid("EXPENSE")
        template_code = "EXPENSE_DIRECT_LINE"

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, exp.company_id, doctype_id, exp.id):
                    for ln in exp.items:
                        payload = {"document_total": float(-Decimal(ln.amount or 0))}
                        dyn = {"expense_account_id": ln.account_id, "cash_bank_account_id": ln.paid_from_account_id}
                        ctx = PostingContext(
                            company_id=exp.company_id,
                            branch_id=exp.branch_id,
                            source_doctype_id=doctype_id,
                            source_doc_id=exp.id,
                            posting_date=exp.posting_date,
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=make_entry_type(is_auto=True, for_reversal=True),
                            remarks=f"Cancel Expense {exp.code} line {ln.id}" + (f" — {reason}" if reason else ""),
                            template_code=template_code,
                            payload=payload,
                            dynamic_account_context=dyn,
                        )
                        PostingService(self.s).post(ctx)
                    self.repo.mark_cancelled(exp.id)
            self.s.commit()
            return exp

        except PostingValidationError as e:
            self.s.rollback(); raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback(); log.exception("Failed to cancel Expense")
            raise BizValidationError("Failed to cancel Expense.")
