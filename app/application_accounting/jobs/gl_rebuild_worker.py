# application_accounting/jobs/gl_rebuild_worker.py
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from decimal import Decimal

from app.application_accounting.chart_of_accounts.models import AccountBalance, PartyAccountBalance, GeneralLedgerEntry


def rebuild_balances(s: Session, company_id: int) -> None:
    # reset (for simplicity here; production: batch)
    s.query(AccountBalance).delete(synchronize_session=False)
    s.query(PartyAccountBalance).delete(synchronize_session=False)
    s.flush()

    rows = s.execute(
        select(
            GeneralLedgerEntry.account_id,
            GeneralLedgerEntry.party_id,
            GeneralLedgerEntry.party_type,
            GeneralLedgerEntry.debit,
            GeneralLedgerEntry.credit,
        ).where(GeneralLedgerEntry.company_id == company_id)
    ).all()

    # naive rebuild
    from app.application_accounting.engine.balance_updater import apply_balances

    for (account_id, party_id, party_type, debit, credit) in rows:
        apply_balances(
            s, account_id=account_id, party_id=party_id, party_type=party_type,
            debit=Decimal(str(debit or 0)), credit=Decimal(str(credit or 0))
        )
    s.flush()
