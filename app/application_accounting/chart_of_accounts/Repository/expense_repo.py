from __future__ import annotations
from typing import Optional, Dict
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select, update, func

from config.database import db
from app.application_accounting.chart_of_accounts.finance_model import Expense, ExpenseItem
from app.application_stock.stock_models import DocStatusEnum

class ExpenseRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

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
        self.s.add(obj); self.s.flush(); return obj

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
        self.s.add(row); self.s.flush(); return row

    def replace_lines(self, expense_id: int, lines: list[Dict]) -> None:
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
        # immutable: code
        mutable = ("posting_date", "remarks", "cost_center_id")
        for k in mutable:
            if k in data:
                setattr(exp, k, data[k])
        self.s.flush()
        return exp

    def mark_submitted(self, expense_id: int) -> None:
        self.s.execute(
            update(Expense).where(Expense.id == expense_id)
            .values(doc_status=DocStatusEnum.SUBMITTED)
        ); self.s.flush()

    def mark_cancelled(self, expense_id: int) -> None:
        self.s.execute(
            update(Expense).where(Expense.id == expense_id)
            .values(doc_status=DocStatusEnum.CANCELLED)
        ); self.s.flush()
