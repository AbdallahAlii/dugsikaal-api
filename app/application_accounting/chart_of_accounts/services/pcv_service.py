# app/application_accounting/chart_of_accounts/services/pcv_service.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.application_accounting.handlers.period_closing import build_gl_context_for_period_closing
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import PeriodClosingVoucher, JournalEntryTypeEnum
from app.application_accounting.chart_of_accounts.Repository.pcv_repo import PCVRepository
from app.application_accounting.chart_of_accounts.schemas.pcv_schemas import PCVCreate, PCVUpdate
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.business_validation.pcv_validation import validate_pcv_create
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids, resolve_company_branch_and_scope
from app.business_validation.posting_date_validation import PostingDateValidator
from app.common.timezone.service import get_company_timezone
from app.application_stock.engine.posting_clock import resolve_posting_dt

ERR_MISSING_POSTING_DATE = "Posting Date is required."
ERR_CLOSING_ACCOUNT_TYPE = "Closing Account Head must be a ledger Equity/Liability account."
ERR_NO_BALANCES_TO_CLOSE = "No Income/Expense balances found for that Fiscal Year."
ERR_INVALID_PERIOD = "Posting Date must lie inside the Fiscal Year window."
# ERR_PERIOD_OVERLAP can now be unused or removed


def _fy_bounds_as_date(fy) -> tuple:
    """
    Safely coerce FiscalYear start/end to date objects even if the columns
    are stored as datetime in the DB.
    """
    start = fy.start_date
    end = fy.end_date

    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()

    return start, end


class PeriodClosingVoucherService:
    def __init__(self, s: Session):
        self.s = s
        self.repo = PCVRepository(s)

    # ------------------------------------------------------------------ Create
    def create(self, *, payload: PCVCreate, ctx: AffiliationContext) -> PeriodClosingVoucher:
        # 1) Business-level mandatory checks (fields only)
        validate_pcv_create(payload)

        # 2) Resolve company (company-level only) + enforce scope
        company_id, _ = resolve_company_branch_and_scope(
            context=ctx,
            payload_company_id=getattr(payload, "company_id", None),
            branch_id=None,
            get_branch_company_id=lambda _branch_id: None,
            require_branch=False,
        )

        if not payload.posting_date:
            # Defensive; validate_pcv_create already checks this
            raise BizValidationError(ERR_MISSING_POSTING_DATE)

        # 3) Fetch and validate Fiscal Year (belongs to company)
        fy = self.repo.get_fy(payload.closing_fiscal_year_id, company_id)
        if not fy:
            raise BizValidationError("Fiscal Year not found.")

        # 4) Normalize posting datetime with company timezone, µs bump, fiscal rules
        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s,
            payload.posting_date,
            company_id,
            created_at=None,
            treat_midnight_as_date=True,
        )

        # 5) Enforce that posting date lies inside the selected Fiscal Year
        posting_date_d = norm_dt.date()
        fy_start_d, fy_end_d = _fy_bounds_as_date(fy)
        if not (fy_start_d <= posting_date_d <= fy_end_d):
            raise BizValidationError(ERR_INVALID_PERIOD)

        # 6) Closing account must be Equity/Liability ledger
        if not self.repo.is_equity_or_liability_ledger(payload.closing_account_head_id, company_id):
            raise BizValidationError(ERR_CLOSING_ACCOUNT_TYPE)

        # 🔴 7) NO MORE "only one per FY" business check
        # if self.repo.already_closed_for_fy(...): raise Conflict(...)

        # 8) Generate/validate code (ERP-style)
        code = self.repo.generate_or_validate_code(company_id=company_id, manual=payload.code)

        # 9) Create PCV in DRAFT
        pcv = PeriodClosingVoucher(
            company_id=company_id,
            closing_fiscal_year_id=fy.id,
            closing_account_head_id=payload.closing_account_head_id,
            generated_journal_entry_id=None,
            submitted_by_id=None,
            code=code,
            posting_date=norm_dt,
            doc_status=DocStatusEnum.DRAFT,
            remarks=payload.remarks,
            auto_prepared=False,
            submitted_at=None,
            total_profit_loss=Decimal("0.0000"),
        )
        self.repo.save(pcv)
        self.s.commit()
        return pcv

    # ------------------------------------------------------------- Update (draft)
    def update(self, *, pcv_id: int, payload: PCVUpdate, ctx: AffiliationContext) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=True)
        if not pcv:
            raise NotFound("Period Closing Voucher not found.")

        # Scope: doc already has company_id
        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)

        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only draft Period Closing Vouchers can be updated.")

        # --- Resolve target Fiscal Year (current or new) ---
        target_fy_id = payload.closing_fiscal_year_id or pcv.closing_fiscal_year_id
        target_fy = self.repo.get_fy(target_fy_id, pcv.company_id)
        if not target_fy:
            raise BizValidationError("Fiscal Year not found.")

        # --- Determine candidate posting datetime (current or new) ---
        candidate_posting_dt = pcv.posting_date
        if payload.posting_date:
            candidate_posting_dt = PostingDateValidator.validate_standalone_document(
                self.s,
                payload.posting_date,
                pcv.company_id,
                created_at=pcv.created_at,
                treat_midnight_as_date=True,
            )

        # --- Ensure posting date lies within target FY window ---
        fy_start_d, fy_end_d = _fy_bounds_as_date(target_fy)
        if not (fy_start_d <= candidate_posting_dt.date() <= fy_end_d):
            raise BizValidationError(ERR_INVALID_PERIOD)

        # --- Apply changes ---

        # Fiscal Year
        if payload.closing_fiscal_year_id and payload.closing_fiscal_year_id != pcv.closing_fiscal_year_id:
            pcv.closing_fiscal_year_id = target_fy.id

        # Posting Date
        if payload.posting_date:
            pcv.posting_date = candidate_posting_dt

        # Closing Account
        if payload.closing_account_head_id:
            if not self.repo.is_equity_or_liability_ledger(payload.closing_account_head_id, pcv.company_id):
                raise BizValidationError(ERR_CLOSING_ACCOUNT_TYPE)
            pcv.closing_account_head_id = payload.closing_account_head_id

        # Remarks
        if payload.remarks is not None:
            pcv.remarks = payload.remarks

        self.repo.save(pcv)
        self.s.commit()
        return pcv


    # ------------------------------------------------------------------ Submit
    def submit(self, *, pcv_id: int, ctx: AffiliationContext) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=False)
        if not pcv:
            raise NotFound("Period Closing Voucher not found.")

        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)

        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only draft Period Closing Vouchers can be submitted.")

        fy = self.repo.get_fy(pcv.closing_fiscal_year_id, pcv.company_id)
        if not fy:
            raise BizValidationError("Fiscal Year not found.")

        # 1) Compute net P&L for that FY (Income - Expense)
        net = self.repo.compute_net_pl_for_fy(
            company_id=pcv.company_id,
            fiscal_year_id=fy.id,
        )
        if net == 0:
            raise BizValidationError(ERR_NO_BALANCES_TO_CLOSE)

        # 2) Resolve posting datetime (company timezone rules)
        tz = get_company_timezone(self.s, pcv.company_id)
        posting_dt = resolve_posting_dt(
            pcv.posting_date.date(),
            created_at=pcv.created_at,
            tz=tz,
            treat_midnight_as_date=True,
        )

        # 3) Determine accounts:
        re_acc_id = int(pcv.closing_account_head_id)
        pl_summary_id = self.repo.get_or_create_pl_summary_account(pcv.company_id)

        # net > 0 → profit; net < 0 → loss (store as positive)
        profit = net if net > 0 else Decimal("0")
        loss = -net if net < 0 else Decimal("0")

        # 4) Resolve branch for posting (no need to bother client)
        branch_id = self.repo.resolve_branch_id_for_company(
            company_id=pcv.company_id,
            ctx_branch_id=getattr(ctx, "branch_id", None),
        )

        # 5) Build GL payload using the handler (ERP-style)
        dt_id = self.repo.get_doctype_id("PERIOD_CLOSING_VOUCHER")
        payload = build_gl_context_for_period_closing(
            profit_amount=float(profit),
            loss_amount=float(loss),
        )

        pctx = PostingContext(
            company_id=pcv.company_id,
            branch_id=branch_id,
            source_doctype_id=dt_id,
            source_doc_id=pcv.id,
            posting_date=posting_dt,
            created_by_id=ctx.user_id,
            is_auto_generated=True,
            entry_type=JournalEntryTypeEnum.CLOSING,
            remarks=f"Period Closing {pcv.code}",
            template_code="PERIOD_CLOSING",
            payload=payload,
            dynamic_account_context={
                "retained_earnings_account_id": re_acc_id,
                "pl_summary_account_id": pl_summary_id,
            },
        )

        je = PostingService(self.s).post(pctx)

        # 6) Finalize PCV
        pcv_db = self.repo.get(pcv_id, for_update=True)
        pcv_db.generated_journal_entry_id = int(je.id)
        pcv_db.total_profit_loss = float(profit or -loss)  # positive for profit, negative for loss
        pcv_db.doc_status = DocStatusEnum.SUBMITTED
        pcv_db.submitted_by_id = ctx.user_id
        pcv_db.submitted_at = datetime.utcnow()
        self.repo.save(pcv_db)

        self.s.commit()
        return pcv_db

    # ------------------------------------------------------------------ Cancel
    def cancel(self, *, pcv_id: int, ctx: AffiliationContext, reason: str | None = None) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=False)
        if not pcv:
            raise NotFound("Period Closing Voucher not found.")

        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)

        if pcv.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only submitted Period Closing Vouchers can be cancelled.")

        dt_id = self.repo.get_doctype_id("PERIOD_CLOSING_VOUCHER")
        tz = get_company_timezone(self.s, pcv.company_id)
        posting_dt = resolve_posting_dt(
            pcv.posting_date.date(),
            created_at=pcv.created_at,
            tz=tz,
            treat_midnight_as_date=True,
        )

        branch_id = self.repo.resolve_branch_id_for_company(
            company_id=pcv.company_id,
            ctx_branch_id=getattr(ctx, "branch_id", None),
        )

        cancel_remarks = f"Cancel Period Closing {pcv.code}"
        if reason:
            cancel_remarks = f"{cancel_remarks} – {reason}"

        # Reverse all JEs linked to this PCV
        PostingService(self.s).cancel(
            PostingContext(
                company_id=pcv.company_id,
                branch_id=branch_id,
                source_doctype_id=dt_id,
                source_doc_id=pcv.id,
                posting_date=posting_dt,
                created_by_id=ctx.user_id,
                is_auto_generated=True,
                remarks=cancel_remarks,
            )
        )

        # Mark PCV as cancelled + clear financial link
        pcv_db = self.repo.get(pcv_id, for_update=True)
        pcv_db.doc_status = DocStatusEnum.CANCELLED
        pcv_db.generated_journal_entry_id = None
        pcv_db.total_profit_loss = 0.0
        self.repo.save(pcv_db)

        self.s.commit()
        return pcv_db
