# app/application_accounting/query_builders/mop_dropdowns.py
from __future__ import annotations

from typing import Mapping, Any, Optional

from sqlalchemy import (
    select, exists, and_, or_, case, literal, func
)
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.common.models.base import StatusEnum  # if you tag MoP enabled separately you can drop this
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment,
    ModeOfPaymentAccount,
    AccountAccessPolicy,
    AccountUseRoleEnum,
)
from app.application_accounting.chart_of_accounts.models import Account, AccountTypeEnum  # adjust path if different


# ---------- tiny helpers ----------
def _co(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)

def _br(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "branch_id", None)

def _uid(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "user_id", None)

def _dept(ctx: AffiliationContext) -> Optional[int]:
    # only if your ctx has department_id; harmless if not present
    return getattr(ctx, "department_id", None)


def build_vat_account_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Single-account dropdown for the company's VAT account.

    Defaults:
      - code = "2311"
      - name = "VAT"

    Selection rule (company-scoped):
      enabled = True AND is_group = False AND account_type = LIABILITY AND (code == 2311 OR name == 'VAT')

    Returns columns:
      - value: Account.id
      - label: Account.name
      - code : Account.code   (exposed via meta)
    """
    co_id = _co(ctx)
    if not co_id:
        # empty result if no company context
        return select(Account.id.label("value")).where(literal(False))

    code = str(params.get("code") or "2311").strip()
    name = str(params.get("name") or "VAT").strip()

    q = (
        select(
            Account.id.label("value"),
            Account.name.label("label"),
            Account.code.label("code"),
        )
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
            Account.is_group.is_(False),
            Account.account_type == AccountTypeEnum.LIABILITY,
            or_(Account.code == code, Account.name == name),
        )
        .order_by(Account.code.asc(), Account.name.asc())
    )
    return q

# ---------- Modes of Payment (simple) ----------
def build_modes_of_payment_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    List enabled Modes of Payment for the user's company.
    Optional filter: params['type'] in {"CASH","BANK","MOBILE_MONEY","CREDIT_CARD","OTHER"}
    Optional: params['ensure_has_account'] -> only show MoPs that have at least one enabled account link.

    Columns returned:
      - value : ModeOfPayment.id
      - label : ModeOfPayment.name
      - type  : ModeOfPayment.type
    """
    co_id = _co(ctx)
    if not co_id:
        # empty
        return select(ModeOfPayment.id.label("value")).where(literal(False))

    mop_type = params.get("type")
    ensure_has_account = params.get("ensure_has_account", True)

    base = (
        select(
            ModeOfPayment.id.label("value"),
            ModeOfPayment.name.label("label"),
            ModeOfPayment.type.label("type"),
        )
        .where(
            ModeOfPayment.company_id == co_id,
            ModeOfPayment.enabled.is_(True),
        )
    )

    if mop_type:
        base = base.where(ModeOfPayment.type == mop_type)

    if ensure_has_account:
        has_acc = exists(
            select(literal(1))
            .select_from(ModeOfPaymentAccount)
            .join(Account, Account.id == ModeOfPaymentAccount.account_id)
            .where(
                ModeOfPaymentAccount.mode_of_payment_id == ModeOfPayment.id,
                ModeOfPaymentAccount.enabled.is_(True),
                Account.enabled.is_(True),
                Account.company_id == co_id,
            )
        )
        base = base.where(has_acc)

    return base.order_by(ModeOfPayment.name.asc())


# ---------- MoP → Accounts (dependent dropdown; ERPNext parity + your policy model) ----------
def build_mop_accounts_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dependent dropdown: requires 'mop_id' (or 'mode_of_payment_id').

    Logic (ERP-like + your policy layer):
      1) CANDIDATES = enabled ModeOfPaymentAccount rows for this MoP, joined to enabled Accounts of the same company
      2) POLICIES = enabled AccountAccessPolicy rows for this (company, mop) that MATCH the current user at the
         highest scope: user (3) > department (2) > branch (1) > company (0)
         - If a 'role' is provided in params, we filter policies by that role.
         - If ANY matching policies exist → ALLOWED = policies at MAX(rank) only
         - If NO matching policies exist → ALLOWED = CANDIDATES
      3) Default account (ModeOfPaymentAccount.is_default) is sorted first if it is in ALLOWED.

    Params:
      - mop_id | mode_of_payment_id : int  (required)
      - role (optional)             : AccountUseRoleEnum (name or value as str)

    Returns columns:
      - value      : Account.id
      - label      : Account.name      (nice for UI)
      - code       : Account.code      (extra field for sublabel/meta)
      - is_default : bool              (so UI can put a star or pin it)
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Account.id.label("value")).where(literal(False))

    mop_id = params.get("mop_id") or params.get("mode_of_payment_id")
    if not mop_id:
        return select(Account.id.label("value")).where(literal(False))

    # optional role filter
    role_raw = params.get("role")
    role_val = None
    if role_raw:
        try:
            role_val = AccountUseRoleEnum(role_raw)  # allow either "CASH_IN" or AccountUseRoleEnum.CASH_IN
        except Exception:
            role_val = None  # ignore bad role; behave as if role not provided

    user_id = _uid(ctx)
    dept_id = _dept(ctx)
    branch_id = _br(ctx)

    # ---------- CANDIDATES: MoP-linked accounts (enabled + same company) ----------
    cand = (
        select(
            ModeOfPaymentAccount.account_id.label("account_id"),
            ModeOfPaymentAccount.is_default.label("is_default"),
            Account.code.label("code"),
            Account.name.label("name"),
        )
        .select_from(ModeOfPaymentAccount)
        .join(ModeOfPayment, ModeOfPayment.id == ModeOfPaymentAccount.mode_of_payment_id)
        .join(Account, Account.id == ModeOfPaymentAccount.account_id)
        .where(
            ModeOfPayment.id == int(mop_id),
            ModeOfPayment.company_id == co_id,
            ModeOfPayment.enabled.is_(True),
            ModeOfPaymentAccount.enabled.is_(True),
            Account.enabled.is_(True),
            Account.company_id == co_id,
        )
    ).cte("cand")

    # ---------- POLICY MATCH & RANK ----------
    # Match expressions (only those that can be true for current user)
    match_terms = []

    if user_id is not None:
        match_terms.append(AccountAccessPolicy.user_id == user_id)

    if dept_id is not None:
        match_terms.append(AccountAccessPolicy.department_id == dept_id)

    if branch_id is not None:
        match_terms.append(AccountAccessPolicy.branch_id == branch_id)

    # company-wide (no scope set)
    match_terms.append(and_(
        AccountAccessPolicy.user_id.is_(None),
        AccountAccessPolicy.department_id.is_(None),
        AccountAccessPolicy.branch_id.is_(None),
    ))

    match_expr = or_(*match_terms)

    # policies filtered for this company + mop (+optional role), ranked by scope
    pol_base = (
        select(
            AccountAccessPolicy.account_id.label("account_id"),
            case(
                (AccountAccessPolicy.user_id == user_id, 3),
                (AccountAccessPolicy.department_id == dept_id, 2),
                (AccountAccessPolicy.branch_id == branch_id, 1),
                (
                    and_(
                        AccountAccessPolicy.user_id.is_(None),
                        AccountAccessPolicy.department_id.is_(None),
                        AccountAccessPolicy.branch_id.is_(None),
                    ), 0
                ),
                else_=-1,
            ).label("rank"),
        )
        .where(
            AccountAccessPolicy.enabled.is_(True),
            AccountAccessPolicy.company_id == co_id,
            AccountAccessPolicy.mode_of_payment_id == int(mop_id),
            match_expr,
        )
    )

    if role_val is not None:
        pol_base = pol_base.where(AccountAccessPolicy.role == role_val)

    pol = pol_base.subquery("pol")

    # Is there any matching policy at all?
    pol_exists_q = (
        select(literal(1))
        .select_from(AccountAccessPolicy)
        .where(
            AccountAccessPolicy.enabled.is_(True),
            AccountAccessPolicy.company_id == co_id,
            AccountAccessPolicy.mode_of_payment_id == int(mop_id),
            match_expr,
        )
    )
    if role_val is not None:
        pol_exists_q = pol_exists_q.where(AccountAccessPolicy.role == role_val)
    any_pol_exists = exists(pol_exists_q)

    # If there are policies, keep only those at MAX(rank)
    max_rank = select(func.max(pol.c.rank)).scalar_subquery()

    # ---------- FINAL SELECT ----------
    # If any policy exists → restrict to those accounts whose pol.rank == max_rank
    # Else → all candidates pass
    q = (
        select(
            cand.c.account_id.label("value"),
            cand.c.name.label("label"),
            cand.c.code.label("code"),
            cand.c.is_default.label("is_default"),
        )
        .select_from(cand)
        .outerjoin(pol, pol.c.account_id == cand.c.account_id)
        .where(
            or_(
                ~any_pol_exists,          # no policies => all candidates
                pol.c.rank == max_rank,   # policies exist => highest scope only
            )
        )
        .order_by(
            # default account first (like ERPNext's "fetch default on MoP select")
            case((cand.c.is_default.is_(True), 0), else_=1),
            cand.c.code.asc(),
            cand.c.name.asc(),
        )
    )

    return q



def build_asset_accounts_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    List ASSET accounts for the user's company.

    Defaults:
      - Returns leaf accounts (is_group = False) only.
      - Label is Account.name; meta includes code (and is_group).

    Optional query params:
      - only_groups: 1/0 → only show folders
      - only_leaves: 1/0 → only show leaf accounts (default = 1)
      - parent_account_id: int → restrict to children of a parent
      - q: str → search by name/code (ilike)

    Returns:
      value : Account.id
      label : Account.name
      code  : Account.code
      is_group : bool
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Account.id.label("value")).where(literal(False))

    only_groups = str(params.get("only_groups", "")).lower() in {"1", "true", "yes"}
    only_leaves = str(params.get("only_leaves", "1")).lower() in {"1", "true", "yes"}  # default: leaves

    q = (
        select(
            Account.id.label("value"),
            Account.name.label("label"),
            Account.code.label("code"),
            Account.is_group.label("is_group"),
        )
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
            Account.account_type == AccountTypeEnum.ASSET,
        )
    )

    # Scope to children of a parent, if provided
    parent_id = params.get("parent_account_id")
    if parent_id is not None:
        try:
            q = q.where(Account.parent_account_id == int(parent_id))
        except Exception:
            return select(Account.id.label("value")).where(literal(False))

    # Leaf vs group filters
    if only_groups and not only_leaves:
        q = q.where(Account.is_group.is_(True))
    elif only_leaves and not only_groups:
        q = q.where(Account.is_group.is_(False))
    # (if both provided or neither → no extra filter; you’ll get both)

    # Search
    term = (params.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.where(or_(Account.name.ilike(like), Account.code.ilike(like)))

    # Order: groups first (if mixed), then by code, then by name
    q = q.order_by(Account.is_group.desc(), Account.code.asc(), Account.name.asc())
    return q