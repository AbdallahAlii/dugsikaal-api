# app/application_accounting/chart_of_accounts/services/journal_service.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List, Sequence, Tuple
from datetime import datetime
from decimal import Decimal
from decimal import Decimal as Dec
from sqlalchemy import select, text

from sqlalchemy.orm import Session

from config.database import db
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import (
    Account,
    CostCenter,
    JournalEntry,
    JournalEntryItem,
    GeneralLedgerEntry,
    FiscalYear,
    FiscalYearStatusEnum,
    AccountTypeEnum,
    ReportTypeEnum,
    JournalEntryTypeEnum,
)
from app.application_accounting.engine.validators import (
    ensure_fiscal_year_open,
    ensure_accounts_exist,
)
from app.application_accounting.engine.balance_updater import apply_balances
from app.application_accounting.chart_of_accounts.Repository.journal_repo import (
    JournalRepo,
    PCVRepo,
)
from app.business_validation.item_validation import (
    BizValidationError,
    ERR_JE_MIN_LINES,
    ERR_JE_ACCOUNT_MANDATORY,
    ERR_JE_ZERO_DR_CR,
    ERR_JE_PARTY_REQUIRED,
    ERR_JE_SAME_ACCOUNT_DR_CR,
    ERR_JE_TOTAL_NOT_BALANCED,
)
from app.business_validation.posting_date_validation import PostingDateValidator
from app.application_stock.stock_models import DocStatusEnum as StockDocStatusEnum

logger = logging.getLogger(__name__)

# ----------------------------- utils -----------------------------


def _sum_dr_cr(lines) -> Tuple[Decimal, Decimal]:
    dr = sum(Decimal(str(x.debit or 0)) for x in lines)
    cr = sum(Decimal(str(x.credit or 0)) for x in lines)
    return dr, cr


def _normalize_date_in_company_fy(
    s: Session,
    company_id: int,
    posting_date: datetime,
    *,
    created_at: Optional[datetime] = None,
) -> Tuple[int, datetime]:
    """
    Normalize posting date like Sales Invoice (ERPNext-style):

    - Use PostingDateValidator to:
        * convert to company timezone,
        * clamp small future skew,
        * enforce open fiscal year + period closing,
        * enforce "too old" rule.
    - Then derive fiscal_year_id via ensure_fiscal_year_open.

    Returns:
        (fiscal_year_id, posting_date_as_date_only)
    """
    norm_dt = PostingDateValidator.validate_standalone_document(
        s,
        posting_date,
        company_id,
        created_at=created_at,
        treat_midnight_as_date=True,
    )
    fy_id = ensure_fiscal_year_open(s, company_id, norm_dt.date())
    return fy_id, norm_dt.date()


def _is_party_account(acc: Account) -> bool:
    """
    Heuristic to detect Receivable / Payable style accounts without
    needing AccountTypeEnum.RECEIVABLE / PAYABLE.

    ERP-style rules:
    - Must be Balance Sheet account.
    - Must be Asset or Liability.
    - Name or code suggests AR/AP (Receivable, Debtors, Payable, Creditors).
    """
    if acc.report_type != ReportTypeEnum.BALANCE_SHEET:
        return False

    if acc.account_type not in (AccountTypeEnum.ASSET, AccountTypeEnum.LIABILITY):
        return False

    name = (acc.name or "").lower()
    if any(
        key in name
        for key in ("receivable", "debtor", "debtors", "payable", "creditor", "creditors")
    ):
        return True

    code = (acc.code or "").strip()
    if code.startswith("113") or code.startswith("114") or code.startswith("21"):
        return True

    return False


# ----------------------- Manual Journal Service -----------------------

# ----------------------- Manual Journal Service -----------------------


class JournalEntryService:
    """Manual Journal Entry service with proper commits and logging."""

    JE_PREFIX = "JE"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = JournalRepo(self.s)

    # ---- helpers ----
    def _ensure_party_accessible(
        self,
        *,
        company_id: int,
        branch_id: int,
        party_type_label: str,
        party_id: int,
    ) -> None:
        """
        Copy of PaymentRepo.ensure_party_accessible logic,
        scoped inside JournalEntryService so JEs cannot use
        wrong / inactive / foreign parties.
        """
        # Raw, lightweight query (no Party ORM import)
        row = self.s.execute(
            text(
                "SELECT id, company_id, branch_id, role, status "
                "FROM parties WHERE id = :pid"
            ),
            {"pid": int(party_id)},
        ).first()

        # Nice labels for error messages
        if party_type_label in ("Customer", "Supplier"):
            label = party_type_label
        else:
            label = "Party"

        if not row:
            raise BizValidationError(f"{label} not found.")

        meta = {
            "id": int(row.id),
            "company_id": int(row.company_id),
            "branch_id": int(row.branch_id) if getattr(row, "branch_id", None) is not None else None,
            "role": str(row.role) if getattr(row, "role", None) is not None else None,
            "status": str(row.status) if getattr(row, "status", None) is not None else None,
        }

        # Role match (like PaymentRepo: only for Customer/Supplier)
        if party_type_label in ("Customer", "Supplier"):
            if (meta.get("role") or "").lower() != party_type_label.lower():
                # Role mismatch → treat as “not found” for this type
                raise BizValidationError(f"{label} not found.")

        # Company match
        if int(meta.get("company_id", -1)) != int(company_id):
            raise BizValidationError(f"{label} does not belong to this company.")

        # Branch match (only when party is bound to a branch)
        pb = meta.get("branch_id")
        if pb is not None and int(pb) != int(branch_id):
            raise BizValidationError(f"{label} does not belong to this branch.")

        # Status must be ACTIVE
        if (meta.get("status") or "").upper() != "ACTIVE":
            raise BizValidationError(f"{label} is inactive.")

    def _generate_or_validate_code(
        self,
        company_id: int,
        branch_id: int,
        manual: Optional[str],
    ) -> str:
        """Generate or validate journal entry code (like SalesService)."""
        logger.debug(
            "JE: _generate_or_validate_code company=%s branch=%s manual=%s",
            company_id,
            branch_id,
            manual,
        )
        if manual:
            code = manual.strip()
            if self.repo.code_exists_je(company_id, branch_id, code):
                raise BizValidationError("Journal Entry code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.JE_PREFIX,
                company_id=company_id,
                branch_id=branch_id,
                code=code,
            )
            logger.info("JE: using manual code=%s", code)
            return code

        auto_code = generate_next_code(
            prefix=self.JE_PREFIX,
            company_id=company_id,
            branch_id=branch_id,
        )
        logger.info("JE: generated auto code=%s", auto_code)
        return auto_code

    def _load_accounts_map(
        self, company_id: int, account_ids: Sequence[int]
    ) -> Dict[int, Account]:
        """Load enabled accounts for given IDs (guarded by company)."""
        if not account_ids:
            return {}

        logger.debug("JE: loading accounts for company=%s ids=%s", company_id, account_ids)
        rows = (
            self.s.execute(
                select(Account).where(
                    Account.company_id == company_id,
                    Account.id.in_(set(account_ids)),
                    Account.enabled == True,  # noqa
                )
            )
            .scalars()
            .all()
        )
        acc_map = {a.id: a for a in rows}
        logger.debug("JE: loaded %s accounts", len(acc_map))
        return acc_map

    def _validate_lines(
        self,
        company_id: int,
        branch_id: int,
        lines,
        entry_type: JournalEntryTypeEnum,
    ) -> None:
        """Validate journal entry lines ERPNext-style."""
        if not lines or len(lines) < 2:
            raise BizValidationError(ERR_JE_MIN_LINES)

        logger.debug(
            "JE: validating %s lines, company=%s, entry_type=%s",
            len(lines),
            company_id,
            entry_type,
        )

        account_ids = [ln.account_id for ln in lines if ln.account_id is not None]
        acc_map = self._load_accounts_map(company_id, account_ids)

        agg: Dict[tuple, Dict[str, Decimal]] = {}
        total_dr = Decimal("0")
        total_cr = Decimal("0")

        for idx, ln in enumerate(lines, start=1):
            if ln.account_id is None:
                raise BizValidationError(ERR_JE_ACCOUNT_MANDATORY.format(row=idx))

            acc = acc_map.get(ln.account_id)
            if not acc:
                raise BizValidationError("Account not found or disabled.")

            if acc.is_group:
                raise BizValidationError(
                    "Posting allowed only on detail accounts (not groups)."
                )

            d = Decimal(str(ln.debit or 0))
            c = Decimal(str(ln.credit or 0))

            if d == 0 and c == 0:
                raise BizValidationError(ERR_JE_ZERO_DR_CR.format(row=idx))
            if d < 0 or c < 0:
                raise BizValidationError("Debit/Credit cannot be negative.")

            # Party requirement for AR/AP-like accounts
            if _is_party_account(acc):
                if not ln.party_type or not ln.party_id:
                    raise BizValidationError(
                        ERR_JE_PARTY_REQUIRED.format(row=idx, account_name=acc.name)
                    )

            key = (ln.account_id, ln.party_type, ln.party_id)
            bucket = agg.setdefault(
                key,
                {"debit": Decimal("0"), "credit": Decimal("0")},
            )
            bucket["debit"] += d
            bucket["credit"] += c

            total_dr += d
            total_cr += c

        # Same account DR+CR rule for manual JEs
        if entry_type in (
            JournalEntryTypeEnum.GENERAL,
            JournalEntryTypeEnum.OPENING,
            JournalEntryTypeEnum.ADJUSTMENT,
        ):
            for (acc_id, party_type, party_id), sums in agg.items():
                if sums["debit"] > 0 and sums["credit"] > 0:
                    acc = acc_map.get(acc_id)
                    name = acc.name if acc else str(acc_id)
                    raise BizValidationError(
                        ERR_JE_SAME_ACCOUNT_DR_CR.format(account_name=name)
                    )

        if total_dr != total_cr:
            diff = total_dr - total_cr
            raise BizValidationError(ERR_JE_TOTAL_NOT_BALANCED.format(diff=str(diff)))

        logger.debug(
            "JE: line validation OK total_dr=%s total_cr=%s", total_dr, total_cr
        )

    # ---- public API ----

    def create(self, *, payload, ctx: AffiliationContext) -> JournalEntry:
        """Create a new Journal Entry with proper transaction + party validation."""
        logger.info("JE.create: start user_id=%s payload=%s", ctx.user_id, payload)
        try:
            # 1) Resolve company/branch with scope checks (like SalesService)
            company_id, branch_id = resolve_company_branch_and_scope(
                context=ctx,
                payload_company_id=payload.company_id,
                branch_id=payload.branch_id or getattr(ctx, "branch_id", None),
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )
            logger.debug(
                "JE.create: resolved company_id=%s branch_id=%s",
                company_id,
                branch_id,
            )

            # 2) Normalize posting date + fiscal year
            fy_id, post_date = _normalize_date_in_company_fy(
                self.s,
                company_id,
                payload.posting_date,
                created_at=None,
            )
            logger.debug(
                "JE.create: normalized posting_date=%s fiscal_year_id=%s",
                post_date,
                fy_id,
            )

            # 3) Validate lines (accounts, totals, AR/AP party *required* etc.)
            self._validate_lines(
                company_id=company_id,
                branch_id=branch_id,
                lines=payload.items,
                entry_type=payload.entry_type,
            )

            # 4) Party-level validation (existence, role, company, branch, active)
            for ln in payload.items:
                if getattr(ln, "party_type", None) and getattr(ln, "party_id", None):
                    # accept either Enum or plain string
                    pt_raw = ln.party_type
                    party_type_label = (
                        pt_raw.value if hasattr(pt_raw, "value") else str(pt_raw)
                    )
                    self._ensure_party_accessible(
                        company_id=company_id,
                        branch_id=branch_id,
                        party_type_label=party_type_label,
                        party_id=int(ln.party_id),
                    )

            # 5) Generate/validate code
            code = self._generate_or_validate_code(
                company_id=company_id,
                branch_id=branch_id,
                manual=getattr(payload, "code", None),
            )

            total_dr, total_cr = _sum_dr_cr(payload.items)
            logger.debug(
                "JE.create: totals DR=%s CR=%s code=%s", total_dr, total_cr, code
            )

            # 6) Build JE header
            je = JournalEntry(
                company_id=company_id,
                branch_id=branch_id,
                fiscal_year_id=fy_id,
                created_by_id=ctx.user_id,
                source_doctype_id=None,
                source_doc_id=None,
                code=code,
                posting_date=post_date,
                doc_status=DocStatusEnum.DRAFT,
                remarks=payload.remarks,
                total_debit=total_dr,
                total_credit=total_cr,
                entry_type=payload.entry_type,
                is_auto_generated=False,
            )
            self.s.add(je)
            self.s.flush([je])  # assign id
            logger.debug("JE.create: JE flushed with id=%s", je.id)

            # 7) Build JE lines
            items: List[JournalEntryItem] = []
            for idx, ln in enumerate(payload.items, start=1):
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
                logger.debug(
                    "JE.create: line %s acc=%s dr=%s cr=%s party_type=%s party_id=%s",
                    idx,
                    ln.account_id,
                    ln.debit,
                    ln.credit,
                    ln.party_type,
                    ln.party_id,
                )

            # 8) Extra defensive account check
            ensure_accounts_exist(
                self.s, company_id, [i.account_id for i in items]
            )

            self.s.add_all(items)
            self.s.flush(items + [je])

            # 9) Commit whole transaction
            self.s.commit()
            logger.info(
                "JE.create: committed id=%s code=%s total_dr=%s total_cr=%s",
                je.id,
                je.code,
                je.total_debit,
                je.total_credit,
            )
            return je

        except Exception as e:
            logger.exception("JE.create: error %s", e)
            self.s.rollback()
            raise

    def update(self, *, je_id: int, payload, ctx: AffiliationContext) -> JournalEntry:
        """Update a Draft Journal Entry, including party validation."""
        logger.info("JE.update: start je_id=%s user_id=%s", je_id, ctx.user_id)
        try:
            # 1) Load JE row (no ctx filters here)
            je = self.repo.get_je(je_id, for_update=True)
            if not je:
                raise BizValidationError("Journal Entry not found.")

            # 2) RBAC scope guard
            ensure_scope_by_ids(
                context=ctx,
                target_company_id=je.company_id,
                target_branch_id=je.branch_id,
            )

            # 3) Only Draft JE can be updated
            if je.doc_status != DocStatusEnum.DRAFT:
                raise BizValidationError("Only Draft Journal Entries can be updated.")

            # 4) Posting date change
            if payload.posting_date is not None:
                fy_id, post_date = _normalize_date_in_company_fy(
                    self.s,
                    je.company_id,
                    payload.posting_date,
                    created_at=je.created_at,
                )
                je.fiscal_year_id = fy_id
                je.posting_date = post_date

            if payload.entry_type is not None:
                je.entry_type = payload.entry_type
            if payload.remarks is not None:
                je.remarks = payload.remarks

            # 5) Items replacement (optional)
            if payload.items is not None:
                # a) validate lines (accounts, totals, AR/AP party required)
                self._validate_lines(
                    company_id=je.company_id,
                    branch_id=je.branch_id,
                    lines=payload.items,
                    entry_type=je.entry_type,
                )

                # b) party validation
                for ln in payload.items:
                    if getattr(ln, "party_type", None) and getattr(ln, "party_id", None):
                        pt_raw = ln.party_type
                        party_type_label = (
                            pt_raw.value if hasattr(pt_raw, "value") else str(pt_raw)
                        )
                        self._ensure_party_accessible(
                            company_id=je.company_id,
                            branch_id=je.branch_id,
                            party_type_label=party_type_label,
                            party_id=int(ln.party_id),
                        )

                # c) delete old items
                old_items = list(je.items or [])
                for old in old_items:
                    self.s.delete(old)
                logger.debug("JE.update: deleted %s old items", len(old_items))

                # d) recompute totals
                total_dr, total_cr = _sum_dr_cr(payload.items)
                je.total_debit = total_dr
                je.total_credit = total_cr

                # e) create new items
                new_items: List[JournalEntryItem] = []
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

                ensure_accounts_exist(
                    self.s, je.company_id, [i.account_id for i in new_items]
                )
                self.s.add_all(new_items)
                logger.debug("JE.update: added %s new items", len(new_items))

            # 6) Commit
            self.s.flush([je])
            self.s.commit()
            logger.info("JE.update: committed id=%s code=%s", je.id, je.code)
            return je

        except Exception as e:
            logger.exception("JE.update: error %s", e)
            self.s.rollback()
            raise


    def submit(self, *, je_id: int, ctx: AffiliationContext) -> JournalEntry:
        """Submit a Draft Journal Entry and create GLE rows (simple ERP-style)."""
        logger.info("JE.submit: start je_id=%s user_id=%s", je_id, ctx.user_id)
        try:
            # 1) Load JE (no scope filter here, same pattern as Sales)
            je = self.repo.get_je(je_id, for_update=True)
            if not je:
                raise BizValidationError("Journal Entry not found.")

            # 2) Enforce RBAC scope
            ensure_scope_by_ids(
                context=ctx,
                target_company_id=je.company_id,
                target_branch_id=je.branch_id,
            )

            # 3) Only Draft can be submitted
            if je.doc_status != DocStatusEnum.DRAFT:
                raise BizValidationError(
                    "Only Draft Journal Entries can be submitted."
                )

            # 4) Re-validate posting date & fiscal year (in case FY/period changed)
            fy_id, post_date = _normalize_date_in_company_fy(
                self.s,
                je.company_id,
                je.posting_date,
                created_at=je.created_at,
            )
            je.fiscal_year_id = fy_id
            je.posting_date = post_date

            # 5) Ensure accounts still exist / enabled
            ensure_accounts_exist(
                self.s,
                je.company_id,
                [i.account_id for i in je.items],
            )

            # 6) Defensive: totals still balanced
            dr = Decimal(str(je.total_debit or 0))
            cr = Decimal(str(je.total_credit or 0))
            if dr != cr:
                diff = dr - cr
                raise BizValidationError(
                    ERR_JE_TOTAL_NOT_BALANCED.format(diff=str(diff))
                )

            # 7) Create General Ledger Entries (immutable)
            gle_count = 0
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
                    entry_type=str(
                        je.entry_type.value
                        if hasattr(je.entry_type, "value")
                        else je.entry_type
                    ),
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
                gle_count += 1

            # 8) Mark JE as Submitted
            je.doc_status = DocStatusEnum.SUBMITTED
            self.s.flush([je])
            self.s.commit()
            logger.info(
                "JE.submit: committed id=%s code=%s gle_count=%s",
                je.id,
                je.code,
                gle_count,
            )
            return je

        except Exception as e:
            logger.exception("JE.submit: error %s", e)
            self.s.rollback()
            raise

    def cancel(
            self,
            *,
            je_id: int,
            ctx: AffiliationContext,
            reason: Optional[str],
    ) -> JournalEntry:
        """Cancel a Submitted JE by posting a reversal JE (ERP-style)."""
        logger.info(
            "JE.cancel: start je_id=%s user_id=%s reason=%s",
            je_id,
            ctx.user_id,
            reason,
        )
        try:
            # 1) Load original JE
            original = self.repo.get_je(je_id, for_update=True)
            if not original:
                raise BizValidationError("Journal Entry not found.")

            # 🚫 Don't allow cancelling auto-generated JEs here
            if original.is_auto_generated:
                raise BizValidationError(
                    "Auto-generated Journal Entries can only be cancelled through "
                    "their source document (Sales Invoice, Payment Entry, etc.)."
                )

            # 2) Scope guard
            ensure_scope_by_ids(
                context=ctx,
                target_company_id=original.company_id,
                target_branch_id=original.branch_id,
            )

            # 3) Only Submitted can be cancelled
            if original.doc_status != DocStatusEnum.SUBMITTED:
                raise BizValidationError(
                    "Only Submitted Journal Entries can be cancelled."
                )

            # 4) Normalize posting date again (FY rules, etc.)
            fy_id, post_date = _normalize_date_in_company_fy(
                self.s,
                original.company_id,
                original.posting_date,
                created_at=original.created_at,
            )

            # 5) Create reversal JE
            rev_code = self._generate_or_validate_code(
                company_id=original.company_id,
                branch_id=original.branch_id,
                manual=None,
            )

            rev = JournalEntry(
                company_id=original.company_id,
                branch_id=original.branch_id,
                fiscal_year_id=fy_id,
                created_by_id=ctx.user_id,
                code=rev_code,
                posting_date=post_date,
                doc_status=DocStatusEnum.SUBMITTED,
                remarks=(
                        f"Reversal of {original.code}"
                        + (f" — {reason}" if reason else "")
                ),
                total_debit=Decimal(str(original.total_credit or 0)),
                total_credit=Decimal(str(original.total_debit or 0)),
                entry_type=JournalEntryTypeEnum.AUTO,
                is_auto_generated=True,
                source_doctype_id=None,
                source_doc_id=original.id,
            )
            self.s.add(rev)
            self.s.flush([rev])

            # 6) Reverse line items + GL entries
            reversal_count = 0
            for ol in list(original.items or []):
                debit = Decimal(str(ol.credit or 0))
                credit = Decimal(str(ol.debit or 0))

                # reversal JE line
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

                # reversal GL entry
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
                    entry_type=str(JournalEntryTypeEnum.AUTO.value),
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
                reversal_count += 1

            # 7) Mark original as CANCELLED
            original.doc_status = DocStatusEnum.CANCELLED
            self.s.flush([rev, original])
            self.s.commit()
            logger.info(
                "JE.cancel: committed reversal id=%s for original id=%s lines=%s",
                rev.id,
                original.id,
                reversal_count,
            )
            return original

        except Exception as e:
            logger.exception("JE.cancel: error %s", e)
            self.s.rollback()
            raise

