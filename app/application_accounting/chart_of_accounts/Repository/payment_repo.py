
from __future__ import annotations
from typing import Optional, Iterable, List, Tuple, Dict, Sequence
from decimal import Decimal

from sqlalchemy import select, update, func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.database import db
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.chart_of_accounts.models import Account  # model kept as-is

# Keep imports aligned with your package layout
from app.application_accounting.chart_of_accounts.finance_model import PaymentEntry, PaymentItem
from app.business_validation.item_validation import (
    BizValidationError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_DISABLED,
    ERR_ACCOUNT_WRONG_COMPANY,
    ERR_GROUP_ACCOUNT_NOT_ALLOWED,
)


class PaymentRepo:
    def __init__(self, s: Optional[Session] = None):
        self.s: Session = s or db.session

    # ---------- codes ----------
    def code_exists_pe(self, company_id: int, branch_id: int, code: str) -> bool:
        q = select(PaymentEntry.id).where(
            PaymentEntry.company_id == company_id,
            PaymentEntry.branch_id == branch_id,
            PaymentEntry.code == code,
        )
        return self.s.execute(q).scalar_one_or_none() is not None

    # ---------- CRUD ----------
    def get(self, payment_id: int) -> Optional[PaymentEntry]:
        return self.s.get(PaymentEntry, payment_id)

    def add(self, obj: PaymentEntry) -> PaymentEntry:
        self.s.add(obj)
        self.s.flush([obj])
        return obj

    def add_items(self, payment_id: int, rows: Iterable[Dict]) -> None:
        for r in rows or []:
            it = PaymentItem(
                payment_id=payment_id,
                source_doctype_id=r.get("source_doctype_id"),
                source_doc_id=r.get("source_doc_id"),
                allocated_amount=Decimal(str(r.get("allocated_amount") or "0")),
            )
            self.s.add(it)
        self.s.flush()

    def delete_items(self, payment_id: int) -> None:
        self.s.query(PaymentItem).filter(PaymentItem.payment_id == payment_id).delete()
        self.s.flush()

    def update_header(self, pe: PaymentEntry, data: Dict) -> PaymentEntry:
        mutable = (
            "payment_type", "posting_date", "mode_of_payment_id",
            "party_type", "party_id",
            "paid_from_account_id", "paid_to_account_id",
            "paid_amount", "remarks", "posting_dt_norm"
        )
        for k in mutable:
            if k in data:
                setattr(pe, k, data[k])
        self.s.flush([pe])
        return pe

    # ---------- totals ----------
    def recompute_allocations(self, payment_id: int) -> Tuple[Decimal, Decimal]:
        total_alloc = self.s.execute(
            select(func.coalesce(func.sum(PaymentItem.allocated_amount), 0))
            .where(PaymentItem.payment_id == payment_id)
        ).scalar_one()
        pe = self.get(payment_id)
        paid = Decimal(pe.paid_amount or 0)
        pe.allocated_amount = Decimal(total_alloc)
        pe.unallocated_amount = paid - Decimal(total_alloc)
        self.s.flush([pe])
        return (Decimal(total_alloc), pe.unallocated_amount)

    # ---------- status ----------
    def mark_submitted(self, payment_id: int) -> None:
        self.s.execute(
            update(PaymentEntry)
            .where(PaymentEntry.id == payment_id)
            .values(doc_status=DocStatusEnum.SUBMITTED)
        )
        self.s.flush()

    def mark_cancelled(self, payment_id: int) -> None:
        self.s.execute(
            update(PaymentEntry)
            .where(PaymentEntry.id == payment_id)
            .values(doc_status=DocStatusEnum.CANCELLED)
        )
        self.s.flush()

    # ---------- account helpers (multi-tenant safe, no hardcoded names) ----------
    def get_account_meta(self, account_id: int) -> Optional[Dict]:
        row = self.s.execute(
            select(
                Account.id, Account.company_id, Account.code, Account.name,
                Account.is_group, Account.enabled
            ).where(Account.id == account_id)
        ).first()
        if not row:
            return None
        return {
            "id": row.id,
            "company_id": int(row.company_id),
            "code": str(row.code),
            "name": row.name,
            "is_group": bool(row.is_group),
            "enabled": bool(row.enabled),
        }

    def get_accounts_meta(self, account_ids: Sequence[int]) -> Dict[int, Dict]:
        if not account_ids:
            return {}
        rows = self.s.execute(
            select(
                Account.id, Account.company_id, Account.code, Account.name,
                Account.is_group, Account.enabled
            ).where(Account.id.in_([int(x) for x in account_ids]))
        ).all()
        out: Dict[int, Dict] = {}
        for r in rows:
            out[int(r.id)] = {
                "id": int(r.id),
                "company_id": int(r.company_id),
                "code": str(r.code),
                "name": r.name,
                "is_group": bool(r.is_group),
                "enabled": bool(r.enabled),
            }
        return out

    def ensure_accounts_accessible(self, *, company_id: int, account_ids: Sequence[int]) -> None:
        """
        Ensure the accounts exist, belong to company, are enabled, and are detail accounts.
        Uses ERP-style short messages from item_validation.py.
        """
        metas = self.get_accounts_meta(account_ids)

        for aid in account_ids:
            meta = metas.get(int(aid))
            if not meta:
                raise BizValidationError(ERR_ACCOUNT_NOT_FOUND)
            if int(meta["company_id"]) != int(company_id):
                raise BizValidationError(ERR_ACCOUNT_WRONG_COMPANY)
            if not meta["enabled"]:
                raise BizValidationError(ERR_ACCOUNT_DISABLED)
            if meta["is_group"]:
                raise BizValidationError(ERR_GROUP_ACCOUNT_NOT_ALLOWED)

    # ---------- party helpers (company/branch/role/active) ----------
    def get_party_meta(self, party_id: int) -> Optional[Dict]:
        """
        Lightweight read without importing the Party ORM class.
        """
        row = self.s.execute(
            text("SELECT id, company_id, branch_id, role, status FROM parties WHERE id = :pid"),
            {"pid": int(party_id)},
        ).first()
        if not row:
            return None
        return {
            "id": int(row.id),
            "company_id": int(row.company_id),
            "branch_id": int(row.branch_id) if getattr(row, "branch_id", None) is not None else None,
            "role": str(row.role) if getattr(row, "role", None) is not None else None,
            "status": str(row.status) if getattr(row, "status", None) is not None else None,
        }

    def ensure_party_accessible(self, *, company_id: int, branch_id: int,
                                party_type_label: str, party_id: int) -> None:
        """
        Ensure party exists, matches role (Customer/Supplier), belongs to company,
        optionally branch (if party.branch_id is set), and is active.
        Raises ValueError with a short user-facing message.
        """
        meta = self.get_party_meta(party_id)
        label = "Customer" if party_type_label == "Customer" else ("Supplier" if party_type_label == "Supplier" else "Party")

        if not meta:
            raise ValueError(f"{label} not found.")

        # Role match (only if Customer/Supplier context)
        if party_type_label in ("Customer", "Supplier"):
            if (meta.get("role") or "").lower() != party_type_label.lower():
                raise ValueError(f"{label} not found.")

        # Company match
        if int(meta.get("company_id", -1)) != int(company_id):
            raise ValueError(f"{label} does not belong to this company.")

        # Branch match (only when party is bound to a branch)
        pb = meta.get("branch_id")
        if pb is not None and int(pb) != int(branch_id):
            raise ValueError(f"{label} does not belong to this branch.")

        # Status must be ACTIVE
        if (meta.get("status") or "").upper() != "ACTIVE":
            raise ValueError(f"{label} is inactive.")
