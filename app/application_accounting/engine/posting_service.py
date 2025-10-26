# #
# # # # application_accounting/engine/posting_service.py
# #
#
# from __future__ import annotations
#
# from dataclasses import dataclass
# from datetime import datetime
# from decimal import Decimal
# from typing import Dict, Any, Optional, List
#
# from sqlalchemy.orm import Session
# from sqlalchemy import select
#
# from app.application_accounting.chart_of_accounts.models import (
#     PartyTypeEnum,
#     JournalEntry,
#     JournalEntryItem,
#     GeneralLedgerEntry,
# )
# from app.application_accounting.engine.amount_sources import compute_amounts
# from app.application_accounting.engine.balance_updater import apply_balances
# from app.application_accounting.engine.dynamic_accounts import resolve_account_id
# from app.application_accounting.engine.errors import PostingValidationError
# from app.application_accounting.engine.events import make_entry_type
# from app.application_accounting.engine.locks import lock_doc
# from app.application_accounting.engine.selectors import get_template_items
# from app.application_accounting.engine.template_resolver import pick_template
# from app.application_accounting.engine.validators import (
#     ensure_idempotent_absent,
#     ensure_fiscal_year_open,
#     ensure_accounts_exist,
#     ensure_balanced,
# )
# from app.common.generate_code.service import generate_next_code
# from app.application_stock.stock_models import DocStatusEnum
#
# # NEW: normalize to company tz + date-only for accounting
# from app.application_stock.engine.posting_clock import resolve_posting_dt
# from app.common.timezone.service import get_company_timezone
# from dataclasses import dataclass, field
#
# @dataclass
# class PostingContext:
#     company_id: int
#     branch_id: int
#     source_doctype_id: int
#     source_doc_id: int
#     posting_date: datetime  # may be date or datetime; we normalize to date in company TZ
#     created_by_id: int
#     is_auto_generated: bool = True
#     entry_type: Optional[str] = None
#     remarks: Optional[str] = None
#     template_code: Optional[str] = None
#     payload: Dict[str, Any] = None
#     runtime_accounts: Dict[str, int] = None
#     party_id: Optional[int] = None
#     party_type: Optional[PartyTypeEnum] = None
#  # 🌟 FIX: Use the imported lowercase 'field' 🌟
#     dynamic_account_context: Dict[str, Any] = field(default_factory=dict)
#
# def _as_accounting_date(dt_like, *, tz_hint):
#     """
#     Treat 'midnight datetimes' as date-only; always return a DATE in company tz.
#     """
#     return resolve_posting_dt(
#         dt_like,
#         tz=tz_hint,
#         treat_midnight_as_date=True,
#     ).date()
#
#
# class PostingService:
#     def __init__(self, session: Session):
#         self.s = session
#
#     def post(self, ctx: PostingContext) -> JournalEntry:
#         # Resolve company/system timezone once for this run
#         tz_hint = get_company_timezone(self.s, ctx.company_id)
#
#         with lock_doc(self.s, ctx.company_id, ctx.source_doctype_id, ctx.source_doc_id):
#             entry_type = ctx.entry_type or make_entry_type(is_auto=True, for_reversal=False)
#             ensure_idempotent_absent(
#                 self.s,
#                 company_id=ctx.company_id,
#                 source_doctype_id=ctx.source_doctype_id,
#                 source_doc_id=ctx.source_doc_id,
#                 entry_type=entry_type,
#             )
#
#             # Normalize to date-only in company TZ
#             post_date = _as_accounting_date(ctx.posting_date, tz_hint=tz_hint)
#
#             fiscal_year_id = ensure_fiscal_year_open(self.s, ctx.company_id, post_date)
#
#             template = pick_template(
#                 self.s,
#                 company_id=ctx.company_id,
#                 source_doctype_id=ctx.source_doctype_id,
#                 explicit_code=ctx.template_code,
#             )
#             items = get_template_items(self.s, template.id)
#
#             # amounts = compute_amounts(ctx.payload or {})
#             amounts = compute_amounts(ctx.payload or {})
#
#             # --- Overlay: allow explicit numeric amount sources from payload (e.g. RETURN_STOCK_VALUE)
#             if ctx.payload:
#                 for k, v in (ctx.payload or {}).items():
#                     # accept direct numeric overrides for known or ad-hoc amount sources
#                     if isinstance(v, (int, float, Decimal, str)):
#                         try:
#                             from decimal import Decimal as _D
#                             val = _D(str(v))
#                         except Exception:
#                             continue
#                         amounts[k] = val
#
#             je = JournalEntry(
#                 company_id=ctx.company_id,
#                 branch_id=ctx.branch_id,
#
#                 fiscal_year_id=fiscal_year_id,
#                 created_by_id=ctx.created_by_id,
#                 source_doctype_id=ctx.source_doctype_id,
#                 source_doc_id=ctx.source_doc_id,
#                 code=generate_next_code(
#                     session=self.s,
#                     prefix="JE",
#                     company_id=ctx.company_id,
#                     branch_id=ctx.branch_id,
#                 ),
#                 posting_date=post_date,  # DATE-ONLY
#                 doc_status=DocStatusEnum.SUBMITTED,
#                 remarks=ctx.remarks,
#                 total_debit=0,
#                 total_credit=0,
#                 entry_type=entry_type,
#                 is_auto_generated=bool(ctx.is_auto_generated),
#             )
#             self.s.add(je)
#             self.s.flush([je])
#
#             total_dr = Decimal("0")
#             total_cr = Decimal("0")
#             line_objs: List[JournalEntryItem] = []
#
#             for tl in items:
#                 amount = Decimal(str(amounts.get(tl.amount_source, 0)))
#                 if amount == 0 and not tl.is_required:
#                     continue
#
#                 account_id = resolve_account_id(
#                     self.s,
#                     company_id=ctx.company_id,
#                     static_account_code=getattr(tl.account, "code", None) if tl.account_id else None,
#                     requires_dynamic_account=tl.requires_dynamic_account,
#                     context_key=tl.context_key,
#                     # runtime_context=(ctx.runtime_accounts or {}),
#                     runtime_context=(ctx.dynamic_account_context or {}),
#                 )
#
#                 if tl.effect.value.upper().startswith("D"):
#                     debit, credit = amount, Decimal("0")
#                     total_dr += amount
#                 else:
#                     debit, credit = Decimal("0"), amount
#                     total_cr += amount
#
#                 jei = JournalEntryItem(
#                     journal_entry_id=je.id,
#                     account_id=account_id,
#                     cost_center_id=None,
#                     party_id=ctx.party_id if tl.requires_dynamic_account else None,
#                     party_type=ctx.party_type if tl.requires_dynamic_account else None,
#                     debit=debit,
#                     credit=credit,
#                     remarks=None,
#                 )
#                 line_objs.append(jei)
#
#             ensure_accounts_exist(self.s, ctx.company_id, [ln.account_id for ln in line_objs])
#             ensure_balanced(total_dr, total_cr)
#
#             je.total_debit = total_dr
#             je.total_credit = total_cr
#             self.s.add_all(line_objs)
#             self.s.flush(line_objs + [je])
#
#             for ln in line_objs:
#                 gle = GeneralLedgerEntry(
#                     company_id=ctx.company_id,
#                     branch_id=ctx.branch_id,
#                     account_id=ln.account_id,
#                     cost_center_id=ln.cost_center_id,
#                     fiscal_year_id=fiscal_year_id,
#                     party_id=ln.party_id,
#                     party_type=ln.party_type,
#                     journal_entry_id=je.id,
#                     source_doctype_id=ctx.source_doctype_id,
#                     source_doc_id=ctx.source_doc_id,
#                     posting_date=post_date,  # DATE-ONLY
#                     debit=ln.debit,
#                     credit=ln.credit,
#                     is_auto_generated=je.is_auto_generated,
#                     entry_type=je.entry_type,
#                 )
#                 self.s.add(gle)
#                 apply_balances(
#                     self.s,
#                     account_id=gle.account_id,
#                     party_id=gle.party_id,
#                     party_type=gle.party_type,
#                     debit=gle.debit,
#                     credit=gle.credit,
#                 )
#
#             self.s.flush()
#             return je
#
#     def cancel(self, ctx: PostingContext) -> JournalEntry:
#         # Resolve company/system timezone once for this run
#         tz_hint = get_company_timezone(self.s, ctx.company_id)
#
#         with lock_doc(self.s, ctx.company_id, ctx.source_doctype_id, ctx.source_doc_id):
#             original: JournalEntry | None = self.s.execute(
#                 select(JournalEntry).where(
#                     JournalEntry.company_id == ctx.company_id,
#                     JournalEntry.source_doctype_id == ctx.source_doctype_id,
#                     JournalEntry.source_doc_id == ctx.source_doc_id,
#                     JournalEntry.is_auto_generated == True,   # noqa
#                     JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
#                 ).order_by(JournalEntry.id.desc()).limit(1)
#             ).scalar_one_or_none()
#             if not original:
#                 raise PostingValidationError("No submitted auto journal found to cancel.")
#
#             # Reverse on the original accounting DATE (no policy toggle)
#             rev_date = _as_accounting_date(original.posting_date, tz_hint=tz_hint)
#
#             fiscal_year_id = ensure_fiscal_year_open(self.s, ctx.company_id, rev_date)
#
#             rev = JournalEntry(
#                 company_id=ctx.company_id,
#                 branch_id=ctx.branch_id,
#                 fiscal_year_id=fiscal_year_id,
#                 created_by_id=ctx.created_by_id,
#                 source_doctype_id=ctx.source_doctype_id,
#                 source_doc_id=ctx.source_doc_id,
#                 code=generate_next_code(
#                     session=self.s,
#                     prefix="JE",
#                     company_id=ctx.company_id,
#                     branch_id=ctx.branch_id,
#                 ),
#                 posting_date=rev_date,  # DATE-ONLY (original date)
#                 doc_status=DocStatusEnum.SUBMITTED,
#                 remarks=f"Reversal of JE {original.code}",
#                 total_debit=original.total_credit,
#                 total_credit=original.total_debit,
#                 entry_type=make_entry_type(is_auto=True, for_reversal=True),
#                 is_auto_generated=True,
#             )
#             self.s.add(rev)
#             self.s.flush([rev])
#
#             orig_lines = list(original.items or [])
#             for ol in orig_lines:
#                 debit = Decimal(str(ol.credit or 0))
#                 credit = Decimal(str(ol.debit or 0))
#
#                 rli = JournalEntryItem(
#                     journal_entry_id=rev.id,
#                     account_id=ol.account_id,
#                     cost_center_id=ol.cost_center_id,
#                     party_id=ol.party_id,
#                     party_type=ol.party_type,
#                     debit=debit,
#                     credit=credit,
#                     remarks=None,
#                 )
#                 self.s.add(rli)
#
#                 gle = GeneralLedgerEntry(
#                     company_id=ctx.company_id,
#                     branch_id=ctx.branch_id,
#                     account_id=ol.account_id,
#                     cost_center_id=ol.cost_center_id,
#                     party_id=ol.party_id,
#                     party_type=ol.party_type,
#                     journal_entry_id=rev.id,
#                     source_doctype_id=ctx.source_doctype_id,
#                     source_doc_id=ctx.source_doc_id,
#                     posting_date=rev_date,  # DATE-ONLY (original date)
#                     debit=debit,
#                     credit=credit,
#                     is_auto_generated=True,
#                     entry_type=rev.entry_type,
#                 )
#                 self.s.add(gle)
#                 apply_balances(
#                     self.s,
#                     account_id=gle.account_id,
#                     party_id=gle.party_id,
#                     party_type=gle.party_type,
#                     debit=gle.debit,
#                     credit=gle.credit,
#                 )
#
#             self.s.flush()
#             return rev
# app/application_accounting/engine/posting_service.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.application_accounting.chart_of_accounts.models import (
    PartyTypeEnum,
    JournalEntry,
    JournalEntryItem,
    GeneralLedgerEntry,
)
from app.application_accounting.engine.amount_sources import compute_amounts
from app.application_accounting.engine.balance_updater import apply_balances
from app.application_accounting.engine.dynamic_accounts import resolve_account_id
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.engine.events import make_entry_type
from app.application_accounting.engine.locks import lock_doc
from app.application_accounting.engine.selectors import get_template_items
from app.application_accounting.engine.template_resolver import pick_template
from app.application_accounting.engine.validators import (
    ensure_idempotent_absent,
    ensure_fiscal_year_open,
    ensure_accounts_exist,
    ensure_balanced,
)
from app.common.generate_code.service import generate_next_code
from app.application_stock.stock_models import DocStatusEnum

# normalize to company tz + date-only for accounting
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.common.timezone.service import get_company_timezone


@dataclass
class PostingContext:
    company_id: int
    branch_id: int
    source_doctype_id: int
    source_doc_id: int
    posting_date: datetime
    created_by_id: int
    is_auto_generated: bool = True
    entry_type: Optional[str] = None
    remarks: Optional[str] = None
    template_code: Optional[str] = None
    payload: Dict[str, Any] = None
    runtime_accounts: Dict[str, int] = None  # kept for backward compat (unused)
    party_id: Optional[int] = None
    party_type: Optional[PartyTypeEnum] = None
    # Use this to pass dynamic accounts like accounts_receivable_account_id, cash_bank_account_id, etc.
    dynamic_account_context: Dict[str, Any] = field(default_factory=dict)


def _as_accounting_date(dt_like, *, tz_hint):
    """Treat 'midnight datetimes' as date-only; always return a DATE in company TZ."""
    return resolve_posting_dt(dt_like, tz=tz_hint, treat_midnight_as_date=True).date()


class PostingService:
    def __init__(self, session: Session):
        self.s = session

    def post(self, ctx: PostingContext) -> JournalEntry:
        tz_hint = get_company_timezone(self.s, ctx.company_id)

        with lock_doc(self.s, ctx.company_id, ctx.source_doctype_id, ctx.source_doc_id):
            entry_type = ctx.entry_type or make_entry_type(is_auto=True, for_reversal=False)
            ensure_idempotent_absent(
                self.s,
                company_id=ctx.company_id,
                source_doctype_id=ctx.source_doctype_id,
                source_doc_id=ctx.source_doc_id,
                entry_type=entry_type,
            )

            # Normalize to DATE in company TZ
            post_date = _as_accounting_date(ctx.posting_date, tz_hint=tz_hint)
            fiscal_year_id = ensure_fiscal_year_open(self.s, ctx.company_id, post_date)

            template = pick_template(
                self.s,
                company_id=ctx.company_id,
                source_doctype_id=ctx.source_doctype_id,
                explicit_code=ctx.template_code,
            )
            template_lines = get_template_items(self.s, template.id)

            # Compute amount buckets from payload once
            payload: Dict[str, Any] = ctx.payload or {}
            amounts: Dict[str, Decimal] = compute_amounts(payload)

            # Allow direct numeric overrides present in payload
            for k, v in list(payload.items()):
                if isinstance(v, (int, float, Decimal, str)):
                    try:
                        amounts[k] = Decimal(str(v))
                    except Exception:
                        pass

            # ---------- Prepare income splits (robust) ----------
            income_splits: Dict[int, Decimal] = {}
            # Prefer explicit splits if provided
            raw_splits = payload.get("income_splits") or {}
            for k, v in raw_splits.items():
                try:
                    aid = int(k)
                    income_splits[aid] = income_splits.get(aid, Decimal("0")) + Decimal(str(v or 0))
                except Exception:
                    continue

            # If not provided, derive from payload["lines"]
            if not income_splits and isinstance(payload.get("lines"), list):
                for ln in payload["lines"]:
                    try:
                        aid = int(ln.get("income_account_id")) if ln.get("income_account_id") is not None else None
                        amt = Decimal(str(ln.get("amount", 0)))
                        if aid:
                            income_splits[aid] = income_splits.get(aid, Decimal("0")) + amt
                    except Exception:
                        continue

            # Single-income shortcut (for templates that want one dynamic 'income_account_id')
            single_income_id: Optional[int] = None
            if isinstance(payload.get("lines"), list):
                distinct = {int(ln["income_account_id"]) for ln in payload["lines"] if ln.get("income_account_id") is not None}
                if len(distinct) == 1:
                    single_income_id = next(iter(distinct))

            # ---------- Create Journal Entry ----------
            je = JournalEntry(
                company_id=ctx.company_id,
                branch_id=ctx.branch_id,
                fiscal_year_id=fiscal_year_id,
                created_by_id=ctx.created_by_id,
                source_doctype_id=ctx.source_doctype_id,
                source_doc_id=ctx.source_doc_id,
                code=generate_next_code(
                    session=self.s, prefix="JE",
                    company_id=ctx.company_id, branch_id=ctx.branch_id,
                ),
                posting_date=post_date,  # DATE-ONLY
                doc_status=DocStatusEnum.SUBMITTED,
                remarks=ctx.remarks,
                total_debit=0,
                total_credit=0,
                entry_type=entry_type,
                is_auto_generated=bool(ctx.is_auto_generated),
            )
            self.s.add(je)
            self.s.flush([je])

            total_dr = Decimal("0")
            total_cr = Decimal("0")
            line_objs: List[JournalEntryItem] = []

            def _append_line(account_id: int, amount: Decimal, effect: str, party_ok: bool):
                nonlocal total_dr, total_cr, line_objs
                if amount == 0:
                    return
                if effect.upper().startswith("D"):
                    debit, credit = amount, Decimal("0")
                    total_dr += amount
                else:
                    debit, credit = Decimal("0"), amount
                    total_cr += amount
                line_objs.append(JournalEntryItem(
                    journal_entry_id=je.id,
                    account_id=int(account_id),
                    cost_center_id=None,
                    party_id=ctx.party_id if party_ok else None,
                    party_type=ctx.party_type if party_ok else None,
                    debit=debit,
                    credit=credit,
                    remarks=None,
                ))

            # ---------- Walk template lines ----------
            for tl in template_lines:
                context_key = (tl.context_key or "").strip() if getattr(tl, "context_key", None) else ""

                # SPECIAL: Any line that asks for 'income_account_id'
                if tl.requires_dynamic_account and context_key == "income_account_id":
                    if income_splits:
                        # explode: one line per income account
                        for acc_id, amt in income_splits.items():
                            _append_line(acc_id, Decimal(str(amt)), tl.effect.value, party_ok=False)
                        continue
                    # If there is exactly one income account on the document, use it
                    if single_income_id and "income_account_id" not in (ctx.dynamic_account_context or {}):
                        amt = Decimal(str(amounts.get(tl.amount_source, 0)))
                        if amt == 0 and not tl.is_required:
                            continue
                        _append_line(single_income_id, amt, tl.effect.value, party_ok=False)
                        continue
                    # Else: fall through to normal dynamic resolution (maybe caller provided it)

                # Normal path
                amt = Decimal(str(amounts.get(tl.amount_source, 0)))
                if amt == 0 and not tl.is_required:
                    continue

                account_id = resolve_account_id(
                    self.s,
                    company_id=ctx.company_id,
                    static_account_code=getattr(tl.account, "code", None) if tl.account_id else None,
                    requires_dynamic_account=tl.requires_dynamic_account,
                    context_key=context_key,
                    runtime_context=(ctx.dynamic_account_context or {}),
                )
                _append_line(account_id, amt, tl.effect.value, party_ok=tl.requires_dynamic_account)

            ensure_accounts_exist(self.s, ctx.company_id, [ln.account_id for ln in line_objs])
            ensure_balanced(total_dr, total_cr)

            je.total_debit = total_dr
            je.total_credit = total_cr
            self.s.add_all(line_objs)
            self.s.flush(line_objs + [je])

            # GLE + balances
            for ln in line_objs:
                gle = GeneralLedgerEntry(
                    company_id=ctx.company_id,
                    branch_id=ctx.branch_id,
                    account_id=ln.account_id,
                    cost_center_id=ln.cost_center_id,
                    fiscal_year_id=fiscal_year_id,
                    party_id=ln.party_id,
                    party_type=ln.party_type,
                    journal_entry_id=je.id,
                    source_doctype_id=ctx.source_doctype_id,
                    source_doc_id=ctx.source_doc_id,
                    posting_date=post_date,  # DATE-ONLY
                    debit=ln.debit,
                    credit=ln.credit,
                    is_auto_generated=je.is_auto_generated,
                    entry_type=je.entry_type,
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

            self.s.flush()
            return je

    def cancel(self, ctx: PostingContext) -> JournalEntry:
        tz_hint = get_company_timezone(self.s, ctx.company_id)

        with lock_doc(self.s, ctx.company_id, ctx.source_doctype_id, ctx.source_doc_id):
            original: JournalEntry | None = self.s.execute(
                select(JournalEntry).where(
                    JournalEntry.company_id == ctx.company_id,
                    JournalEntry.source_doctype_id == ctx.source_doctype_id,
                    JournalEntry.source_doc_id == ctx.source_doc_id,
                    JournalEntry.is_auto_generated == True,   # noqa
                    JournalEntry.doc_status == DocStatusEnum.SUBMITTED,
                ).order_by(JournalEntry.id.desc()).limit(1)
            ).scalar_one_or_none()
            if not original:
                raise PostingValidationError("No submitted auto journal found to cancel.")

            # Reverse on the original accounting DATE
            rev_date = _as_accounting_date(original.posting_date, tz_hint=tz_hint)
            fiscal_year_id = ensure_fiscal_year_open(self.s, ctx.company_id, rev_date)

            rev = JournalEntry(
                company_id=ctx.company_id,
                branch_id=ctx.branch_id,
                fiscal_year_id=fiscal_year_id,
                created_by_id=ctx.created_by_id,
                source_doctype_id=ctx.source_doctype_id,
                source_doc_id=ctx.source_doc_id,
                code=generate_next_code(
                    session=self.s, prefix="JE",
                    company_id=ctx.company_id, branch_id=ctx.branch_id,
                ),
                posting_date=rev_date,  # DATE-ONLY
                doc_status=DocStatusEnum.SUBMITTED,
                remarks=f"Reversal of JE {original.code}",
                total_debit=original.total_credit,
                total_credit=original.total_debit,
                entry_type=make_entry_type(is_auto=True, for_reversal=True),
                is_auto_generated=True,
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
                    company_id=ctx.company_id,
                    branch_id=ctx.branch_id,
                    account_id=ol.account_id,
                    cost_center_id=ol.cost_center_id,
                    party_id=ol.party_id,
                    party_type=ol.party_type,
                    journal_entry_id=rev.id,
                    source_doctype_id=ctx.source_doctype_id,
                    source_doc_id=ctx.source_doc_id,
                    posting_date=rev_date,  # DATE-ONLY
                    debit=debit,
                    credit=credit,
                    is_auto_generated=True,
                    entry_type=rev.entry_type,
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

            self.s.flush()
            return rev
