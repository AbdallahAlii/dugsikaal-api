
# seed_data/coa/seeder.py
from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Your models / enums
from app.application_accounting.chart_of_accounts.models import (
    Account,
    AccountBalance,
    AccountTypeEnum,
    ReportTypeEnum,
    DebitOrCreditEnum,
)
# ❌ removed DocStatusEnum import (no longer used with enabled boolean)
from app.application_org.models.company import Company

from .data import DEFAULT_ACCOUNTS, ROOT_PLACEHOLDER

logger = logging.getLogger(__name__)


# ---------------- helpers ----------------
def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters):
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False
    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    try:
        db.flush([obj])
        return obj, True
    except IntegrityError:
        db.rollback()
        return db.scalar(select(model).filter_by(**filters)), False


def _enum_from_str(enum_cls, value: Optional[str]):
    """Map string like 'ASSET' → AccountTypeEnum.ASSET. Raise on invalid values."""
    if value is None:
        return None
    try:
        return enum_cls[value.upper()]
    except KeyError as exc:
        raise ValueError(f"Invalid {enum_cls.__name__} value: {value!r}") from exc


def _derive_report_type(account_type: AccountTypeEnum) -> ReportTypeEnum:
    """Income/Expense → P&L; others → Balance Sheet."""
    return (
        ReportTypeEnum.PROFIT_AND_LOSS
        if account_type in (AccountTypeEnum.INCOME, AccountTypeEnum.EXPENSE)
        else ReportTypeEnum.BALANCE_SHEET
    )


def _derive_normal_balance(account_type: AccountTypeEnum) -> DebitOrCreditEnum:
    """Assets/Expenses → Debit; Liabilities/Equity/Income → Credit."""
    return (
        DebitOrCreditEnum.DEBIT
        if account_type in (AccountTypeEnum.ASSET, AccountTypeEnum.EXPENSE)
        else DebitOrCreditEnum.CREDIT
    )


def _guess_company_abbr(company: Company) -> Optional[str]:
    """Pick a stable short code from Company; prefer prefix field; fall back to initials."""
    if getattr(company, "prefix", None):
        p = (company.prefix or "").strip().upper()
        if p:
            return p
    name = getattr(company, "name", None) or getattr(company, "legal_name", None)
    if not name:
        return None
    parts = [p for p in name.replace("&", " ").split() if p and p[0].isalnum()]
    abbr = "".join(p[0] for p in parts[:3]).upper()
    return abbr or None


def _resolve_root_code(company: Company, explicit_root_code: Optional[str], use_company_prefix: bool) -> str:
    if explicit_root_code:
        return explicit_root_code
    if use_company_prefix:
        abbr = _guess_company_abbr(company)
        if abbr:
            return f"{abbr}-COA"
    return "COA"


# ---------------- public entrypoint ----------------
def seed_chart_of_accounts(
    db: Session,
    company_id: int,
    *,
    root_code: Optional[str] = None,
    root_name: str = "Root Chart of Accounts",
    use_company_prefix_for_root: bool = True,
    set_status_submitted: bool = True,   # kept for signature compatibility (ignored for enabled)
    create_balances_for_leaves: bool = True,
) -> None:
    """
    Idempotent COA seed for a given company:
      - Creates or updates accounts by (company_id, code)
      - Dynamic root code per company (PREFIX-COA or 'COA')
      - Auto-derives report_type & normal balance
      - Auto-creates AccountBalance rows for non-group accounts (optional)

    Note: uses Frappe-style boolean 'enabled' instead of docstatus; all seeded accounts are enabled.
    """
    company = db.scalar(select(Company).where(Company.id == company_id))
    if not company:
        logger.error("Company id=%s not found; skipping COA seeding.", company_id)
        return

    root_code_resolved = _resolve_root_code(company, root_code, use_company_prefix_for_root)
    root_name_resolved = f"{root_name} ({company.name})" if company.name else root_name

    logger.info("🚀 COA seed start: company_id=%s root=%s", company_id, root_code_resolved)

    # Ensure root exists
    root_defaults = dict(
        name=root_name_resolved,
        parent_account_id=None,
        is_group=True,
        account_type=AccountTypeEnum.ASSET,           # to satisfy NOT NULL constraints
        report_type=ReportTypeEnum.BALANCE_SHEET,
        debit_or_credit=DebitOrCreditEnum.DEBIT,
        enabled=True,                                  # ← use enabled boolean
    )
    root, _ = _get_or_create(
        db,
        Account,
        company_id=company_id,
        code=root_code_resolved,
        defaults=root_defaults,
    )

    # Build an in-memory index (existing by code)
    existing = db.scalars(select(Account).where(Account.company_id == company_id)).all()
    code_to_id: Dict[str, int] = {a.code: int(a.id) for a in existing}
    code_to_id[root_code_resolved] = int(root.id)

    created, updated, balances_created = 0, 0, 0

    for row in DEFAULT_ACCOUNTS:
        code: str = row["code"]
        parent_code: Optional[str] = row.get("parent_code")
        is_group: bool = bool(row.get("is_group"))

        if parent_code == ROOT_PLACEHOLDER:
            parent_code = root_code_resolved

        # Resolve parent id
        parent_id: Optional[int] = None
        if parent_code:
            parent_id = code_to_id.get(parent_code)
            if not parent_id:
                # Try DB (safe for re-runs even if order changed)
                parent_id = db.scalar(
                    select(Account.id).where(Account.company_id == company_id, Account.code == parent_code)
                )
                if not parent_id:
                    raise ValueError(
                        f"Parent code {parent_code!r} not found before creating {code!r}. "
                        "Check DEFAULT_ACCOUNTS parent ordering."
                    )

        # Enums
        atype = _enum_from_str(AccountTypeEnum, row.get("account_type"))
        if atype is None:
            raise ValueError(f"Row {code}: account_type is required")

        rtype = _derive_report_type(atype)
        normal_balance = _derive_normal_balance(atype)

        # Upsert
        acc, was_created = _get_or_create(
            db,
            Account,
            company_id=company_id,
            code=code,
            defaults=dict(
                name=row["name"],
                parent_account_id=parent_id,
                account_type=atype,
                report_type=rtype,
                is_group=is_group,
                debit_or_credit=normal_balance,
                enabled=True,  # ← new accounts seeded as enabled
            ),
        )
        if was_created:
            created += 1
        else:
            changed = False
            if acc.name != row["name"]:
                acc.name = row["name"]; changed = True
            if acc.parent_account_id != parent_id:
                acc.parent_account_id = parent_id; changed = True
            if acc.account_type != atype:
                acc.account_type = atype; changed = True
                acc.report_type = _derive_report_type(atype)
                acc.debit_or_credit = _derive_normal_balance(atype)
            if bool(acc.is_group) != is_group:
                acc.is_group = is_group; changed = True
            # Ensure enabled (we no longer use docstatus)
            if not bool(getattr(acc, "enabled", True)):
                acc.enabled = True; changed = True
            if changed:
                updated += 1

        # Cache for children
        code_to_id[code] = int(acc.id)

        # Ensure AccountBalance for leaves
        if create_balances_for_leaves and not acc.is_group:
            _, bal_created = _get_or_create(
                db,
                AccountBalance,
                account_id=acc.id,
                defaults=dict(total_debit=0.0, total_credit=0.0, current_balance=0.0),
            )
            if bal_created:
                balances_created += 1

    db.commit()
    logger.info(
        "🎉 COA seed complete (company_id=%s): created=%d, updated=%d, balances_created=%d",
        company_id, created, updated, balances_created
    )
