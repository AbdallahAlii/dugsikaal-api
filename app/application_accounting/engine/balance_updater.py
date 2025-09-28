# application_accounting/engine/balance_updater.py
from __future__ import annotations
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application_accounting.chart_of_accounts.models import AccountBalance, PartyAccountBalance, PartyTypeEnum


def _bump_account_balance(s: Session, account_id: int, debit: Decimal, credit: Decimal) -> None:
    row = s.execute(
        select(AccountBalance).where(AccountBalance.account_id == account_id)
    ).scalar_one_or_none()
    if not row:
        row = AccountBalance(account_id=account_id, total_debit=0, total_credit=0, current_balance=0)
        s.add(row)
    row.total_debit  = (row.total_debit  or 0) + debit
    row.total_credit = (row.total_credit or 0) + credit
    row.current_balance = (row.total_debit or 0) - (row.total_credit or 0)

def _bump_party_balance(
    s: Session, account_id: int, party_id: Optional[int], party_type: Optional[PartyTypeEnum],
    debit: Decimal, credit: Decimal
) -> None:
    if not party_id or not party_type:
        return
    row = s.execute(
        select(PartyAccountBalance).where(
            PartyAccountBalance.account_id == account_id,
            PartyAccountBalance.party_id == party_id,
            PartyAccountBalance.party_type == party_type,
        )
    ).scalar_one_or_none()
    if not row:
        row = PartyAccountBalance(
            account_id=account_id, party_id=party_id, party_type=party_type,
            total_debit=0, total_credit=0, current_balance=0
        )
        s.add(row)
    row.total_debit  = (row.total_debit  or 0) + debit
    row.total_credit = (row.total_credit or 0) + credit
    row.current_balance = (row.total_debit or 0) - (row.total_credit or 0)

def apply_balances(
    s: Session, *,
    account_id: int, party_id: Optional[int], party_type: Optional[PartyTypeEnum],
    debit: Decimal, credit: Decimal
) -> None:
    _bump_account_balance(s, account_id, debit, credit)
    _bump_party_balance(s, account_id, party_id, party_type, debit, credit)
