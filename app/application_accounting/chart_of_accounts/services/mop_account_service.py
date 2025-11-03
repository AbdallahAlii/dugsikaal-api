# app/application_accounting/services/mop_account_service.py
from __future__ import annotations
import logging
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.orm import Session
from config.database import db

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.account_policies import AccountUseRoleEnum
from app.application_accounting.chart_of_accounts.Repository.mop_account_repo import MOPAccountRepository

log = logging.getLogger(__name__)


# Optional helper if you want to infer role from a Payment Entry context
def infer_role(
    *,
    payment_type: Optional[str] = None,  # "PAY" | "RECEIVE" | "INTERNAL_TRANSFER"
    side: Optional[str] = None           # "from"/"to" for transfers
) -> Optional[AccountUseRoleEnum]:
    if not payment_type:
        return None
    pt = (payment_type or "").upper()
    sd = (side or "").lower()

    if pt == "PAY":
        return AccountUseRoleEnum.CASH_OUT
    if pt == "RECEIVE":
        return AccountUseRoleEnum.CASH_IN
    if pt == "INTERNAL_TRANSFER":
        if sd in {"from", "source"}:
            return AccountUseRoleEnum.TRANSFER_SOURCE
        if sd in {"to", "target"}:
            return AccountUseRoleEnum.TRANSFER_TARGET
        # If side not given, return None to show all candidates
        return None
    return None


class MOPAccountService:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = MOPAccountRepository(self.s)

    def resolve_dropdown(
        self,
        *,
        ctx: AffiliationContext,
        mode_of_payment_id: int,
        role: Optional[AccountUseRoleEnum] = None,
        payment_type: Optional[str] = None,
        side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns:
        {
          "default_account_id": int | None,
          "rows": [{"value": id, "label": name, "code": code, "is_default": bool}, ...]
        }
        """
        # Company is mandatory for scoping
        if not getattr(ctx, "company_id", None):
            return {"default_account_id": None, "rows": []}

        if role is None:
            role = infer_role(payment_type=payment_type, side=side)

        q = self.repo.build_allowed_accounts_query(
            company_id=ctx.company_id,
            mop_id=int(mode_of_payment_id),
            role=role,
            user_id=getattr(ctx, "user_id", None),
            branch_id=getattr(ctx, "branch_id", None),
            department_id=getattr(ctx, "department_id", None),  # ok if None
        )
        rows = self.s.execute(q).mappings().all()  # [{"value":..., "label":..., ...}, ...]

        default_id = next((r["value"] for r in rows if r["is_default"]), None)
        # If MoP default isn’t allowed, pick first allowed row as a soft default for UX
        if default_id is None and rows:
            default_id = rows[0]["value"]

        return {"default_account_id": default_id, "rows": rows}
