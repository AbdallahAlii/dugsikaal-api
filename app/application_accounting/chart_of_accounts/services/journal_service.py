from __future__ import annotations
from typing import Optional, Dict, Any, Sequence, List
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.generate_code.service import generate_next_code
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import (
    Account, CostCenter, JournalEntry, JournalEntryItem, GeneralLedgerEntry,
    FiscalYear, FiscalYearStatusEnum, AccountTypeEnum, ReportTypeEnum, JournalEntryTypeEnum,
)
from app.application_accounting.engine.validators import (
    ensure_fiscal_year_open, ensure_accounts_exist, ensure_balanced
)
from app.application_accounting.engine.balance_updater import apply_balances
from app.application_accounting.chart_of_accounts.Repository.journal_repo import JournalRepo, PCVRepo
from app.business_validation.item_validation import BizValidationError

# ----------------------------- utils -----------------------------

def _sum_dr_cr(lines) -> (Decimal, Decimal):
    dr = sum(Decimal(str(x.debit or 0)) for x in lines)
    cr = sum(Decimal(str(x.credit or 0)) for x in lines)
    return dr, cr

def _assert_leaf_account(s: Session, company_id: int, account_id: int) -> None:
    acc = s.execute(
        select(Account).where(Account.company_id == company_id, Account.id == account_id, Account.enabled == True)  # noqa
    ).scalar_one_or_none()
    if not acc:
        raise BizValidationError("Account not found or disabled.")
    if acc.is_group:
        raise BizValidationError("Posting allowed only on detail accounts (not groups).")

def _validate_cc_if_any(s: Session, company_id: int, branch_id: int, cost_center_id: Optional[int]) -> None:
    if cost_center_id is None:
        return
    cc = s.execute(
        select(CostCenter).where(
            CostCenter.id == cost_center_id,
            CostCenter.company_id == company_id,
            CostCenter.branch_id == branch_id,
            CostCenter.enabled == True,  # noqa
        )
    ).scalar_one_or_none()
    if not cc:
        raise BizValidationError("Cost Center not found or disabled.")

def _normalize_date_in_company_fy(s: Session, company_id: int, posting_date: datetime) -> (int, datetime):
    fy_id = ensure_fiscal_year_open(s, company_id, posting_date)
    return fy_id, posting_date.date()

# ----------------------- Manual Journal Service -----------------------

class JournalEntryService:
    JE_PREFIX = "JE"

    def __init__(self, s: Session):
        self.s = s
        self.repo = JournalRepo(s)

    def _validate_lines(self, company_id: int, branch_id: int, lines) -> None:
        if not lines or len(lines) < 2:
            raise BizValidationError("At least two lines are required.")
        for ln in lines:
            _assert_leaf_account(self.s, company_id, ln.account_id)
            _validate_cc_if_any(self.s, company_id, branch_id, ln.cost_center_id)
            # party is optional here; add tighter rules if you tag AR/AP accounts

        # Sum and balance
        dr, cr = _sum_dr_cr(lines)
        ensure_balanced(dr, cr)

    def create(self, *, payload, ctx) -> JournalEntry:
        company_id = payload.company_id
        branch_id = payload.branch_id
        fy_id, post_date = _normalize_date_in_company_fy(self.s, company_id, payload.posting_date)

        self._validate_lines(company_id, branch_id, payload.items)

        total_dr, total_cr = _sum_dr_cr(payload.items)
        je = JournalEntry(
            company_id=company_id,
            branch_id=branch_id,
            fiscal_year_id=fy_id,
            created_by_id=ctx.user_id,
            source_doctype_id=None,
            source_doc_id=None,
            code=generate_next_code(session=self.s, prefix=self.JE_PREFIX, company_id=company_id, branch_id=branch_id),
            posting_date=post_date,
            doc_status=DocStatusEnum.DRAFT,
            remarks=payload.remarks,
            total_debit=total_dr,
            total_credit=total_cr,
            entry_type=payload.entry_type,
            is_auto_generated=False,
        )
        self.s.add(je)
        self.s.flush([je])

        # lines
        items = []
        for ln in payload.items:
            it = JournalEntryItem(
                journal_entry_id=je.id,
                account_id=ln.account_id,
                cost_center_id=ln.cost_center_id,
                party_id=ln.party_id,
                party_type=ln.party_type,
                debit=Decimal(str(ln.debit or 0)),
                credit=Decimal(str(ln.credit or 0)),
                remarks=ln.remarks,
            )
            items.append(it)
        ensure_accounts_exist(self.s, company_id, [i.account_id for i in items])

        self.s.add_all(items)
        self.s.flush(items + [je])
        return je

    def update(self, *, je_id: int, payload, ctx) -> JournalEntry:
        je = self.repo.get_je(je_id, ctx.company_ids, ctx.branch_ids)
        if not je:
            raise BizValidationError("Journal Entry not found.")
        if je.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Journal Entries can be updated.")

        if payload.posting_date is not None:
            fy_id, post_date = _normalize_date_in_company_fy(self.s, je.company_id, payload.posting_date)
            je.fiscal_year_id = fy_id
            je.posting_date = post_date

        if payload.entry_type is not None:
            je.entry_type = payload.entry_type
        if payload.remarks is not None:
            je.remarks = payload.remarks

        if payload.items is not None:
            self._validate_lines(je.company_id, je.branch_id, payload.items)
            # delete & replace items
            for old in list(je.items or []):
                self.s.delete(old)
            self.s.flush()

            total_dr, total_cr = _sum_dr_cr(payload.items)
            je.total_debit = total_dr
            je.total_credit = total_cr

            new_items = []
            for ln in payload.items:
                it = JournalEntryItem(
                    journal_entry_id=je.id,
                    account_id=ln.account_id,
                    cost_center_id=ln.cost_center_id,
                    party_id=ln.party_id,
                    party_type=ln.party_type,
                    debit=Decimal(str(ln.debit or 0)),
                    credit=Decimal(str(ln.credit or 0)),
                    remarks=ln.remarks,
                )
                new_items.append(it)
            ensure_accounts_exist(self.s, je.company_id, [i.account_id for i in new_items])
            self.s.add_all(new_items)

        self.s.flush([je])
        return je

    def submit(self, *, je_id: int, ctx) -> JournalEntry:
        je = self.repo.get_je(je_id, ctx.company_ids, ctx.branch_ids)
        if not je:
            raise BizValidationError("Journal Entry not found.")
        if je.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Journal Entries can be submitted.")

        # Re-validate against FY and totals
        fy_id, post_date = _normalize_date_in_company_fy(self.s, je.company_id, je.posting_date)
        je.fiscal_year_id = fy_id
        je.posting_date = post_date
        ensure_accounts_exist(self.s, je.company_id, [i.account_id for i in je.items])
        ensure_balanced(Decimal(str(je.total_debit or 0)), Decimal(str(je.total_credit or 0)))

        # Post immutable GLE
        for ln in je.items:
            gle = GeneralLedgerEntry(
                company_id=je.company_id,
                branch_id=je.branch_id,
                account_id=ln.account_id,
                cost_center_id=ln.cost_center_id,
                fiscal_year_id=fy_id,
                party_id=ln.party_id,
                party_type=ln.party_type,
                journal_entry_id=je.id,
                source_doctype_id=None,
                source_doc_id=None,
                posting_date=post_date,
                debit=Decimal(str(ln.debit or 0)),
                credit=Decimal(str(ln.credit or 0)),
                is_auto_generated=False,
                entry_type=str(je.entry_type.value if hasattr(je.entry_type, "value") else je.entry_type),
            )
            self.s.add(gle)
            apply_balances(
                self.s,
                account_id=gle.account_id,
                party_id=gle.party_id,
                party_type=gle.party_type,
                debit=gle.debit,
                credit=gle.credit,
            )

        je.doc_status = DocStatusEnum.SUBMITTED
        self.s.flush([je])
        return je

    def cancel(self, *, je_id: int, ctx, reason: Optional[str]) -> JournalEntry:
        original = self.repo.get_je(je_id, ctx.company_ids, ctx.branch_ids)
        if not original:
            raise BizValidationError("Journal Entry not found.")
        if original.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only Submitted Journal Entries can be cancelled.")

        # Create reversal JE on same date
        fy_id, post_date = _normalize_date_in_company_fy(self.s, original.company_id, original.posting_date)

        rev = JournalEntry(
            company_id=original.company_id,
            branch_id=original.branch_id,
            fiscal_year_id=fy_id,
            created_by_id=ctx.user_id,
            code=generate_next_code(session=self.s, prefix=self.JE_PREFIX, company_id=original.company_id, branch_id=original.branch_id),
            posting_date=post_date,
            doc_status=DocStatusEnum.SUBMITTED,
            remarks=f"Reversal of {original.code}" + (f" — {reason}" if reason else ""),
            total_debit=Decimal(str(original.total_credit or 0)),
            total_credit=Decimal(str(original.total_debit or 0)),
            entry_type=JournalEntryTypeEnum.AUTO,
            is_auto_generated=True,
            source_doctype_id=None,
            source_doc_id=original.id,
        )
        self.s.add(rev)
        self.s.flush([rev])

        for ol in list(original.items or []):
            debit = Decimal(str(ol.credit or 0))
            credit = Decimal(str(ol.debit or 0))
            rli = JournalEntryItem(
                journal_entry_id=rev.id,
                account_id=ol.account_id,
                cost_center_id=ol.cost_center_id,
                party_id=ol.party_id,
                party_type=ol.party_type,
                debit=debit,
                credit=credit,
                remarks=None,
            )
            self.s.add(rli)

            gle = GeneralLedgerEntry(
                company_id=original.company_id,
                branch_id=original.branch_id,
                account_id=ol.account_id,
                cost_center_id=ol.cost_center_id,
                fiscal_year_id=fy_id,
                party_id=ol.party_id,
                party_type=ol.party_type,
                journal_entry_id=rev.id,
                source_doctype_id=None,
                source_doc_id=original.id,
                posting_date=post_date,
                debit=debit,
                credit=credit,
                is_auto_generated=True,
                entry_type=str(rev.entry_type.value if hasattr(rev.entry_type, "value") else rev.entry_type),
            )
            self.s.add(gle)
            apply_balances(
                self.s,
                account_id=gle.account_id,
                party_id=gle.party_id,
                party_type=gle.party_type,
                debit=gle.debit,
                credit=gle.credit,
            )

        original.doc_status = DocStatusEnum.CANCELLED
        self.s.flush([rev, original])
        return original

# ------------------- Period Closing Voucher Service -------------------

class PeriodClosingVoucherService:
    PCV_PREFIX = "PCV"

    def __init__(self, s: Session):
        self.s = s
        self.repo = PCVRepo(s)

    def _fy_guard(self, fy: FiscalYear) -> None:
        if fy.status != FiscalYearStatusEnum.OPEN:
            raise BizValidationError("Fiscal Year is not open.")
        if fy.end_date <= fy.start_date:
            raise BizValidationError("Fiscal Year dates are invalid.")

    def create(self, *, payload, ctx):
        # verify FY
        fy = self.repo.fy_by_id(payload.closing_fiscal_year_id, ctx.company_ids)
        if not fy:
            raise BizValidationError("Closing Fiscal Year not found.")
        self._fy_guard(fy)

        posting_date = payload.posting_date.date() if payload.posting_date else fy.end_date.date()
        if not (fy.start_date.date() <= posting_date <= fy.end_date.date()):
            raise BizValidationError("Posting Date must be within the Closing Fiscal Year.")

        from app.application_accounting.chart_of_accounts.models import PeriodClosingVoucher
        pcv = PeriodClosingVoucher(
            company_id=payload.company_id,
            branch_id=payload.branch_id,
            closing_fiscal_year_id=fy.id,
            closing_account_head_id=payload.closing_account_head_id,
            generated_journal_entry_id=None,
            submitted_by_id=None,
            code=generate_next_code(session=self.s, prefix=self.PCV_PREFIX, company_id=payload.company_id, branch_id=payload.branch_id),
            posting_date=posting_date,
            doc_status=DocStatusEnum.DRAFT,
            remarks=payload.remarks,
            auto_prepared=False,
            submitted_at=None,
            total_profit_loss=Decimal("0.0000"),
        )
        self.s.add(pcv)
        self.s.flush([pcv])
        return pcv

    def update(self, *, pcv_id: int, payload, ctx):
        pcv = self.repo.get_pcv(pcv_id, ctx.company_ids, ctx.branch_ids)
        if not pcv:
            raise BizValidationError("Period Closing Voucher not found.")
        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Period Closing Vouchers can be updated.")

        fy = self.repo.fy_by_id(pcv.closing_fiscal_year_id, ctx.company_ids)
        self._fy_guard(fy)

        if payload.posting_date is not None:
            pd = payload.posting_date.date()
            if not (fy.start_date.date() <= pd <= fy.end_date.date()):
                raise BizValidationError("Posting Date must be within the Closing Fiscal Year.")
            pcv.posting_date = pd
        if payload.closing_account_head_id is not None:
            pcv.closing_account_head_id = payload.closing_account_head_id
        if payload.remarks is not None:
            pcv.remarks = payload.remarks

        self.s.flush([pcv])
        return pcv

    def _build_closing_lines(self, *, company_id: int, fy_id: int, posting_date, closing_account_id: int):
        """
        Build lines to zero all P&L accounts up to posting_date and push net into closing_account_id.
        """
        balances = self.repo.pl_account_balances(company_id=company_id, fiscal_year_id=fy_id, up_to_date=posting_date)
        lines: List[Dict[str, Any]] = []
        total_dr = Decimal("0")
        total_cr = Decimal("0")

        for account_id, sum_debit, sum_credit in balances:
            d = Decimal(str(sum_debit or 0))
            c = Decimal(str(sum_credit or 0))
            net = d - c  # debit positive means expense balance, credit positive means income balance
            if net == 0:
                continue
            if net > 0:
                # Expense (debit) balance -> credit to zero it
                lines.append(dict(account_id=account_id, debit=Decimal("0"), credit=net))
                total_cr += net
            else:
                # Income (credit) balance -> debit to zero it
                amt = abs(net)
                lines.append(dict(account_id=account_id, debit=amt, credit=Decimal("0")))
                total_dr += amt

        # Add balancing line to Retained Earnings
        if total_dr > total_cr:
            diff = total_dr - total_cr
            lines.append(dict(account_id=closing_account_id, debit=Decimal("0"), credit=diff))
            total_cr += diff
            net_pl = diff  # profit (credit to RE)
        elif total_cr > total_dr:
            diff = total_cr - total_dr
            lines.append(dict(account_id=closing_account_id, debit=diff, credit=Decimal("0")))
            total_dr += diff
            net_pl = -diff  # loss (debit to RE)
        else:
            net_pl = Decimal("0")

        ensure_balanced(total_dr, total_cr)
        return lines, net_pl, total_dr, total_cr

    def submit(self, *, pcv_id: int, ctx):
        pcv = self.repo.get_pcv(pcv_id, ctx.company_ids, ctx.branch_ids)
        if not pcv:
            raise BizValidationError("Period Closing Voucher not found.")
        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Period Closing Vouchers can be submitted.")

        fy = self.repo.fy_by_id(pcv.closing_fiscal_year_id, ctx.company_ids)
        self._fy_guard(fy)

        # make closing lines
        lines, net_pl, tdr, tcr = self._build_closing_lines(
            company_id=pcv.company_id,
            fy_id=fy.id,
            posting_date=pcv.posting_date,
            closing_account_id=pcv.closing_account_head_id,
        )

        # create auto Journal Entry
        je = JournalEntry(
            company_id=pcv.company_id,
            branch_id=pcv.branch_id,
            fiscal_year_id=fy.id,
            created_by_id=ctx.user_id,
            code=generate_next_code(session=self.s, prefix="JE", company_id=pcv.company_id, branch_id=pcv.branch_id),
            posting_date=pcv.posting_date,
            doc_status=DocStatusEnum.SUBMITTED,
            remarks=f"Year-end closing for FY {fy.name} via PCV {pcv.code}",
            total_debit=tdr,
            total_credit=tcr,
            entry_type="CLOSING",
            is_auto_generated=True,
            source_doctype_id=None,
            source_doc_id=pcv.id,
        )
        self.s.add(je)
        self.s.flush([je])

        # lines + GLE
        for ln in lines:
            item = JournalEntryItem(
                journal_entry_id=je.id,
                account_id=int(ln["account_id"]),
                cost_center_id=None,
                party_id=None,
                party_type=None,
                debit=Decimal(str(ln["debit"])),
                credit=Decimal(str(ln["credit"])),
                remarks=None,
            )
            self.s.add(item)

            gle = GeneralLedgerEntry(
                company_id=pcv.company_id,
                branch_id=pcv.branch_id,
                account_id=item.account_id,
                cost_center_id=None,
                fiscal_year_id=fy.id,
                party_id=None,
                party_type=None,
                journal_entry_id=je.id,
                source_doctype_id=None,
                source_doc_id=pcv.id,
                posting_date=pcv.posting_date,
                debit=item.debit,
                credit=item.credit,
                is_auto_generated=True,
                entry_type="CLOSING",
            )
            self.s.add(gle)
            apply_balances(self.s, account_id=item.account_id, party_id=None, party_type=None, debit=gle.debit, credit=gle.credit)

        # finalize PCV
        pcv.generated_journal_entry_id = je.id
        pcv.doc_status = DocStatusEnum.SUBMITTED
        pcv.submitted_by_id = ctx.user_id
        pcv.submitted_at = datetime.utcnow()
        pcv.total_profit_loss = net_pl

        self.s.flush([pcv, je])
        return pcv

    def cancel(self, *, pcv_id: int, ctx, reason: Optional[str]):
        pcv = self.repo.get_pcv(pcv_id, ctx.company_ids, ctx.branch_ids)
        if not pcv:
            raise BizValidationError("Period Closing Voucher not found.")
        if pcv.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only Submitted Period Closing Vouchers can be cancelled.")
        if not pcv.generated_journal_entry_id:
            raise BizValidationError("No generated Journal Entry to reverse.")

        # reverse the generated JE
        original = self.s.execute(
            select(JournalEntry).where(
                JournalEntry.id == pcv.generated_journal_entry_id,
                JournalEntry.company_id == pcv.company_id,
            )
        ).scalar_one_or_none()
        if not original:
            raise BizValidationError("Generated Journal Entry not found.")

        rev = JournalEntry(
            company_id=original.company_id,
            branch_id=original.branch_id,
            fiscal_year_id=original.fiscal_year_id,
            created_by_id=ctx.user_id,
            code=generate_next_code(session=self.s, prefix="JE", company_id=original.company_id, branch_id=original.branch_id),
            posting_date=original.posting_date,
            doc_status=DocStatusEnum.SUBMITTED,
            remarks=f"Reversal of {original.code} (PCV {pcv.code})" + (f" — {reason}" if reason else ""),
            total_debit=Decimal(str(original.total_credit or 0)),
            total_credit=Decimal(str(original.total_debit or 0)),
            entry_type="AUTO",
            is_auto_generated=True,
            source_doctype_id=None,
            source_doc_id=pcv.id,
        )
        self.s.add(rev)
        self.s.flush([rev])

        for ol in list(original.items or []):
            debit = Decimal(str(ol.credit or 0))
            credit = Decimal(str(ol.debit or 0))
            rli = JournalEntryItem(
                journal_entry_id=rev.id,
                account_id=ol.account_id,
                cost_center_id=ol.cost_center_id,
                party_id=None,
                party_type=None,
                debit=debit,
                credit=credit,
                remarks=None,
            )
            self.s.add(rli)

            gle = GeneralLedgerEntry(
                company_id=original.company_id,
                branch_id=original.branch_id,
                account_id=ol.account_id,
                cost_center_id=ol.cost_center_id,
                fiscal_year_id=original.fiscal_year_id,
                party_id=None,
                party_type=None,
                journal_entry_id=rev.id,
                source_doctype_id=None,
                source_doc_id=pcv.id,
                posting_date=original.posting_date,
                debit=debit,
                credit=credit,
                is_auto_generated=True,
                entry_type="AUTO",
            )
            self.s.add(gle)
            apply_balances(self.s, account_id=gle.account_id, party_id=None, party_type=None, debit=gle.debit, credit=gle.credit)

        # mark PCV cancelled (keep link to original JE)
        from app.application_stock.stock_models import DocStatusEnum as DS
        pcv.doc_status = DS.CANCELLED
        self.s.flush([pcv, rev])
        return pcv
