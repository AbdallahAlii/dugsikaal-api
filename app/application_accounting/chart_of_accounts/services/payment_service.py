
# app/application_accounting/chart_of_accounts/service/payment_entry_service.py
from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.application_reports.hook.invalidation import invalidate_financial_reports_for_company
from app.common.cache.cache_invalidator import bump_list_cache_company, bump_accounting_detail, bump_coa_balance_company
from config.database import db
from app.common.generate_code.service import ensure_manual_code_is_next_and_bump, generate_next_code
from app.application_stock.stock_models import DocumentType, DocStatusEnum
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.engine.events import make_entry_type
from app.application_accounting.engine.locks import lock_doc
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.application_accounting.chart_of_accounts.finance_model import PaymentEntry, PaymentItem, PaymentTypeEnum
from app.application_accounting.chart_of_accounts.Repository.payment_repo import PaymentRepo
from app.application_accounting.chart_of_accounts.Repository.party_ledger_repo import PartyLedgerRepo
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.common.timezone.service import get_company_timezone
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.business_validation.posting_date_validation import PostingDateValidator

log = logging.getLogger(__name__)

class PaymentEntryService:
    PE_PREFIX = "PAY"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PaymentRepo(self.s)
        self.ledger = PartyLedgerRepo(self.s)

    # ------------------------ utilities ------------------------

    def _dtid(self, code: str) -> int:
        rid = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not rid:
            raise BizValidationError(f"DocumentType '{code}' not found.")
        return int(rid)

    def _gen_code(self, company_id: int, branch_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            if self.repo.code_exists_pe(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PE_PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PE_PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_allocation_rows(
        self, *, company_id: int, party_kind: Optional[str], party_id: Optional[int],
        rows: List[Dict], paid_amount: Decimal, direction: str
    ) -> None:
        if not rows:
            return

        total_alloc = sum(Decimal(str(r.get("allocated_amount") or 0)) for r in rows)
        if total_alloc > paid_amount:
            raise BizValidationError("Allocated amount cannot exceed Paid amount.")

        if not party_kind or not party_id:
            raise BizValidationError("Select a Party and Party Type.")

        # Targeted fetch (fast)
        doc_ids = [
            int(r.get("source_doc_id") or 0)
            for r in rows
            if int(r.get("source_doc_id") or 0) > 0
        ]
        by_id = self.ledger.get_outstanding_by_ids(
            company_id=company_id,
            party_kind=party_kind,   # "Customer" or "Supplier"
            party_id=party_id,
            doc_ids=doc_ids,
        )

        for r in rows:
            doc_id = int(r.get("source_doc_id") or 0)
            if doc_id <= 0 or doc_id not in by_id:
                raise BizValidationError("Select a valid outstanding invoice for this party.")
            out_amt = Decimal(str(by_id[doc_id]["outstanding_amount"]))
            alloc = Decimal(str(r.get("allocated_amount") or 0))
            if alloc <= 0:
                raise BizValidationError("Allocated amount must be greater than zero.")
            if abs(alloc) > abs(out_amt):
                raise BizValidationError("Allocated amount cannot exceed invoice outstanding.")
            if direction == "IN" and out_amt == Decimal("0"):
                raise BizValidationError("Nothing outstanding on the selected invoice.")
            if direction == "OUT" and out_amt == Decimal("0"):
                raise BizValidationError("Nothing outstanding on the selected bill.")

    def _compose_posting(self, pe: PaymentEntry, reverse: bool = False):
        if pe.payment_type == PaymentTypeEnum.RECEIVE:
            template_code = "PAYMENT_RECEIVE"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"AMOUNT_RECEIVED": float(-amt if reverse else amt)}
            dyn = {
                "cash_bank_account_id": pe.paid_to_account_id,     # DR
                "party_ledger_account_id": pe.paid_from_account_id # CR (A/R)
            }
        elif pe.payment_type == PaymentTypeEnum.PAY:
            template_code = "PAYMENT_PAY"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"AMOUNT_PAID": float(-amt if reverse else amt)}
            dyn = {
                "party_ledger_account_id": pe.paid_to_account_id,  # DR (A/P)
                "cash_bank_account_id": pe.paid_from_account_id    # CR
            }
        else:
            template_code = "PAYMENT_INTERNAL_TRANSFER"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"AMOUNT_PAID": float(-amt if reverse else amt)}
            dyn = {
                "paid_from_account_id": pe.paid_from_account_id,
                "paid_to_account_id": pe.paid_to_account_id,
            }
        return template_code, payload, dyn

    def _get_validated(self, payment_id: int, context: AffiliationContext, for_update: bool = False) -> PaymentEntry:
        pe = self.repo.get(payment_id)
        if not pe:
            raise BizValidationError("Payment Entry not found.")
        ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)
        if for_update:
            self.s.refresh(pe, with_for_update=True)
        return pe

    # ----------------------------- CREATE --------------------------------
    def create(self, *, payload: Dict, context: AffiliationContext) -> PaymentEntry:
        # FIX: Get company_id from payload or fall back to context
        company_id = payload.get("company_id")
        if company_id is None:
            if not context.company_id:
                raise BizValidationError(
                    "Company is required. Please provide company_id or ensure user has a company affiliation.")
            company_id = context.company_id
        else:
            company_id = int(company_id)

        # FIX: Get branch_id from payload or fall back to context
        branch_id = payload.get("branch_id")
        if branch_id is None:
            if not context.branch_id:
                raise BizValidationError(
                    "Branch is required. Please provide branch_id or ensure user has a branch affiliation.")
            branch_id = context.branch_id
        else:
            branch_id = int(branch_id)

        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        code = self._gen_code(company_id, branch_id, payload.get("code"))

        if payload["paid_from_account_id"] == payload["paid_to_account_id"]:
            raise BizValidationError("From and To accounts must be different.")

        _ = PostingDateValidator.validate_standalone_document(
            self.s, payload["posting_date"], company_id, created_at=None, treat_midnight_as_date=True
        )

        ptype = payload.get("party_type")
        pid = payload.get("party_id")
        if ptype and pid:
            try:
                ptype_label = PartyTypeEnum(ptype).value if isinstance(ptype, str) else ptype.value
                self.repo.ensure_party_accessible(
                    company_id=company_id, branch_id=branch_id,
                    party_type_label=ptype_label, party_id=int(pid)
                )
            except ValueError as ex:
                raise BizValidationError(str(ex))

        self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=[payload["paid_from_account_id"]])
        self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=[payload["paid_to_account_id"]])

        pe = PaymentEntry(
            company_id=company_id, branch_id=branch_id, code=code,
            payment_type=PaymentTypeEnum(payload["payment_type"]),
            posting_date=payload["posting_date"],
            mode_of_payment_id=payload.get("mode_of_payment_id"),
            party_type=PartyTypeEnum(payload["party_type"]) if payload.get("party_type") else None,
            party_id=payload.get("party_id"),
            paid_from_account_id=payload["paid_from_account_id"],
            paid_to_account_id=payload["paid_to_account_id"],
            paid_amount=Decimal(str(payload["paid_amount"])),
            remarks=payload.get("remarks"),
            created_by_id=context.user_id,
            doc_status=DocStatusEnum.DRAFT,
        )

        try:
            self.repo.add(pe)
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Could not save Payment Entry due to invalid references.")

        items = payload.get("items") or []
        direction = "IN" if pe.payment_type == PaymentTypeEnum.RECEIVE else (
            "OUT" if pe.payment_type == PaymentTypeEnum.PAY else "X")
        if items and pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
            self._validate_allocation_rows(
                company_id=company_id,
                party_kind=pe.party_type.value if pe.party_type else None,
                party_id=pe.party_id,
                rows=items,
                paid_amount=pe.paid_amount,
                direction=direction,
            )
        if items:
            self.repo.add_items(pe.id, items)
        self.repo.recompute_allocations(pe.id)

        # Optional: allow create-time auto-allocate when requested
        if bool(payload.get("auto_allocate")) and pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
            if pe.party_type and pe.party_id and Decimal(pe.paid_amount or 0) > 0:
                self._auto_allocate(pe)
                self.repo.recompute_allocations(pe.id)

        self.s.commit()
        return pe

    # ----------------------------- UPDATE (Draft only) -------------------

    def update(self, *, payment_id: int, payload: Dict, context: AffiliationContext) -> PaymentEntry:
        pe = self._get_validated(payment_id, context, for_update=True)
        if pe.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Payment Entries can be updated.")
        if "code" in payload and payload["code"] and payload["code"] != pe.code:
            raise BizValidationError("Code cannot be changed after creation.")

        # FIX: Handle company_id/branch_id with fallbacks
        company_id = payload.get("company_id", pe.company_id)
        branch_id = payload.get("branch_id", pe.branch_id)

        # Convert to int if provided
        if isinstance(company_id, str):
            company_id = int(company_id)
        if isinstance(branch_id, str):
            branch_id = int(branch_id)

        # Ensure scope if company/branch changed
        if company_id != pe.company_id or branch_id != pe.branch_id:
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        if "party_type" in payload and payload["party_type"]:
            payload["party_type"] = PartyTypeEnum(payload["party_type"])
        if "payment_type" in payload and payload["payment_type"]:
            payload["payment_type"] = PaymentTypeEnum(payload["payment_type"])

        pt = payload.get("payment_type", pe.payment_type)
        if pt in (PaymentTypeEnum.PAY, PaymentTypeEnum.RECEIVE):
            if "mode_of_payment_id" in payload and not payload["mode_of_payment_id"]:
                raise BizValidationError("Payment method is required.")

        pfa = payload.get("paid_from_account_id", pe.paid_from_account_id)
        pta = payload.get("paid_to_account_id", pe.paid_to_account_id)
        if pfa and pta and pfa == pta:
            raise BizValidationError("From and To accounts must be different.")

        if "posting_date" in payload and payload["posting_date"]:
            _ = PostingDateValidator.validate_standalone_document(
                self.s, payload["posting_date"], company_id, created_at=pe.created_at, treat_midnight_as_date=True
            )

        if payload.get("party_type") or payload.get("party_id"):
            ptype = (payload.get("party_type") or pe.party_type)
            pid = (payload.get("party_id") or pe.party_id)
            if ptype and pid:
                try:
                    ptype_label = ptype.value if not isinstance(ptype, str) else ptype
                    self.repo.ensure_party_accessible(
                        company_id=company_id, branch_id=branch_id,
                        party_type_label=ptype_label, party_id=int(pid)
                    )
                except ValueError as ex:
                    raise BizValidationError(str(ex))

        if "paid_from_account_id" in payload and payload["paid_from_account_id"]:
            self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=[payload["paid_from_account_id"]])

        if "paid_to_account_id" in payload and payload["paid_to_account_id"]:
            self.repo.ensure_accounts_accessible(company_id=company_id, account_ids=[payload["paid_to_account_id"]])

        # Update the payload with determined company_id/branch_id
        update_payload = payload.copy()
        if company_id != pe.company_id:
            update_payload["company_id"] = company_id
        if branch_id != pe.branch_id:
            update_payload["branch_id"] = branch_id

        self.repo.update_header(pe, update_payload)

        if "items" in payload and payload["items"] is not None:
            items = payload["items"] or []
            if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER and items:
                raise BizValidationError("Internal transfers cannot reference invoices.")
            direction = "IN" if pe.payment_type == PaymentTypeEnum.RECEIVE else (
                "OUT" if pe.payment_type == PaymentTypeEnum.PAY else "X")
            if items and pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
                self._validate_allocation_rows(
                    company_id=company_id,
                    party_kind=pe.party_type.value if pe.party_type else None,
                    party_id=pe.party_id,
                    rows=items,
                    paid_amount=Decimal(pe.paid_amount or 0),
                    direction=direction,
                )
            self.repo.delete_items(pe.id)
            if items:
                self.repo.add_items(pe.id, items)

        auto_allocate = bool(payload.get("auto_allocate"))
        if auto_allocate:
            self._auto_allocate(pe)

        self.repo.recompute_allocations(pe.id)
        self.s.commit()
        return pe


    # ----------------------------- SUBMIT --------------------------------

    def submit(self, *, payment_id: int, context: AffiliationContext, auto_allocate: bool = False) -> PaymentEntry:
        pe = self._get_validated(payment_id, context, for_update=False)
        if pe.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Payment Entries can be submitted.")

        # Party requirement for PAY/RECEIVE (advance allowed but with a party)
        if pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
            if not pe.party_type or not pe.party_id:
                raise BizValidationError("Select a Party and Party Type.")

        tz = get_company_timezone(self.s, pe.company_id)
        posting_dt = resolve_posting_dt(pe.posting_date, created_at=pe.created_at, tz=tz, treat_midnight_as_date=True)
        doctype_id = self._dtid("PAYMENT_ENTRY")

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, pe.company_id, doctype_id, pe.id):
                    pe_locked = self._get_validated(payment_id, context, for_update=True)
                    if pe_locked.doc_status != DocStatusEnum.DRAFT:
                        raise BizValidationError("Only Draft Payment Entries can be submitted.")

                    # Default auto-allocate when there are no items & paid_amount > 0
                    default_auto = (
                        pe_locked.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER
                        and (not pe_locked.items or len(pe_locked.items) == 0)
                        and Decimal(pe_locked.paid_amount or 0) > 0
                    )
                    if auto_allocate or default_auto:
                        self._auto_allocate(pe_locked)
                        self.repo.recompute_allocations(pe_locked.id)

                    template_code, payload, dyn = self._compose_posting(pe_locked, reverse=False)

                    ctx = PostingContext(
                        company_id=pe_locked.company_id,
                        branch_id=pe_locked.branch_id,
                        source_doctype_id=doctype_id,
                        source_doc_id=pe_locked.id,
                        posting_date=posting_dt,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=make_entry_type(is_auto=True),
                        remarks=f"Payment Entry {pe_locked.code}",
                        template_code=template_code,
                        payload=payload,
                        runtime_accounts={},
                        party_id=pe_locked.party_id if pe_locked.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER else None,
                        party_type=pe_locked.party_type if pe_locked.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER else None,
                        dynamic_account_context=dyn,
                    )
                    PostingService(self.s).post(ctx)

                    # IMPORTANT: read refs from DB (not relationship) to avoid stale cache
                    self._apply_explicit_allocations(pe_locked)

                    self.repo.mark_submitted(pe_locked.id)

            self.s.commit()

            # 🔥 Invalidate financial reports ONLY (payments never affect stock)
            try:
                invalidate_financial_reports_for_company(pe.company_id)
                # Optional cache bumps for UI
                bump_list_cache_company("accounting", "payment_entries", pe.company_id)
                bump_accounting_detail("payment_entries", pe.id)
                bump_coa_balance_company(pe.company_id)
            except Exception:
                log.warning("Post-commit cache invalidation failed for payment %s", pe.id, exc_info=True)

            return pe

        except PostingValidationError as e:
            self.s.rollback(); raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback(); log.exception("Failed to submit Payment Entry")
            raise BizValidationError("Failed to submit Payment Entry.")

    # ----------------------------- CANCEL --------------------------------

    def cancel(
            self,
            *,
            payment_id: int,
            context: AffiliationContext,
            reason: Optional[str] = None,
    ) -> PaymentEntry:
        # First fetch for quick validation + scope
        pe = self._get_validated(payment_id, context, for_update=False)
        if pe.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only submitted Payment Entries can be cancelled.")

        doctype_id = self._dtid("PAYMENT_ENTRY")

        tz = get_company_timezone(self.s, pe.company_id)
        posting_dt = resolve_posting_dt(
            pe.posting_date,
            created_at=pe.created_at,
            tz=tz,
            treat_midnight_as_date=True,
        )

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, pe.company_id, doctype_id, pe.id):
                    pe_locked = self._get_validated(payment_id, context, for_update=True)
                    if pe_locked.doc_status != DocStatusEnum.SUBMITTED:
                        raise BizValidationError(
                            "Only submitted Payment Entries can be cancelled."
                        )

                    # 🔄 Reverse the original auto-generated JE for this Payment Entry
                    ctx_cancel = PostingContext(
                        company_id=pe_locked.company_id,
                        branch_id=pe_locked.branch_id,
                        source_doctype_id=doctype_id,
                        source_doc_id=pe_locked.id,
                        # Required by dataclass; PostingService.cancel uses the
                        # original JE accounting date internally.
                        posting_date=posting_dt,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        remarks=(
                                f"Cancel Payment Entry {pe_locked.code}"
                                + (f" — {reason}" if reason else "")
                        ),
                    )
                    PostingService(self.s).cancel(ctx_cancel)

                    # 🔁 Revert allocations (Sales Invoices / Purchase Invoices)
                    self._revert_allocations(pe_locked)

                    # Mark header as CANCELLED
                    self.repo.mark_cancelled(pe_locked.id)

            self.s.commit()

            # 🔥 Invalidate after commit
            try:
                invalidate_financial_reports_for_company(pe.company_id)
                bump_list_cache_company("accounting", "payment_entries", pe.company_id)
                bump_accounting_detail("payment_entries", pe.id)
                bump_coa_balance_company(pe.company_id)
            except Exception:
                log.warning(
                    "Post-commit cache invalidation failed for cancel payment %s",
                    pe.id,
                    exc_info=True,
                )

            return pe

        except PostingValidationError as e:
            self.s.rollback()
            raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback()
            log.exception("Failed to cancel Payment Entry")
            raise BizValidationError("Failed to cancel Payment Entry.")

    # ----------------------------- OUTSTANDING ---------------------------

    def get_outstanding(self, *, company_id: int, party_kind: str, party_id: int, **filters) -> List[Dict]:
        return self.ledger.get_outstanding_invoices(
            company_id=company_id, party_kind=party_kind, party_id=party_id, **filters
        )

    # ========================= allocation helpers =======================

    def _apply_explicit_allocations(self, pe: PaymentEntry) -> None:
        """
        Apply allocations by querying PaymentItem rows directly (avoids stale relationships).
        """
        if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER:
            return
        pk = pe.party_type.value if pe.party_type else None
        if pk not in ("Customer", "Supplier"):
            return

        rows = self.s.execute(
            select(PaymentItem.source_doc_id, PaymentItem.allocated_amount)
            .where(PaymentItem.payment_id == pe.id)
        ).all()

        for doc_id, amt in rows:
            amt = Decimal(str(amt or 0))
            if amt <= 0:
                continue
            self.ledger.apply_allocation(party_kind=pk, invoice_id=int(doc_id), amount=amt)

        self.s.flush()

    def _revert_allocations(self, pe: PaymentEntry) -> None:
        if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER:
            return
        pk = pe.party_type.value if pe.party_type else None
        if pk not in ("Customer", "Supplier"):
            return
        rows = self.s.execute(
            select(PaymentItem.source_doc_id, PaymentItem.allocated_amount)
            .where(PaymentItem.payment_id == pe.id)
        ).all()
        for doc_id, amt in rows:
            amt = Decimal(str(amt or 0))
            if amt <= 0:
                continue
            self.ledger.apply_allocation(party_kind=pk, invoice_id=int(doc_id), amount=-amt)
        self.s.flush()

    def _auto_allocate(self, pe: PaymentEntry) -> None:
        if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER:
            self.repo.delete_items(pe.id)
            self.repo.recompute_allocations(pe.id)
            return
        if not pe.party_type or not pe.party_id:
            raise BizValidationError("Select a Party and Party Type.")

        self.repo.delete_items(pe.id)
        paid = Decimal(pe.paid_amount or 0)
        remaining = paid

        pk = pe.party_type.value if pe.party_type else None
        rows = self.get_outstanding(company_id=pe.company_id, party_kind=pk, party_id=pe.party_id)

        if pe.payment_type == PaymentTypeEnum.RECEIVE and pk == "Supplier":
            has_negative = any(Decimal(r["outstanding_amount"]) < 0 for r in rows)
            if not has_negative:
                raise BizValidationError("Cannot Receive from Supplier without any negative outstanding bill.")
        if pe.payment_type == PaymentTypeEnum.PAY and pk == "Customer":
            has_negative = any(Decimal(r["outstanding_amount"]) < 0 for r in rows)
            if not has_negative:
                raise BizValidationError("Cannot Pay to Customer without any negative outstanding invoice.")

        new_items: List[Dict] = []
        for r in rows:
            if remaining <= 0:
                break
            o = abs(Decimal(r["outstanding_amount"]))
            if o <= 0:
                continue
            take = min(remaining, o)
            new_items.append(dict(
                source_doctype_id=None,
                source_doc_id=int(r["doc_id"]),
                allocated_amount=float(take),
            ))
            remaining -= take

        if new_items:
            self.repo.add_items(pe.id, new_items)
        self.repo.recompute_allocations(pe.id)
