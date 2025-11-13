# app/application_accounting/chart_of_accounts/services/pcv_service.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, BadRequest

from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import PeriodClosingVoucher
from app.application_accounting.chart_of_accounts.Repository.pcv_repo import PCVRepository
from app.application_accounting.chart_of_accounts.schemas.pcv_schemas import PCVCreate, PCVUpdate
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.business_validation.posting_date_validation import PostingDateValidator
from app.common.timezone.service import get_company_timezone
from app.application_stock.engine.posting_clock import resolve_posting_dt

ERR_MISSING_POSTING_DATE = "Posting Date is required."
ERR_CLOSING_ACCOUNT_TYPE = "Closing Account Head must be a ledger Equity/Liability account."
ERR_NO_BALANCES_TO_CLOSE = "No Income/Expense balances found for that Fiscal Year."
ERR_PERIOD_OVERLAP = "This Fiscal Year already has a submitted/returned PCV."
ERR_INVALID_PERIOD = "Posting Date must lie inside the Fiscal Year window."

class PeriodClosingVoucherService:
    def __init__(self, s: Session):
        self.s = s
        self.repo = PCVRepository(s)

    # Create
    def create(self, *, payload: PCVCreate, ctx: AffiliationContext) -> PeriodClosingVoucher:
        if not payload.posting_date:
            raise BadRequest(ERR_MISSING_POSTING_DATE)

        fy = self.repo.get_fy(payload.closing_fiscal_year_id, payload.company_id)
        if not fy:
            raise BadRequest("Fiscal Year not found.")
        if not (fy.start_date <= payload.posting_date <= fy.end_date):
            raise BadRequest(ERR_INVALID_PERIOD)

        ensure_scope_by_ids(context=ctx, target_company_id=payload.company_id, target_branch_id=None)

        if not self.repo.is_equity_or_liability_ledger(payload.closing_account_head_id, payload.company_id):
            raise BadRequest(ERR_CLOSING_ACCOUNT_TYPE)

        if self.repo.already_closed_for_fy(company_id=payload.company_id, fiscal_year_id=fy.id):
            raise Conflict(ERR_PERIOD_OVERLAP)

        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s, payload.posting_date, payload.company_id, created_at=None, treat_midnight_as_date=True
        )

        code = self.repo.generate_or_validate_code(company_id=payload.company_id, manual=payload.code)
        pcv = PeriodClosingVoucher(
            company_id=payload.company_id,
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

    # Update (draft only)
    def update(self, *, pcv_id: int, payload: PCVUpdate, ctx: AffiliationContext) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=True)
        if not pcv:
            raise NotFound("PCV not found.")
        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)
        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BadRequest("Only draft PCV can be updated.")

        fy = self.repo.get_fy(pcv.closing_fiscal_year_id, pcv.company_id)
        if not fy:
            raise BadRequest("Fiscal Year not found.")

        if payload.posting_date:
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s, payload.posting_date, pcv.company_id, created_at=pcv.created_at, treat_midnight_as_date=True
            )
            if not (fy.start_date <= norm_dt <= fy.end_date):
                raise BadRequest(ERR_INVALID_PERIOD)
            pcv.posting_date = norm_dt

        if payload.closing_account_head_id:
            if not self.repo.is_equity_or_liability_ledger(payload.closing_account_head_id, pcv.company_id):
                raise BadRequest(ERR_CLOSING_ACCOUNT_TYPE)
            pcv.closing_account_head_id = payload.closing_account_head_id

        if payload.remarks is not None:
            pcv.remarks = payload.remarks

        self.repo.save(pcv)
        self.s.commit()
        return pcv

    # Submit
    def submit(self, *, pcv_id: int, ctx: AffiliationContext) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=False)
        if not pcv:
            raise NotFound("PCV not found.")
        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)
        if pcv.doc_status != DocStatusEnum.DRAFT:
            raise BadRequest("Only draft PCV can be submitted.")

        fy = self.repo.get_fy(pcv.closing_fiscal_year_id, pcv.company_id)
        if not fy:
            raise BadRequest("Fiscal Year not found.")

        net = self.repo.compute_net_pl_for_fy(company_id=pcv.company_id, fiscal_year_id=fy.id)
        if net == 0:
            raise BadRequest(ERR_NO_BALANCES_TO_CLOSE)

        tz = get_company_timezone(self.s, pcv.company_id)
        posting_dt = resolve_posting_dt(pcv.posting_date.date(), created_at=pcv.created_at, tz=tz,
                                        treat_midnight_as_date=True)

        re_acc_id = int(pcv.closing_account_head_id)
        pl_summary_id = self.repo.get_or_create_pl_summary_account(pcv.company_id)

        profit, loss = (net, Decimal("0")) if net > 0 else (Decimal("0"), -net)

        # ✅ Resolve a branch for posting without asking the client
        branch_id = self.repo.resolve_branch_id_for_company(
            company_id=pcv.company_id,
            ctx_branch_id=getattr(ctx, "branch_id", None),
        )

        dt_id = self.repo.get_doctype_id("PERIOD_CLOSING_VOUCHER")
        pctx = PostingContext(
            company_id=pcv.company_id,
            branch_id=branch_id,
            source_doctype_id=dt_id,
            source_doc_id=pcv.id,
            posting_date=posting_dt,
            created_by_id=ctx.user_id,
            is_auto_generated=True,
            remarks=f"Period Closing {pcv.code}",
            template_code="PERIOD_CLOSING",
            payload={
                "PROFIT_AMOUNT": float(profit),
                "LOSS_AMOUNT": float(loss),
            },
            dynamic_account_context={
                "retained_earnings_account_id": re_acc_id,
                "pl_summary_account_id": pl_summary_id,
            },
        )

        je = PostingService(self.s).post(pctx)

        # finalize
        pcv_db = self.repo.get(pcv_id, for_update=True)
        pcv_db.generated_journal_entry_id = int(je.id)
        pcv_db.total_profit_loss = float(profit or -loss)
        pcv_db.doc_status = DocStatusEnum.SUBMITTED
        pcv_db.submitted_by_id = ctx.user_id
        pcv_db.submitted_at = datetime.utcnow()
        self.repo.save(pcv_db)

        self.s.commit()
        return pcv_db

    # Cancel
    def cancel(self, *, pcv_id: int, ctx: AffiliationContext, reason: str | None = None) -> PeriodClosingVoucher:
        pcv = self.repo.get(pcv_id, for_update=False)
        if not pcv:
            raise NotFound("PCV not found.")
        ensure_scope_by_ids(context=ctx, target_company_id=pcv.company_id, target_branch_id=None)
        if pcv.doc_status != DocStatusEnum.SUBMITTED:
            raise BadRequest("Only submitted PCV can be cancelled.")

        dt_id = self.repo.get_doctype_id("PERIOD_CLOSING_VOUCHER")
        tz = get_company_timezone(self.s, pcv.company_id)
        posting_dt = resolve_posting_dt(pcv.posting_date.date(), created_at=pcv.created_at, tz=tz,
                                        treat_midnight_as_date=True)

        branch_id = self.repo.resolve_branch_id_for_company(
            company_id=pcv.company_id,
            ctx_branch_id=getattr(ctx, "branch_id", None),
        )

        cancel_remarks = f"Cancel Period Closing {pcv.code}"
        if reason:
            cancel_remarks = f"{cancel_remarks} – {reason}"

        PostingService(self.s).cancel(PostingContext(
            company_id=pcv.company_id,
            branch_id=branch_id,
            source_doctype_id=dt_id,
            source_doc_id=pcv.id,
            posting_date=posting_dt,
            created_by_id=ctx.user_id,
            is_auto_generated=True,
            remarks=cancel_remarks,
        ))

        pcv_db = self.repo.get(pcv_id, for_update=True)
        pcv_db.doc_status = DocStatusEnum.CANCELLED
        self.repo.save(pcv_db)

        self.s.commit()
        return pcv_db
