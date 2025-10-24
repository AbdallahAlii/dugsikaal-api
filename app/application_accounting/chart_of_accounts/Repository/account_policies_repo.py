from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, ModeOfPaymentAccount, AccountAccessPolicy
)
from app.application_accounting.chart_of_accounts.models import Account

class PoliciesRepository:
    def __init__(self, session: Session):
        self.s: Session = session

    # ───── Mode of Payment
    def get_mop_by_id(self, mop_id: int) -> Optional[ModeOfPayment]:
        return self.s.get(ModeOfPayment, mop_id)

    def get_mop_by_name(self, company_id: int, name: str) -> Optional[ModeOfPayment]:
        return self.s.scalar(
            select(ModeOfPayment).where(
                ModeOfPayment.company_id == company_id,
                ModeOfPayment.name == name
            )
        )

    def create_mop(self, mop: ModeOfPayment) -> ModeOfPayment:
        self.s.add(mop)
        self.s.flush([mop])
        return mop

    def update_mop_fields(self, mop: ModeOfPayment, updates: dict) -> ModeOfPayment:
        for k, v in updates.items():
            setattr(mop, k, v)
        self.s.flush([mop])
        return mop

    # ───── Mode of Payment Account (NO branch_id - matches your model)
    def add_mop_account(self, mop_account: ModeOfPaymentAccount) -> ModeOfPaymentAccount:
        self.s.add(mop_account)
        self.s.flush([mop_account])
        return mop_account

    def delete_mop_account(self, mop_id: int, account_id: int) -> bool:
        result = self.s.execute(
            delete(ModeOfPaymentAccount).where(
                ModeOfPaymentAccount.mode_of_payment_id == mop_id,
                ModeOfPaymentAccount.account_id == account_id
            )
        )
        return result.rowcount > 0

    def get_mop_accounts(self, mop_id: int) -> List[ModeOfPaymentAccount]:
        return self.s.scalars(
            select(ModeOfPaymentAccount).where(
                ModeOfPaymentAccount.mode_of_payment_id == mop_id
            )
        ).all()

    def unset_mop_defaults(self, mop_id: int) -> None:
        """Unset all defaults for a MoP (Frappe-style: one default per MoP)"""
        self.s.execute(
            update(ModeOfPaymentAccount)
            .where(ModeOfPaymentAccount.mode_of_payment_id == mop_id)
            .values(is_default=False)
        )

    def mop_has_account(self, mop_id: int, account_id: int) -> bool:
        return self.s.scalar(
            select(ModeOfPaymentAccount.id).where(
                ModeOfPaymentAccount.mode_of_payment_id == mop_id,
                ModeOfPaymentAccount.account_id == account_id
            )
        ) is not None

    # ───── Account Access Policy
    def create_access_policy(self, policy: AccountAccessPolicy) -> AccountAccessPolicy:
        self.s.add(policy)
        self.s.flush([policy])
        return policy

    def get_access_policy_by_id(self, policy_id: int) -> Optional[AccountAccessPolicy]:
        return self.s.get(AccountAccessPolicy, policy_id)

    def update_access_policy_fields(self, policy: AccountAccessPolicy, updates: dict) -> AccountAccessPolicy:
        for k, v in updates.items():
            setattr(policy, k, v)
        self.s.flush([policy])
        return policy

    # ───── Validation helpers
    def account_in_company(self, company_id: int, account_id: int) -> bool:
        return self.s.scalar(select(Account.id).where(
            Account.company_id == company_id,
            Account.id == account_id
        )) is not None

    def account_is_leaf(self, account_id: int) -> bool:
        """Check if account is a leaf account (not a group)"""
        row = self.s.scalar(select(Account).where(Account.id == account_id))
        if not row:
            return False
        return not row.is_group