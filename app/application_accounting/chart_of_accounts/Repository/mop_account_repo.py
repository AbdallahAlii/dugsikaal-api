# app/application_accounting/repo/mop_account_repo.py
from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy import select, and_, or_, case, func, literal
from sqlalchemy.orm import Session

from config.database import db
from app.application_accounting.chart_of_accounts.account_policies  import (
    ModeOfPayment, ModeOfPaymentAccount, AccountAccessPolicy, AccountUseRoleEnum
)
from app.application_accounting.chart_of_accounts.models import Account  # adjust if your path differs

log = logging.getLogger(__name__)


class MOPAccountRepository:
    """
    Read-only SQL builder for ModeOfPayment → Account resolution
    with policy precedence: user > department > branch > company.
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def build_allowed_accounts_query(
        self,
        *,
        company_id: int,
        mop_id: int,
        role: Optional[AccountUseRoleEnum],
        user_id: Optional[int],
        branch_id: Optional[int],
        department_id: Optional[int],
    ):
        """
        Returns a SQLAlchemy Select producing:
          - value: Account.id
          - label: Account.name
          - code:  Account.code
          - is_default: ModeOfPaymentAccount.is_default

        Behavior:
          - If no policy rows exist for (company, mop, role), ALL candidates are allowed.
          - If policies exist, allow only accounts from the HIGHEST matching scope.
        """

        # --- Base candidates: enabled MoPAccounts + enabled Accounts for this company/MoP ---
        cand = (
            select(
                Account.id.label("value"),
                Account.name.label("label"),
                Account.code.label("code"),
                ModeOfPaymentAccount.is_default.label("is_default"),
            )
            .select_from(ModeOfPaymentAccount)
            .join(ModeOfPayment, ModeOfPayment.id == ModeOfPaymentAccount.mode_of_payment_id)
            .join(Account, Account.id == ModeOfPaymentAccount.account_id)
            .where(
                ModeOfPayment.id == mop_id,
                ModeOfPayment.company_id == company_id,
                ModeOfPayment.enabled.is_(True),
                ModeOfPaymentAccount.enabled.is_(True),
                Account.enabled.is_(True),
            )
        ).cte("cand")

        if not role:
            # No role → no policy filtering; the dropdown can still be scoped by permissions elsewhere if needed.
            q = select(cand.c.value, cand.c.label, cand.c.code, cand.c.is_default).order_by(
                cand.c.is_default.desc(), cand.c.label.asc()
            )
            return q

        # --- Policies for this MoP-role + scope ranking ---
        # rank: user=3, department=2, branch=1, company=0 (company = all scope NULL)
        P = AccountAccessPolicy
        rank = case(
            (
                P.user_id == (user_id if user_id is not None else literal(-1)),
                literal(3),
            ),
            (
                P.department_id == (department_id if department_id is not None else literal(-1)),
                literal(2),
            ),
            (
                P.branch_id == (branch_id if branch_id is not None else literal(-1)),
                literal(1),
            ),
            else_=literal(0),
        ).label("rank")

        pol = (
            select(P.account_id.label("account_id"), rank)
            .where(
                P.enabled.is_(True),
                P.company_id == company_id,
                P.mode_of_payment_id == mop_id,
                P.role == role,
            )
        ).cte("pol")

        # any policy?
        policy_count = select(func.count(literal(1))).select_from(pol).scalar_subquery()

        # best rank
        best_rank = select(func.max(pol.c.rank)).scalar_subquery()

        # Allowed = candidates if no policies; else restricted to accounts whose policy has the best rank
        q = (
            select(cand.c.value, cand.c.label, cand.c.code, cand.c.is_default)
            .select_from(cand)
            .outerjoin(pol, pol.c.account_id == cand.c.value)
            .where(
                or_(
                    policy_count == 0,
                    pol.c.rank == best_rank
                )
            )
            .order_by(
                cand.c.is_default.desc(),  # default first if still allowed
                cand.c.label.asc()
            )
        )
        return q
