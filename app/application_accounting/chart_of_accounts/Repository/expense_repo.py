from __future__ import annotations
from typing import Optional, Dict, List, Sequence
from decimal import Decimal

from sqlalchemy import select, update, func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.database import db
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import Account
from app.application_accounting.chart_of_accounts.finance_model import Expense, ExpenseItem,ExpenseType
from app.business_validation.item_validation import (
    BizValidationError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_DISABLED,
    ERR_ACCOUNT_WRONG_COMPANY,
    ERR_GROUP_ACCOUNT_NOT_ALLOWED,
)

class ExpenseRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    # ---------- Expense Type Methods ----------
    def get_expense_type(self, expense_type_id: int) -> Optional[ExpenseType]:
        return self.s.get(ExpenseType, expense_type_id)

    def add_expense_type(self, obj: ExpenseType) -> ExpenseType:
        self.s.add(obj)
        self.s.flush([obj])
        return obj

    def update_expense_type(self, expense_type: ExpenseType, data: Dict) -> ExpenseType:
        mutable = ("name", "description", "default_account_id", "enabled")
        for k in mutable:
            if k in data:
                setattr(expense_type, k, data[k])
        self.s.flush([expense_type])
        return expense_type

    def expense_type_name_exists(self, company_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        q = select(ExpenseType.id).where(
            ExpenseType.company_id == company_id,
            ExpenseType.name == name,
        )
        if exclude_id:
            q = q.where(ExpenseType.id != exclude_id)
        return self.s.execute(q).scalar_one_or_none() is not None

    # ---------- Expense Document Methods ----------
    def code_exists_exp(self, company_id: int, branch_id: int, code: str) -> bool:
        q = select(Expense.id).where(
            Expense.company_id == company_id,
            Expense.branch_id == branch_id,
            Expense.code == code,
        )
        return self.s.execute(q).scalar_one_or_none() is not None

    def get(self, expense_id: int) -> Optional[Expense]:
        return self.s.get(Expense, expense_id)

    def add(self, obj: Expense) -> Expense:
        self.s.add(obj)
        self.s.flush([obj])
        return obj

    def add_line(self, expense_id: int, ln: Dict) -> ExpenseItem:
        row = ExpenseItem(
            expense_id=expense_id,
            account_id=ln["account_id"],
            paid_from_account_id=ln["paid_from_account_id"],
            description=ln.get("description"),
            amount=Decimal(str(ln["amount"])),
            cost_center_id=ln.get("cost_center_id"),
            expense_type_id=ln.get("expense_type_id"),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def replace_lines(self, expense_id: int, lines: List[Dict]) -> None:
        self.s.query(ExpenseItem).filter(ExpenseItem.expense_id == expense_id).delete()
        for ln in lines or []:
            self.add_line(expense_id, ln)
        self.s.flush()

    def recompute_total(self, expense_id: int) -> Decimal:
        total = self.s.execute(
            select(func.coalesce(func.sum(ExpenseItem.amount), 0))
            .where(ExpenseItem.expense_id == expense_id)
        ).scalar_one()
        exp = self.get(expense_id)
        exp.total_amount = Decimal(total or 0)
        self.s.flush()
        return Decimal(total or 0)

    def update_header(self, exp: Expense, data: Dict) -> Expense:
        mutable = ("posting_date", "remarks", "cost_center_id")
        for k in mutable:
            if k in data:
                setattr(exp, k, data[k])
        self.s.flush([exp])
        return exp

    def mark_submitted(self, expense_id: int) -> None:
        self.s.execute(
            update(Expense).where(Expense.id == expense_id)
            .values(doc_status=DocStatusEnum.SUBMITTED)
        )
        self.s.flush()

    def mark_cancelled(self, expense_id: int) -> None:
        self.s.execute(
            update(Expense).where(Expense.id == expense_id)
            .values(doc_status=DocStatusEnum.CANCELLED)
        )
        self.s.flush()

    # ---------- Account Validation ----------
    def get_accounts_meta(self, account_ids: Sequence[int]) -> Dict[int, Dict]:
        if not account_ids:
            return {}
        rows = self.s.execute(
            select(
                Account.id, Account.company_id, Account.code, Account.name,
                Account.is_group, Account.enabled
            ).where(Account.id.in_([int(x) for x in account_ids]))
        ).all()
        out: Dict[int, Dict] = {}
        for r in rows:
            out[int(r.id)] = {
                "id": int(r.id),
                "company_id": int(r.company_id),
                "code": str(r.code),
                "name": r.name,
                "is_group": bool(r.is_group),
                "enabled": bool(r.enabled),
            }
        return out

    def ensure_accounts_accessible(self, *, company_id: int, account_ids: Sequence[int]) -> None:
        """Validate accounts exist, belong to company, are enabled and are detail accounts."""
        metas = self.get_accounts_meta(account_ids)

        for aid in account_ids:
            meta = metas.get(int(aid))
            if not meta:
                raise BizValidationError(ERR_ACCOUNT_NOT_FOUND)
            if int(meta["company_id"]) != int(company_id):
                raise BizValidationError(ERR_ACCOUNT_WRONG_COMPANY)
            if not meta["enabled"]:
                raise BizValidationError(ERR_ACCOUNT_DISABLED)
            if meta["is_group"]:
                raise BizValidationError(ERR_GROUP_ACCOUNT_NOT_ALLOWED)

    # ---------- Expense Type Validation ----------
    def ensure_expense_type_accessible(self, *, company_id: int, expense_type_id: int) -> None:
        """Validate expense type exists, belongs to company and is enabled."""
        exp_type = self.get_expense_type(expense_type_id)
        if not exp_type:
            raise BizValidationError("Expense Type not found.")
        if int(exp_type.company_id) != int(company_id):
            raise BizValidationError("Expense Type does not belong to this company.")
        if not exp_type.enabled:
            raise BizValidationError("Expense Type is disabled.")