from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session

from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.application_accounting.engine.posting_service import PostingContext, PostingService
from app.application_accounting.engine.errors import PostingValidationError

# Optional: tiny DTOs if you like
@dataclass(frozen=True)
class Allocation:
    alloc_doctype_id: int
    alloc_doc_id: int
    amount: float


def resolve_default_customer_ar_account_id(s, company_id):
    pass


def resolve_default_supplier_ap_account_id(s, company_id):
    pass


def resolve_default_employee_advance_account_id(s, company_id):
    pass


def _resolve_counterparty_account_id(
    s: Session,
    *,
    company_id: int,
    party_type: PartyTypeEnum,
    party_id: int,
    counterparty_account_id: Optional[int],
) -> int:
    """
    If caller did not pass a counterparty_account_id, pick a sensible default
    based on party_type (Frappe-style control accounts).
    """
    if counterparty_account_id:
        return int(counterparty_account_id)

    if party_type == PartyTypeEnum.CUSTOMER:
        acc_id = resolve_default_customer_ar_account_id(s, company_id)
        if not acc_id:
            raise PostingValidationError("Missing default Accounts Receivable account for company.")
        return acc_id

    if party_type == PartyTypeEnum.SUPPLIER:
        acc_id = resolve_default_supplier_ap_account_id(s, company_id)
        if not acc_id:
            raise PostingValidationError("Missing default Accounts Payable account for company.")
        return acc_id

    if party_type == PartyTypeEnum.EMPLOYEE:
        acc_id = resolve_default_employee_advance_account_id(s, company_id)
        if not acc_id:
            raise PostingValidationError("Missing default Employee Advances account for company.")
        return acc_id

    # Other: must be provided by caller
    raise PostingValidationError(
        "counterparty_account_id is required when party_type is 'Other'."
    )


def _pick_template_code(direction: str) -> str:
    """
    Generic templates (recommended):
      PAYMENT_IN  → Dr Bank/Cash, Cr Counterparty
      PAYMENT_OUT → Dr Counterparty, Cr Bank/Cash
    """
    d = (direction or "").upper()
    if d == "IN":
        return "PAYMENT_IN"
    if d == "OUT":
        return "PAYMENT_OUT"
    raise PostingValidationError("direction must be 'IN' or 'OUT'.")


def post_payment_entry(
    s: Session,
    *,
    company_id: int,
    branch_id: int,
    party_type: PartyTypeEnum,
    party_id: int,
    direction: str,                 # "IN" or "OUT"
    amount: float,                  # positive
    posting_date: datetime,
    created_by_id: int,
    source_doctype_id: int,
    source_doc_id: int,
    cash_bank_account_id: int,
    counterparty_account_id: Optional[int] = None,
    remarks: Optional[str] = None,
    allocations: Optional[List[Allocation]] = None,
    write_off_account_id: Optional[int] = None,
    write_off_amount: float = 0.0,
) -> None:
    """
    Unified Payment Entry poster.
    - Uses generic templates PAYMENT_IN / PAYMENT_OUT.
    - Auto-resolves counterparty account for Customer/Supplier/Employee.
    - Allocations are optional (sub-ledger usage); GL totals come from 'amount' (+ write-off).
    """
    if amount is None or float(amount) <= 0:
        raise PostingValidationError("amount must be a positive number.")

    tmpl = _pick_template_code(direction)
    cpty_acc_id = _resolve_counterparty_account_id(
        s,
        company_id=company_id,
        party_type=party_type,
        party_id=party_id,
        counterparty_account_id=counterparty_account_id,
    )

    payload: Dict[str, Any] = {}
    if tmpl == "PAYMENT_IN":
        payload["amount_received"] = float(amount)
    else:  # PAYMENT_OUT
        payload["amount_paid"] = float(amount)

    # Optional write-off support (adds a 3rd line in templates if you model it)
    # You can compute signs inside PostingService/amount_sources if preferred.
    if write_off_amount and float(write_off_amount) > 0 and not write_off_account_id:
        raise PostingValidationError("write_off_account_id is required when write_off_amount > 0.")

    runtime_accounts = {
        "cash_bank_account_id": int(cash_bank_account_id),
        "counterparty_account_id": int(cpty_acc_id),
        # optionally pass a write-off account if you model it in templates
        "write_off_account_id": int(write_off_account_id) if write_off_account_id else None,
    }

    # Idempotent post keyed by (company, doctype, doc_id)
    ctx = PostingContext(
        company_id=company_id,
        branch_id=branch_id,
        source_doctype_id=source_doctype_id,
        source_doc_id=source_doc_id,
        posting_date=posting_date,
        created_by_id=created_by_id,
        is_auto_generated=True,
        remarks=remarks or f"Payment Entry {source_doc_id}",
        template_code=tmpl,
        payload={**payload, "write_off_amount": float(write_off_amount or 0.0)},
        runtime_accounts=runtime_accounts,
        party_id=party_id,
        party_type=party_type,
        extras={"allocations": [a.__dict__ for a in allocations] if allocations else []},
    )

    PostingService(s).post(ctx)


def cancel_payment_entry(
    s: Session,
    *,
    company_id: int,
    branch_id: int,
    party_type: PartyTypeEnum,
    party_id: int,
    posting_date: datetime,          # used for reversal JE date if you implement reversals
    created_by_id: int,
    source_doctype_id: int,
    source_doc_id: int,
    reason: Optional[str] = None,
) -> None:
    """
    Unified Payment cancellation (reversal/unpost).
    Assumes PostingService can unpost by (company_id, source_doctype_id, source_doc_id).
    """
    svc = PostingService(s)
    svc.cancel_by_source(
        company_id=company_id,
        branch_id=branch_id,
        source_doctype_id=source_doctype_id,
        source_doc_id=source_doc_id,
        cancelled_by_id=created_by_id,
        posting_date=posting_date,
        remarks=reason or f"Cancel Payment Entry {source_doc_id}",
        party_id=party_id,
        party_type=party_type,
    )
