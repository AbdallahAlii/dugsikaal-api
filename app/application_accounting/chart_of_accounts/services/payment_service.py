from __future__ import annotations
import logging
from decimal import Decimal
from typing import Optional, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.generate_code.service import ensure_manual_code_is_next_and_bump, generate_next_code
from config.database import db

from app.application_stock.stock_models import DocumentType, DocStatusEnum
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.engine.errors import PostingValidationError
from app.application_accounting.engine.events import make_entry_type
from app.application_accounting.engine.locks import lock_doc
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_accounting.chart_of_accounts.finance_model import PaymentEntry, PaymentItem, PaymentTypeEnum
from app.application_accounting.chart_of_accounts.Repository.payment_repo import PaymentRepo
from app.application_accounting.chart_of_accounts.Repository.party_ledger_repo import PartyLedgerRepo
log = logging.getLogger(__name__)

class PaymentEntryService:
    PE_PREFIX = "PE"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PaymentRepo(self.s)
        self.ledger = PartyLedgerRepo(self.s)

    def _dtid(self, code: str) -> int:
        rid = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not rid:
            raise BizValidationError(f"DocumentType '{code}' not found.")
        return int(rid)

    def _get_validated(self, payment_id: int, context: AffiliationContext, for_update: bool = False) -> PaymentEntry:
        pe = self.repo.get(payment_id)
        if not pe:
            raise BizValidationError("Payment Entry not found.")
        ensure_scope_by_ids(context=context, target_company_id=pe.company_id, target_branch_id=pe.branch_id)
        if for_update:
            self.s.refresh(pe, with_for_update=True)
        return pe

    def _gen_code(self, company_id: int, branch_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            if self.repo.code_exists_pe(company_id, branch_id, code):
                raise BizValidationError("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PE_PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PE_PREFIX, company_id=company_id, branch_id=branch_id)

    # ------------------------------------------------------------------ CREATE

    def create(self, *, payload: Dict, context: AffiliationContext) -> PaymentEntry:
        company_id = int(payload["company_id"]); branch_id = int(payload["branch_id"])
        code = self._gen_code(company_id, branch_id, payload.get("code"))

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
        self.repo.add(pe)

        items = payload.get("items") or []
        if items:
            self.repo.add_items(pe.id, items)
            self.repo.recompute_allocations(pe.id)

        self.s.commit()
        return pe

    # -------------------------------------------------------------- UPDATE (Draft only)

    def update(self, *, payment_id: int, payload: Dict, context: AffiliationContext) -> PaymentEntry:
        pe = self._get_validated(payment_id, context, for_update=True)
        if pe.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only Draft Payment Entries can be updated.")
        if "code" in payload and payload["code"] and payload["code"] != pe.code:
            raise BizValidationError("Code cannot be changed after creation.")

        # Header
        # normalize party_type if provided
        if "party_type" in payload and payload["party_type"]:
            payload["party_type"] = PartyTypeEnum(payload["party_type"])
        if "payment_type" in payload and payload["payment_type"]:
            payload["payment_type"] = PaymentTypeEnum(payload["payment_type"])
        self.repo.update_header(pe, payload)

        # Items replace (if provided)
        if "items" in payload and payload["items"] is not None:
            self.repo.delete_items(pe.id)
            self.repo.add_items(pe.id, payload["items"])

        # Auto-allocate if asked
        auto_allocate = bool(payload.get("auto_allocate"))
        if auto_allocate:
            self._auto_allocate(pe)

        self.repo.recompute_allocations(pe.id)
        self.s.commit()
        return pe

    # -------------------------------------------------------------- SUBMISSION

    def submit(self, *, payment_id: int, context: AffiliationContext, auto_allocate: bool = False) -> PaymentEntry:
        pe = self._get_validated(payment_id, context, for_update=False)
        if pe.doc_status != DocStatusEnum.DRAFT:
            raise BizValidationError("Only draft Payment Entries can be submitted.")

        if pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
            if not pe.party_type or not pe.party_id:
                raise BizValidationError("Party is required for PAY/RECEIVE.")

        if auto_allocate and pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER:
            self._auto_allocate(pe)

        self.repo.recompute_allocations(pe.id)

        template_code, payload, dyn = self._compose_posting(pe)
        doctype_id = self._dtid("PAYMENT_ENTRY")

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, pe.company_id, doctype_id, pe.id):
                    pe_locked = self._get_validated(payment_id, context, for_update=True)
                    if pe_locked.doc_status != DocStatusEnum.DRAFT:
                        raise BizValidationError("Only draft Payment Entries can be submitted.")

                    ctx = PostingContext(
                        company_id=pe_locked.company_id,
                        branch_id=pe_locked.branch_id,
                        source_doctype_id=doctype_id,
                        source_doc_id=pe_locked.id,
                        posting_date=pe_locked.posting_date,
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

                    self._apply_explicit_allocations(pe_locked)
                    self.repo.mark_submitted(pe_locked.id)

            self.s.commit()
            return pe

        except PostingValidationError as e:
            self.s.rollback(); raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback(); log.exception("Failed to submit Payment Entry")
            raise BizValidationError("Failed to submit Payment Entry.")

    # --------------------------------------------------------------- CANCELLATION

    def cancel(self, *, payment_id: int, context: AffiliationContext, reason: Optional[str] = None) -> PaymentEntry:
        pe = self._get_validated(payment_id, context, for_update=True)
        if pe.doc_status != DocStatusEnum.SUBMITTED:
            raise BizValidationError("Only submitted Payment Entries can be cancelled.")

        doctype_id = self._dtid("PAYMENT_ENTRY")
        template_code, payload, dyn = self._compose_posting(pe, reverse=True)

        try:
            with self.s.begin_nested():
                with lock_doc(self.s, pe.company_id, doctype_id, pe.id):
                    ctx = PostingContext(
                        company_id=pe.company_id,
                        branch_id=pe.branch_id,
                        source_doctype_id=doctype_id,
                        source_doc_id=pe.id,
                        posting_date=pe.posting_date,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=make_entry_type(is_auto=True, for_reversal=True),
                        remarks=f"Cancel Payment Entry {pe.code}" + (f" — {reason}" if reason else ""),
                        template_code=template_code,
                        payload=payload,
                        runtime_accounts={},
                        party_id=pe.party_id if pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER else None,
                        party_type=pe.party_type if pe.payment_type != PaymentTypeEnum.INTERNAL_TRANSFER else None,
                        dynamic_account_context=dyn,
                    )
                    PostingService(self.s).post(ctx)

                    self._revert_allocations(pe)
                    self.repo.mark_cancelled(pe.id)

            self.s.commit()
            return pe

        except PostingValidationError as e:
            self.s.rollback(); raise BizValidationError(f"Accounting error: {e}")
        except Exception:
            self.s.rollback(); log.exception("Failed to cancel Payment Entry")
            raise BizValidationError("Failed to cancel Payment Entry.")

    # --------------------------------------------------------------- OUTSTANDING

    def get_outstanding(self, *, company_id: int, party_kind: str, party_id: int, **filters) -> List[Dict]:
        rows = self.ledger.get_outstanding_invoices(
            company_id=company_id, party_kind=party_kind, party_id=party_id, **filters
        )
        return rows

    # =================== internals ============================================

    def _compose_posting(self, pe: PaymentEntry, reverse: bool = False):
        if pe.payment_type == PaymentTypeEnum.RECEIVE:
            template_code = "PAYMENT_RECEIVE"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"amount_received": float(-amt if reverse else amt)}
            dyn = {
                "cash_bank_account_id": pe.paid_to_account_id,
                "party_ledger_account_id": pe.paid_from_account_id,
            }
        elif pe.payment_type == PaymentTypeEnum.PAY:
            template_code = "PAYMENT_PAY"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"amount_paid": float(-amt if reverse else amt)}
            dyn = {
                "party_ledger_account_id": pe.paid_to_account_id,
                "cash_bank_account_id": pe.paid_from_account_id,
            }
        else:
            template_code = "PAYMENT_INTERNAL_TRANSFER"
            amt = Decimal(pe.paid_amount or 0)
            payload = {"amount_paid": float(-amt if reverse else amt)}
            dyn = {
                "paid_from_account_id": pe.paid_from_account_id,
                "paid_to_account_id": pe.paid_to_account_id,
            }
        return template_code, payload, dyn

    def _apply_explicit_allocations(self, pe: PaymentEntry) -> None:
        # Only Customer/Supplier references are SI/PI; others are advances
        if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER:
            return
        pk = pe.party_type.value if pe.party_type else None
        if pk not in ("Customer", "Supplier"):
            return
        for ref in pe.items:
            amt = Decimal(ref.allocated_amount or 0)
            if amt <= 0: continue
            self.ledger.apply_allocation(
                party_kind=pk, invoice_id=int(ref.source_doc_id), amount=amt
            )

    def _revert_allocations(self, pe: PaymentEntry) -> None:
        if pe.payment_type == PaymentTypeEnum.INTERNAL_TRANSFER:
            return
        pk = pe.party_type.value if pe.party_type else None
        if pk not in ("Customer", "Supplier"):
            return
        for ref in pe.items:
            amt = Decimal(ref.allocated_amount or 0)
            if amt <= 0: continue
            self.ledger.apply_allocation(
                party_kind=pk, invoice_id=int(ref.source_doc_id), amount=-amt
            )

    def _auto_allocate(self, pe: PaymentEntry) -> None:
        # clear existing and try FIFO on SI/PI when applicable
        if pe.party_type and pe.party_type.value not in ("Customer", "Supplier"):
            # no referenced docs for the other party types → keep as advance
            self.repo.delete_items(pe.id)
            self.repo.recompute_allocations(pe.id)
            return

        self.repo.delete_items(pe.id)
        paid = Decimal(pe.paid_amount or 0)
        remaining = paid

        pk = pe.party_type.value if pe.party_type else None
        rows = self.get_outstanding(company_id=pe.company_id, party_kind=pk, party_id=pe.party_id)

        # ERPNext-like guardrails (only meaningful for Cust/Supp)
        if pe.payment_type == PaymentTypeEnum.RECEIVE and pk == "Supplier":
            has_negative = any(Decimal(r["outstanding_amount"]) < 0 for r in rows)
            if not has_negative:
                raise BizValidationError("Cannot Receive from Supplier without any negative outstanding invoice")
        if pe.payment_type == PaymentTypeEnum.PAY and pk == "Customer":
            has_negative = any(Decimal(r["outstanding_amount"]) < 0 for r in rows)
            if not has_negative:
                raise BizValidationError("Cannot Pay to Customer without any negative outstanding invoice")

        new_items: List[Dict] = []
        for r in rows:
            if remaining <= 0: break
            o = abs(Decimal(r["outstanding_amount"]))
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
