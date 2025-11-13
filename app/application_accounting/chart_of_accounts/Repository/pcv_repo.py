# app/application_accounting/chart_of_accounts/Repository/pcv_repo.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest

from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, PeriodClosingVoucher, Account, AccountTypeEnum, ReportTypeEnum,
    GeneralLedgerEntry,
)
from app.application_stock.stock_models import DocStatusEnum
from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump

# ⚠️ Adjust this import to your actual Branch model location
from app.application_org.models.company import Branch
class PCVRepository:
    PCV_PREFIX = "PCV"

    def __init__(self, s: Session):
        self.s = s

    # ---- codes ----
    def generate_or_validate_code(self, *, company_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            exists = self.s.execute(
                select(PeriodClosingVoucher.id).where(
                    PeriodClosingVoucher.company_id == company_id,
                    PeriodClosingVoucher.code == code
                ).limit(1)
            ).scalar_one_or_none()
            if exists:
                raise ValueError("Document code already exists.")
            ensure_manual_code_is_next_and_bump(prefix=self.PCV_PREFIX, company_id=company_id, branch_id=None, code=code)
            return code
        return generate_next_code(prefix=self.PCV_PREFIX, company_id=company_id, branch_id=None, session=self.s)

    # ---- persistence ----
    def save(self, pcv: PeriodClosingVoucher) -> None:
        self.s.add(pcv)

    def get(self, pcv_id: int, for_update: bool = False) -> Optional[PeriodClosingVoucher]:
        q = select(PeriodClosingVoucher).where(PeriodClosingVoucher.id == pcv_id)
        if for_update:
            q = q.with_for_update()
        return self.s.execute(q).scalar_one_or_none()

    def get_doctype_id(self, code: str) -> int:
        from app.application_stock.stock_models import DocumentType
        val = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not val:
            raise ValueError(f"DocumentType '{code}' not found.")
        return int(val)

    # ---- FY ----
    def get_fy(self, fy_id: int, company_id: int) -> Optional[FiscalYear]:
        return self.s.execute(
            select(FiscalYear).where(FiscalYear.id == fy_id, FiscalYear.company_id == company_id)
        ).scalar_one_or_none()

    # ---- account checks ----
    def is_equity_or_liability_ledger(self, account_id: int, company_id: int) -> bool:
        a = self.s.execute(
            select(Account).where(Account.id == account_id, Account.company_id == company_id)
        ).scalar_one_or_none()
        return bool(a and not a.is_group and a.account_type in {AccountTypeEnum.EQUITY, AccountTypeEnum.LIABILITY})

    # ---- net P&L for FY ----
    def compute_net_pl_for_fy(self, *, company_id: int, fiscal_year_id: int) -> Decimal:
        inc = self.s.execute(
            select(func.coalesce(func.sum(GeneralLedgerEntry.credit - GeneralLedgerEntry.debit), 0))
            .join(Account, Account.id == GeneralLedgerEntry.account_id)
            .where(
                GeneralLedgerEntry.company_id == company_id,
                GeneralLedgerEntry.fiscal_year_id == fiscal_year_id,
                Account.account_type == AccountTypeEnum.INCOME
            )
        ).scalar() or 0
        exp = self.s.execute(
            select(func.coalesce(func.sum(GeneralLedgerEntry.debit - GeneralLedgerEntry.credit), 0))
            .join(Account, Account.id == GeneralLedgerEntry.account_id)
            .where(
                GeneralLedgerEntry.company_id == company_id,
                GeneralLedgerEntry.fiscal_year_id == fiscal_year_id,
                Account.account_type == AccountTypeEnum.EXPENSE
            )
        ).scalar() or 0
        return Decimal(str(inc)) - Decimal(str(exp))

    # ---- P&L Summary helper ----
    def get_or_create_pl_summary_account(self, company_id: int, *, code: str = "3999", name: str = "P&L Summary") -> int:
        acc_id = self.s.execute(
            select(Account.id).where(Account.company_id == company_id, Account.code == code).limit(1)
        ).scalar_one_or_none()
        if acc_id:
            return int(acc_id)

        a = Account(
            company_id=company_id,
            parent_account_id=None,
            code=code,
            name=name,
            account_type=AccountTypeEnum.EQUITY,
            report_type=ReportTypeEnum.BALANCE_SHEET,
            is_group=False,
            enabled=True,
        )
        self.s.add(a)
        self.s.flush([a])
        return int(a.id)

    def already_closed_for_fy(self, *, company_id: int, fiscal_year_id: int) -> bool:
        cnt = self.s.execute(
            select(func.count()).select_from(PeriodClosingVoucher).where(
                PeriodClosingVoucher.company_id == company_id,
                PeriodClosingVoucher.closing_fiscal_year_id == fiscal_year_id,
                PeriodClosingVoucher.doc_status.in_([DocStatusEnum.SUBMITTED, DocStatusEnum.RETURNED])
            )
        ).scalar() or 0
        return cnt > 0

    # ---- branch resolver (no client branch required) ----
    def resolve_branch_id_for_company(self, company_id: int, *, ctx_branch_id: int | None) -> int:
        # 1) Use context branch if it belongs to the same company
        if ctx_branch_id:
            ok = self.s.execute(
                select(Branch.id).where(Branch.id == ctx_branch_id, Branch.company_id == company_id).limit(1)
            ).scalar_one_or_none()
            if ok:
                return int(ok)

        # 2) Prefer default branch if such column/flag exists
        try:
            default_id = self.s.execute(
                select(Branch.id)
                .where(Branch.company_id == company_id, Branch.is_default == True)  # noqa: E712
                .order_by(Branch.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if default_id:
                return int(default_id)
        except Exception:
            # is_default might not exist; ignore
            pass

        # 3) Fallback to any branch for this company
        any_id = self.s.execute(
            select(Branch.id).where(Branch.company_id == company_id).order_by(Branch.id.asc()).limit(1)
        ).scalar_one_or_none()
        if any_id:
            return int(any_id)

        # 4) No branches at all
        raise BadRequest("No Branch found for company. Create a Branch first.")
