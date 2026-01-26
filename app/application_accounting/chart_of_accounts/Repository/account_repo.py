from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select, exists
from sqlalchemy.orm import Session
import logging

from app.application_accounting.chart_of_accounts.models import (
    Account,
    GeneralLedgerEntry,
    JournalEntryItem,
)
from config.database import db

log = logging.getLogger(__name__)


class AccountRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Basic fetchers ---

    def get_by_id(self, account_id: int) -> Optional[Account]:
        return self.s.get(Account, account_id)

    def get_by_code(self, company_id: int, code: str) -> Optional[Account]:
        return self.s.scalar(
            select(Account).where(
                Account.company_id == company_id,
                Account.code == code,
            )
        )

    def get_children(self, company_id: int, parent_id: int) -> List[Account]:
        return list(self.s.scalars(
            select(Account).where(
                Account.company_id == company_id,
                Account.parent_account_id == parent_id,
            ).order_by(Account.code)
        ))

    def has_children(self, company_id: int, account_id: int) -> bool:
        return self.s.scalar(
            select(exists().where(
                Account.company_id == company_id,
                Account.parent_account_id == account_id,
            ))
        )

    # --- Transaction checks ---

    def has_transactions(self, company_id: int, account_id: int) -> bool:
        """Check if account is referenced in any JournalEntryItem or GL Entry."""
        jei_exists = self.s.scalar(
            select(exists().where(
                JournalEntryItem.account_id == account_id
            ))
        )

        if jei_exists:
            return True

        gle_exists = self.s.scalar(
            select(exists().where(
                GeneralLedgerEntry.company_id == company_id,
                GeneralLedgerEntry.account_id == account_id,
            ))
        )

        return bool(gle_exists)

    # --- CRUD operations ---

    def add(self, account: Account) -> Account:
        self.s.add(account)
        self.s.flush([account])
        return account

    def delete(self, account: Account) -> None:
        self.s.delete(account)
        self.s.flush()

    def update(self, account: Account, updates: dict) -> None:
        for k, v in updates.items():
            setattr(account, k, v)
        self.s.flush([account])
    def get_child_codes(self, company_id: int, parent_account_id: int) -> List[str]:
        """
        Return all child account codes under a given parent for this company.
        Used for auto-generating the next account number.
        """
        rows = self.s.scalars(
            select(Account.code).where(
                Account.company_id == company_id,
                Account.parent_account_id == parent_account_id,
            )
        )
        return list(rows)


    def get_by_name(self, company_id: int, name: str) -> Optional[Account]:
        """
        Find account by name within a company (for uniqueness checks).
        """
        return self.s.scalar(
            select(Account).where(
                Account.company_id == company_id,
                Account.name == name,
            )
        )