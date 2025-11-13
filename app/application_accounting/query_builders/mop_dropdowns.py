# app/application_accounting/query_builders/mop_dropdowns.py
from __future__ import annotations

from typing import Mapping, Any, Optional, Iterable

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
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType
from app.application_parties.parties_models import Party,PartyRoleEnum
from app.application_hr.models.hr import Employee,EmployeeAssignment

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






# ---- access helpers (same semantics as your list builders) ----
def _is_super_admin(ctx: AffiliationContext) -> bool:
    roles = getattr(ctx, "roles", []) or []
    return "Super Admin" in roles

def _is_company_owner(ctx: AffiliationContext) -> bool:
    # owner = primary affiliation with no branch_id
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False

def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    return bool(getattr(ctx, "is_system_admin", False) or _is_super_admin(ctx) or _is_company_owner(ctx))


def _br_ids(ctx: AffiliationContext) -> list[int]:
    return list(getattr(ctx, "branch_ids", []) or [])

def _normalize_party_type(raw: Any) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s in {"customer", "customers"}:
        return "Customer"
    if s in {"supplier", "suppliers"}:
        return "Supplier"
    if s in {"employee", "employees"}:
        return "Employee"
    if s in {"shareholder", "shareholders"}:
        return "Shareholder"
    return None

def _tokens(query: str) -> list[str]:
    # split on whitespace, ignore empties
    return [t for t in (query or "").strip().split() if t]

def _and_of_or_terms(cols: Iterable, query: str):
    """
    Build ( (col1 ILIKE %t1% OR col2 ILIKE %t1% OR ...) AND ( ... for t2 ) ... )
    """
    toks = _tokens(query)
    if not toks:
        return None
    per_token_clauses = []
    for t in toks:
        like = f"%{t}%"
        per_token_clauses.append(or_(*[c.ilike(like) for c in cols]))
    return and_(*per_token_clauses)




def _ledger_pref(role: PartyRoleEnum) -> tuple[str, str]:
    """
    Returns (preferred_code, fallback_name_pattern)
    """
    if role == PartyRoleEnum.CUSTOMER:
        return ("1131", "%Debtors%")
    if role == PartyRoleEnum.SUPPLIER:
        return ("2111", "%Creditors%")
    if role == PartyRoleEnum.EMPLOYEE:
        return ("1151", "%Employee Advances%")
    if role == PartyRoleEnum.SHAREHOLDER:
        return ("1152", "%Loans to Shareholders%")
    return ("", "%")  # no-op fallback

def _ledger_id_sq_for_role(co_id: int, role: PartyRoleEnum):
    pref_code, name_like = _ledger_pref(role)
    if not co_id:
        return select(literal(None)).scalar_subquery()
    return (
        select(Account.id)
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
            Account.is_group.is_(False),
            or_(Account.code == pref_code, Account.name.ilike(name_like)),
        )
        .order_by(Account.code.asc(), Account.name.asc())
        .limit(1)
        .scalar_subquery()
    )

def _account_code_from_id(id_sq):
    return select(Account.code).where(Account.id == id_sq).limit(1).scalar_subquery()

def _account_name_from_id(id_sq):
    return select(Account.name).where(Account.id == id_sq).limit(1).scalar_subquery()










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





# ---------- Expense Types (simple, ERPNext-style) ----------
def build_expense_types_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    List enabled Expense Types for the user's company.

    Optional:
      - ensure_has_default_account (bool, default True): only show types with a default account.

    Returns:
      - value        : ExpenseType.id
      - label        : ExpenseType.name
      - description  : ExpenseType.description
    """
    co_id = _co(ctx)
    if not co_id:
        return select(ExpenseType.id.label("value")).where(literal(False))

    ensure_has_default_account = params.get("ensure_has_default_account", True)

    q = (
        select(
            ExpenseType.id.label("value"),
            ExpenseType.name.label("label"),
            ExpenseType.description.label("description"),
        )
        .where(
            ExpenseType.company_id == co_id,
            ExpenseType.enabled.is_(True),
        )
    )

    if ensure_has_default_account:
        q = q.where(ExpenseType.default_account_id.is_not(None))

    return q.order_by(ExpenseType.name.asc())


# ---------- Expense Type → Default Account (single row; strict ERPNext parity) ----------
def build_expense_type_default_account_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Get the DEFAULT expense account for a given Expense Type.

    Params:
      - expense_type_id : int (required)

    Returns (0–1 rows):
      - value : Account.id
      - label : Account.name
      - code  : Account.code
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Account.id.label("value")).where(literal(False))

    et_id = params.get("expense_type_id")
    if not et_id:
        return select(Account.id.label("value")).where(literal(False))

    q = (
        select(
            Account.id.label("value"),
            Account.name.label("label"),
            Account.code.label("code"),
        )
        .select_from(ExpenseType)
        .join(Account, Account.id == ExpenseType.default_account_id)
        .where(
            ExpenseType.id == int(et_id),
            ExpenseType.company_id == co_id,
            ExpenseType.enabled.is_(True),
            Account.company_id == co_id,
            Account.enabled.is_(True),
            Account.account_type == AccountTypeEnum.EXPENSE,
        )
        .limit(1)
    )
    return q


# ---------- All Expense Accounts (company-scoped; leafs by default) ----------
def build_expense_accounts_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    List EXPENSE accounts for the user's company.

    Optional params:
      - only_groups: 1/0 → only folders
      - only_leaves: 1/0 → only leaf accounts (default=1)
      - parent_account_id: int → restrict to children under a parent
      - q: str → search by code/name (ilike)

    Returns:
      - value    : Account.id
      - label    : Account.name
      - code     : Account.code
      - is_group : bool
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Account.id.label("value")).where(literal(False))

    only_groups = str(params.get("only_groups", "")).lower() in {"1", "true", "yes"}
    only_leaves = str(params.get("only_leaves", "1")).lower() in {"1", "true", "yes"}

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
            Account.account_type == AccountTypeEnum.EXPENSE,
        )
    )

    parent_id = params.get("parent_account_id")
    if parent_id is not None:
        try:
            q = q.where(Account.parent_account_id == int(parent_id))
        except Exception:
            return select(Account.id.label("value")).where(literal(False))

    if only_groups and not only_leaves:
        q = q.where(Account.is_group.is_(True))
    elif only_leaves and not only_groups:
        q = q.where(Account.is_group.is_(False))

    term = (params.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.where(or_(Account.name.ilike(like), Account.code.ilike(like)))

    return q.order_by(Account.is_group.desc(), Account.code.asc(), Account.name.asc())


# ---------- Expense Type → Accounts (dependent; DEFAULT pinned first) ----------
def build_expense_type_accounts_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    ERPNext-like dependent dropdown for picking an expense ACCOUNT after choosing an Expense Type.
    It does NOT restrict choices; it simply pins the type's default account first.

    Params:
      - expense_type_id : int (required)
      - only_leaves / only_groups / parent_account_id / q (same behavior as build_expense_accounts_dropdown)

    Returns:
      - value      : Account.id
      - label      : Account.name
      - code       : Account.code
      - is_group   : bool
      - is_default : bool (True only for the type's default account)
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Account.id.label("value")).where(literal(False))

    et_id = params.get("expense_type_id")
    if not et_id:
        return select(Account.id.label("value")).where(literal(False))

    # Scalar subquery for the default account id (NULL if none or disabled)
    default_id_sq = (
        select(ExpenseType.default_account_id)
        .where(
            ExpenseType.id == int(et_id),
            ExpenseType.company_id == co_id,
            ExpenseType.enabled.is_(True),
        )
        .scalar_subquery()
    )

    only_groups = str(params.get("only_groups", "")).lower() in {"1", "true", "yes"}
    only_leaves = str(params.get("only_leaves", "1")).lower() in {"1", "true", "yes"}

    q = (
        select(
            Account.id.label("value"),
            Account.name.label("label"),
            Account.code.label("code"),
            Account.is_group.label("is_group"),
            case((Account.id == default_id_sq, True), else_=False).label("is_default"),
        )
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
            Account.account_type == AccountTypeEnum.EXPENSE,
        )
    )

    parent_id = params.get("parent_account_id")
    if parent_id is not None:
        try:
            q = q.where(Account.parent_account_id == int(parent_id))
        except Exception:
            return select(Account.id.label("value")).where(literal(False))

    if only_groups and not only_leaves:
        q = q.where(Account.is_group.is_(True))
    elif only_leaves and not only_groups:
        q = q.where(Account.is_group.is_(False))

    term = (params.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        q = q.where(or_(Account.name.ilike(like), Account.code.ilike(like)))

    # Default (if present) floats to the top; then code, name
    return q.order_by(
        case((Account.id == default_id_sq, 0), else_=1),
        Account.code.asc(),
        Account.name.asc(),
    )



# ---------------- Party-by-type (unified) ----------------
def _build_customers_or_suppliers_dropdown(
    session: Session,
    ctx: AffiliationContext,
    params: Mapping[str, Any],
    role: PartyRoleEnum,
):
    co_id = _co(ctx)
    if not co_id:
        return select(Party.id.label("value")).where(literal(False))

    include_inactive = str(params.get("include_inactive", "")).lower() in {"1", "true", "yes"}
    explicit_branch_id = params.get("branch_id")
    query_text = params.get("q") or params.get("query") or ""

    ledger_id_sq = _ledger_id_sq_for_role(co_id, role)

    q = (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            Party.phone.label("phone"),
            # --- NEW: ledger meta ---
            ledger_id_sq.label("ledger_account_id"),
            _account_code_from_id(ledger_id_sq).label("ledger_account_code"),
            _account_name_from_id(ledger_id_sq).label("ledger_account_name"),
        )
        .where(
            Party.company_id == co_id,
            Party.role == role,
        )
    )

    if not include_inactive:
        q = q.where(Party.status == StatusEnum.ACTIVE)

    if explicit_branch_id is not None:
        try:
            q = q.where(Party.branch_id == int(explicit_branch_id))
        except Exception:
            return select(Party.id.label("value")).where(literal(False))
    else:
        if not _has_company_wide_access(ctx):
            br_ids = _br_ids(ctx)
            if br_ids:
                q = q.where(or_(Party.branch_id.is_(None), Party.branch_id.in_(br_ids)))
            else:
                return select(Party.id.label("value")).where(literal(False))

    if query_text:
        clause = _and_of_or_terms(
            cols=(Party.name, Party.code, Party.phone),
            query=query_text,
        )
        if clause is not None:
            q = q.where(clause)

    return q.order_by(func.lower(Party.name).asc(), Party.code.asc())

def _build_employees_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    co_id = _co(ctx)
    if not co_id:
        return select(Employee.id.label("value")).where(literal(False))

    include_inactive = str(params.get("include_inactive", "")).lower() in {"1", "true", "yes"}
    explicit_branch_id = params.get("branch_id")
    query_text = params.get("q") or params.get("query") or ""

    # Employees: default to Employee Advances (1151) for Payment Entry use-cases
    ledger_id_sq = _ledger_id_sq_for_role(co_id, PartyRoleEnum.EMPLOYEE)

    base = (
        select(
            Employee.id.label("value"),
            Employee.full_name.label("label"),
            Employee.code.label("code"),
            Employee.phone_number.label("phone"),
            # --- NEW: ledger meta ---
            ledger_id_sq.label("ledger_account_id"),
            _account_code_from_id(ledger_id_sq).label("ledger_account_code"),
            _account_name_from_id(ledger_id_sq).label("ledger_account_name"),
        )
        .where(Employee.company_id == co_id)
    )

    if not include_inactive:
        base = base.where(Employee.status == StatusEnum.ACTIVE)

    if explicit_branch_id is not None:
        EA = EmployeeAssignment
        base = (
            base.join(
                EA,
                and_(
                    EA.employee_id == Employee.id,
                    EA.company_id == co_id,
                    EA.is_primary.is_(True),
                    EA.to_date.is_(None),
                    EA.branch_id == int(explicit_branch_id),
                ),
            )
        )
    else:
        if not _has_company_wide_access(ctx):
            br_ids = _br_ids(ctx)
            if br_ids:
                EA = EmployeeAssignment
                base = base.join(
                    EA,
                    and_(
                        EA.employee_id == Employee.id,
                        EA.company_id == co_id,
                        EA.is_primary.is_(True),
                        EA.to_date.is_(None),
                        EA.branch_id.in_(br_ids),
                    ),
                )
            else:
                return select(Employee.id.label("value")).where(literal(False))

    if query_text:
        clause = _and_of_or_terms(
            cols=(Employee.full_name, Employee.code, Employee.phone_number),
            query=query_text,
        )
        if clause is not None:
            base = base.where(clause)

    return base.distinct(Employee.id).order_by(func.lower(Employee.full_name).asc(), Employee.code.asc())

def _build_shareholders_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    # If you later add a Shareholder table, mirror the pattern above and keep the ledger meta via:
    # ledger_id_sq = _ledger_id_sq_for_role(co_id, PartyRoleEnum.SHAREHOLDER)
    return select(literal(None).label("value")).where(literal(False))

def build_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    kind = _normalize_party_type(
        params.get("party_type") or params.get("party_kind") or params.get("role")
    )
    if kind == "Customer":
        return _build_customers_or_suppliers_dropdown(session, ctx, params, PartyRoleEnum.CUSTOMER)
    if kind == "Supplier":
        return _build_customers_or_suppliers_dropdown(session, ctx, params, PartyRoleEnum.SUPPLIER)
    if kind == "Employee":
        return _build_employees_dropdown(session, ctx, params)
    if kind == "Shareholder":
        return _build_shareholders_dropdown(session, ctx, params)
    return select(literal(None).label("value")).where(literal(False))
# ---- Parties: Customers/Suppliers (single table: Party) ----
# def _build_customers_or_suppliers_dropdown(
#     session: Session,
#     ctx: AffiliationContext,
#     params: Mapping[str, Any],
#     role: PartyRoleEnum,
# ):
#     co_id = _co(ctx)
#     if not co_id:
#         return select(Party.id.label("value")).where(literal(False))
#
#     include_inactive = str(params.get("include_inactive", "")).lower() in {"1", "true", "yes"}
#     explicit_branch_id = params.get("branch_id")  # optional, explicit filter
#     query_text = params.get("q") or params.get("query") or ""
#
#     q = (
#         select(
#             Party.id.label("value"),
#             Party.name.label("label"),
#             Party.code.label("code"),
#             Party.phone.label("phone"),
#         )
#         .where(
#             Party.company_id == co_id,
#             Party.role == role,
#         )
#     )
#
#     # status filter
#     if not include_inactive:
#         q = q.where(Party.status == StatusEnum.ACTIVE)
#
#     # branch scoping
#     if explicit_branch_id is not None:
#         try:
#             q = q.where(Party.branch_id == int(explicit_branch_id))
#         except Exception:
#             return select(Party.id.label("value")).where(literal(False))
#     else:
#         # enforce tenant branch visibility when not company-wide
#         if not _has_company_wide_access(ctx):
#             br_ids = _br_ids(ctx)
#             if br_ids:
#                 # allow company-wide parties (NULL) + ones in the user's branches
#                 q = q.where(or_(Party.branch_id.is_(None), Party.branch_id.in_(br_ids)))
#             else:
#                 # no branches on ctx and not company-wide → hide everything
#                 return select(Party.id.label("value")).where(literal(False))
#
#     # search (AND-of-OR across tokens, ERP-ish)
#     if query_text:
#         clause = _and_of_or_terms(
#             cols=(Party.name, Party.code, Party.phone),
#             query=query_text,
#         )
#         if clause is not None:
#             q = q.where(clause)
#
#     return q.order_by(func.lower(Party.name).asc(), Party.code.asc())
#
# # ---- Employees (own table; optionally branch-restricted via primary active assignment) ----
# def _build_employees_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
#     co_id = _co(ctx)
#     if not co_id:
#         return select(Employee.id.label("value")).where(literal(False))
#
#     include_inactive = str(params.get("include_inactive", "")).lower() in {"1", "true", "yes"}
#     explicit_branch_id = params.get("branch_id")
#     query_text = params.get("q") or params.get("query") or ""
#
#     base = (
#         select(
#             Employee.id.label("value"),
#             Employee.full_name.label("label"),
#             Employee.code.label("code"),
#             Employee.phone_number.label("phone"),
#         )
#         .where(Employee.company_id == co_id)
#     )
#
#     if not include_inactive:
#         base = base.where(Employee.status == StatusEnum.ACTIVE)
#
#     # branch scoping
#     if explicit_branch_id is not None:
#         # only employees whose primary active assignment is in the given branch
#         EA = EmployeeAssignment
#         base = (
#             base.join(
#                 EA,
#                 and_(
#                     EA.employee_id == Employee.id,
#                     EA.company_id == co_id,
#                     EA.is_primary.is_(True),
#                     EA.to_date.is_(None),
#                     EA.branch_id == int(explicit_branch_id),
#                 ),
#             )
#         )
#     else:
#         if not _has_company_wide_access(ctx):
#             br_ids = _br_ids(ctx)
#             if br_ids:
#                 EA = EmployeeAssignment
#                 base = base.join(
#                     EA,
#                     and_(
#                         EA.employee_id == Employee.id,
#                         EA.company_id == co_id,
#                         EA.is_primary.is_(True),
#                         EA.to_date.is_(None),
#                         EA.branch_id.in_(br_ids),
#                     ),
#                 )
#             else:
#                 return select(Employee.id.label("value")).where(literal(False))
#
#     # search
#     if query_text:
#         clause = _and_of_or_terms(
#             cols=(Employee.full_name, Employee.code, Employee.phone_number),
#             query=query_text,
#         )
#         if clause is not None:
#             base = base.where(clause)
#
#     # distinct in case of joins
#     base = base.distinct(Employee.id).order_by(func.lower(Employee.full_name).asc(), Employee.code.asc())
#     return base
#
# # ---- Shareholders placeholder (replace when model exists) ----
# def _build_shareholders_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
#     return select(literal(None).label("value")).where(literal(False))
#
# def build_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
#     """
#     Unified party dropdown.
#     Params:
#       - party_type / party_kind / role: "Customer" | "Supplier" | "Employee" | "Shareholder" (required)
#       - q / query: tokenized search on name/code/phone (AND across tokens)
#       - branch_id: optional explicit branch filter
#       - include_inactive: bool-like, default False
#     """
#     kind = _normalize_party_type(
#         params.get("party_type") or params.get("party_kind") or params.get("role")
#     )
#     if kind == "Customer":
#         return _build_customers_or_suppliers_dropdown(session, ctx, params, PartyRoleEnum.CUSTOMER)
#     if kind == "Supplier":
#         return _build_customers_or_suppliers_dropdown(session, ctx, params, PartyRoleEnum.SUPPLIER)
#     if kind == "Employee":
#         return _build_employees_dropdown(session, ctx, params)
#     if kind == "Shareholder":
#         return _build_shareholders_dropdown(session, ctx, params)
#
#     # Unknown kind → empty quickly
#     return select(literal(None).label("value")).where(literal(False))


def build_accounts_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All Accounts (Chart of Accounts) for the current company.

    Defaults:
      - Returns leaf accounts (is_group = False) by default (safer for posting).
      - Repository-level search (q) will match name/code via config.search_fields.

    Optional filters:
      - only_groups: 1/0 → only folders
      - only_leaves: 1/0 → only leaf accounts (default = 1)
      - parent_account_id: int → restrict to children of a parent
      - account_type: ASSET | LIABILITY | EQUITY | INCOME | EXPENSE

    Returns:
      value        : Account.id
      label        : Account.name
      code         : Account.code
      is_group     : bool
      account_type : Account.account_type
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
            Account.account_type.label("account_type"),
        )
        .where(
            Account.company_id == co_id,
            Account.enabled.is_(True),
        )
    )

    # Optional filters (applied here to keep behavior explicit)
    acct_type = params.get("account_type")
    if acct_type:
        q = q.where(Account.account_type == acct_type)

    parent_id = params.get("parent_account_id")
    if parent_id is not None:
        try:
            q = q.where(Account.parent_account_id == int(parent_id))
        except Exception:
            return select(Account.id.label("value")).where(literal(False))

    if only_groups and not only_leaves:
        q = q.where(Account.is_group.is_(True))
    elif only_leaves and not only_groups:
        q = q.where(Account.is_group.is_(False))

    # Sort by code then name (friendly, ERP-like)
    return q.order_by(Account.code.asc(), Account.name.asc())
