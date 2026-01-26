# app/application_reports/scripts/profit_loss.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text, bindparam

from app.security.rbac_effective import AffiliationContext
from app.application_reports.core.date_utils import parse_date_flex, format_date_for_display
from app.application_reports.core.accounting_utils import get_currency_precision

from app.application_accounting.chart_of_accounts.models import (
    Account,
    AccountTypeEnum,
    ReportTypeEnum,
    FiscalYear,
)

from app.application_reports.core.columns import (
    currency_column,
    data_column,
    int_column,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Period model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PeriodDef:
    fieldname: str
    label: str
    from_date: date
    to_date: date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return False


def _parse_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(
        d.day,
        [31,
         29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
    )
    return date(year, month, day)


def _sanitize_fieldname(label: str) -> str:
    import re
    base = label.strip().lower()
    base = re.sub(r"[^0-9a-z]+", "_", base).strip("_")
    return f"p_{base or 'period'}"


def _format_filters_for_output(filters: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(filters)
    for k in ("from_date", "to_date"):
        if out.get(k) and isinstance(out[k], (date, datetime)):
            out[k] = format_date_for_display(out[k])
    return out


def _resolve_cost_center_id(
    session: Session,
    company_id: int,
    branch_id: Optional[int],
    cost_center_value: Any,
) -> Optional[int]:
    """
    UI might send:
      - cost_center as ID (int / "12")
      - cost_center as Name (string)
    Resolve safely against cost_centers, limited to the company (and branch if provided).
    """
    if not cost_center_value:
        return None

    cc_id = _parse_int(cost_center_value)
    if cc_id:
        sql = """
            SELECT id
            FROM cost_centers
            WHERE id = :id
              AND company_id = :company_id
              AND enabled = TRUE
        """
        params: Dict[str, Any] = {"id": cc_id, "company_id": company_id}
        if branch_id:
            sql += " AND branch_id = :branch_id"
            params["branch_id"] = branch_id

        row = session.execute(text(sql), params).first()
        return int(row[0]) if row else None

    name = str(cost_center_value).strip()
    if not name:
        return None

    sql = """
        SELECT id
        FROM cost_centers
        WHERE company_id = :company_id
          AND name = :name
          AND enabled = TRUE
    """
    params = {"company_id": company_id, "name": name}
    if branch_id:
        sql += " AND branch_id = :branch_id"
        params["branch_id"] = branch_id

    row = session.execute(text(sql), params).first()
    return int(row[0]) if row else None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def get_filters() -> List[Dict[str, Any]]:
    return [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
        {"fieldname": "branch_id", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "cost_center", "label": "Cost Center", "fieldtype": "Link", "options": "Cost Center"},

        {
            "fieldname": "basis",
            "label": "Based On",
            "fieldtype": "Select",
            "options": "Date Range\nFiscal Year",
            "default": "Date Range",
            "required": True,
        },

        {"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
        {"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"},

        {"fieldname": "from_fiscal_year", "label": "From Fiscal Year", "fieldtype": "Link", "options": "Fiscal Year"},
        {"fieldname": "to_fiscal_year", "label": "To Fiscal Year", "fieldtype": "Link", "options": "Fiscal Year"},

        {
            "fieldname": "periodicity",
            "label": "Periodicity",
            "fieldtype": "Select",
            "options": "Yearly\nQuarterly\nMonthly",
            "default": "Yearly",
            "required": True,
        },

        {"fieldname": "accumulated_values", "label": "Show Accumulated Values", "fieldtype": "Check", "default": 0},
        {"fieldname": "include_closing_entries", "label": "Include Period Closing Entries", "fieldtype": "Check", "default": 1},
        {"fieldname": "show_zero_rows", "label": "Show Zero Accounts", "fieldtype": "Check", "default": 0},

        # Optional convenience
        {"fieldname": "consolidate_columns", "label": "Show Only Last Period", "fieldtype": "Check", "default": 0},
        {"fieldname": "hide_group_amounts", "label": "Hide Group Amounts", "fieldtype": "Check", "default": 0},

        # Optional: show Total column (many users expect it)
        {"fieldname": "show_total_column", "label": "Show Total Column", "fieldtype": "Check", "default": 1},
    ]


# ---------------------------------------------------------------------------
# Period building
# ---------------------------------------------------------------------------

def _build_periods_for_date_range(from_date: date, to_date: date, periodicity: str) -> List[PeriodDef]:
    periodicity = (periodicity or "Yearly").strip().lower()
    periods: List[PeriodDef] = []

    if periodicity == "yearly":
        for year in range(from_date.year, to_date.year + 1):
            p_from = from_date if year == from_date.year else date(year, 1, 1)
            p_to = to_date if year == to_date.year else date(year, 12, 31)
            label = str(year)
            periods.append(PeriodDef(_sanitize_fieldname(label), label, p_from, p_to))
        return periods

    cur = from_date
    while cur <= to_date:
        if periodicity == "quarterly":
            span = 3
            q = ((cur.month - 1) // 3) + 1
            label = f"{cur.year}-Q{q}"
        else:
            span = 1
            label = cur.strftime("%b-%Y")

        next_start = _add_months(cur, span)
        p_to = min(next_start - timedelta(days=1), to_date)
        periods.append(PeriodDef(_sanitize_fieldname(label), label, cur, p_to))
        cur = p_to + timedelta(days=1)

    return periods


def _build_periods_for_fiscal_year(
    session: Session,
    company_id: int,
    from_fy_name: str,
    to_fy_name: str,
    periodicity: str,
) -> Tuple[List[PeriodDef], date, date]:
    periodicity = (periodicity or "Yearly").strip().lower()

    f1 = session.query(FiscalYear).filter(FiscalYear.company_id == company_id, FiscalYear.name == from_fy_name).one_or_none()
    f2 = session.query(FiscalYear).filter(FiscalYear.company_id == company_id, FiscalYear.name == to_fy_name).one_or_none()
    if not f1 or not f2:
        raise ValueError("Invalid Fiscal Year range selected.")

    if f1.start_date > f2.start_date:
        f1, f2 = f2, f1

    fy_list = (
        session.query(FiscalYear)
        .filter(
            FiscalYear.company_id == company_id,
            FiscalYear.start_date >= f1.start_date,
            FiscalYear.end_date <= f2.end_date,
        )
        .order_by(FiscalYear.start_date)
        .all()
    )
    if not fy_list:
        raise ValueError("No Fiscal Years found in the selected range.")

    overall_min = fy_list[0].start_date.date()
    overall_max = fy_list[-1].end_date.date()
    periods: List[PeriodDef] = []

    for fy in fy_list:
        fy_start = fy.start_date.date()
        fy_end = fy.end_date.date()

        if periodicity == "yearly":
            label = fy.name
            periods.append(PeriodDef(_sanitize_fieldname(label), label, fy_start, fy_end))
            continue

        cur = fy_start
        while cur <= fy_end:
            if periodicity == "quarterly":
                span = 3
                q = ((cur.month - 1) // 3) + 1
                label = f"{fy.name} Q{q}"
            else:
                span = 1
                label = f"{cur.strftime('%b-%Y')} ({fy.name})"

            next_start = _add_months(cur, span)
            p_to = min(next_start - timedelta(days=1), fy_end)
            periods.append(PeriodDef(_sanitize_fieldname(label), label, cur, p_to))
            cur = p_to + timedelta(days=1)

    return periods, overall_min, overall_max


def _build_periods(filters: Dict[str, Any], session: Session, company_id: int) -> Tuple[List[PeriodDef], date, date]:
    basis = (filters.get("basis") or "Date Range").strip().lower()
    periodicity = (filters.get("periodicity") or "Yearly").strip()

    if basis.startswith("fiscal"):
        f1 = (filters.get("from_fiscal_year") or "").strip()
        f2 = (filters.get("to_fiscal_year") or "").strip()
        if not f1 or not f2:
            raise ValueError("From Fiscal Year and To Fiscal Year are required when Based On = Fiscal Year.")
        return _build_periods_for_fiscal_year(session, company_id, f1, f2, periodicity)

    to_d = parse_date_flex(filters.get("to_date")) or date.today()
    from_d = parse_date_flex(filters.get("from_date")) or date(to_d.year, 1, 1)
    periods = _build_periods_for_date_range(from_d, to_d, periodicity)
    if not periods:
        raise ValueError("No periods could be derived from the selected date range.")
    return periods, periods[0].from_date, periods[-1].to_date


# ---------------------------------------------------------------------------
# Accounts + GL loading
# ---------------------------------------------------------------------------

def _load_pl_accounts(session: Session, company_id: int) -> List[Account]:
    """
    Your model only has INCOME and EXPENSE types for P&L.
    """
    return (
        session.query(Account)
        .filter(
            Account.company_id == company_id,
            Account.enabled.is_(True),
            Account.report_type == ReportTypeEnum.PROFIT_AND_LOSS,
            Account.account_type.in_([AccountTypeEnum.INCOME, AccountTypeEnum.EXPENSE]),
        )
        .all()
    )


def _load_pl_gl_daily(
    session: Session,
    company_id: int,
    account_ids: List[int],
    overall_from: date,
    overall_to: date,
    include_closing: bool,
    branch_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Load daily sums per account (fast and safe).
    Filters branch + cost center in SQL (prevents wrong-branch leakage).
    """
    if not account_ids:
        return []

    sql = """
        SELECT
            gle.account_id,
            gle.posting_date::date AS posting_date,
            SUM(gle.debit)  AS debit,
            SUM(gle.credit) AS credit
        FROM general_ledger_entries gle
        JOIN journal_entries je ON je.id = gle.journal_entry_id
        WHERE gle.company_id = :company_id
          AND gle.posting_date::date >= :from_date
          AND gle.posting_date::date <= :to_date
          AND gle.account_id IN :account_ids
          AND je.doc_status = 'SUBMITTED'
    """

    params: Dict[str, Any] = {
        "company_id": company_id,
        "from_date": overall_from,
        "to_date": overall_to,
        "account_ids": account_ids,
    }

    if branch_id:
        sql += " AND gle.branch_id = :branch_id"
        params["branch_id"] = branch_id

    if cost_center_id:
        sql += " AND gle.cost_center_id = :cost_center_id"
        params["cost_center_id"] = cost_center_id

    if not include_closing:
        # be tolerant to stored enum values
        sql += " AND je.entry_type::text NOT IN ('Closing', 'CLOSING')"

    sql += """
        GROUP BY gle.account_id, gle.posting_date::date
        ORDER BY gle.account_id, posting_date
    """

    stmt = text(sql).bindparams(bindparam("account_ids", expanding=True))
    rows = session.execute(stmt, params).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tree helpers + Cost-of-sales heuristic
# ---------------------------------------------------------------------------

_COS_KEYWORDS = (
    "cost of sales",
    "cost of goods",
    "cost of goods sold",
    "cogs",
    "direct cost",
    "direct expense",
    "cost_of_sales",
    "cost_of_goods",
)

def _looks_like_cost_of_sales(name_or_code: str) -> bool:
    s = (name_or_code or "").strip().lower()
    if not s:
        return False
    return any(k in s for k in _COS_KEYWORDS)

def _is_cost_of_sales_account(acc: Account, account_map: Dict[int, Account]) -> bool:
    """
    Since your AccountTypeEnum has only INCOME/EXPENSE, we detect Cost of Sales by:
      - account name/code contains COS keywords, OR
      - any parent in the tree contains COS keywords.
    """
    if acc.account_type != AccountTypeEnum.EXPENSE:
        return False

    if _looks_like_cost_of_sales(acc.name) or _looks_like_cost_of_sales(acc.code):
        return True

    # Check parents
    seen = set()
    pid = acc.parent_account_id
    while pid and pid not in seen:
        seen.add(pid)
        parent = account_map.get(pid)
        if not parent:
            break
        if _looks_like_cost_of_sales(parent.name) or _looks_like_cost_of_sales(parent.code):
            return True
        pid = parent.parent_account_id

    return False


def _build_account_tree(accounts: List[Account]) -> Tuple[Dict[int, Account], Dict[Optional[int], List[int]], Dict[int, int], List[int]]:
    account_map: Dict[int, Account] = {a.id: a for a in accounts}
    children: Dict[Optional[int], List[int]] = defaultdict(list)

    for a in accounts:
        children[a.parent_account_id].append(a.id)

    depth: Dict[int, int] = {}
    roots = [a.id for a in accounts if a.parent_account_id not in account_map]

    # Income first, then Expense, then code
    def root_key(acc_id: int) -> Tuple[int, str]:
        a = account_map[acc_id]
        order = {AccountTypeEnum.INCOME: 0, AccountTypeEnum.EXPENSE: 1}.get(a.account_type, 9)
        return (order, a.code or "")

    roots.sort(key=root_key)

    def dfs(acc_id: int, lvl: int) -> None:
        depth[acc_id] = lvl
        for cid in sorted(children.get(acc_id, []), key=lambda x: (account_map[x].code or "")):
            dfs(cid, lvl + 1)

    for rid in roots:
        dfs(rid, 0)

    return account_map, children, depth, roots


# ---------------------------------------------------------------------------
# P&L math (clean sign logic)
# ---------------------------------------------------------------------------

def _daily_amount_for_pl(acc_type: AccountTypeEnum, debit: float, credit: float) -> float:
    """
    ERP sign convention for display:
      - Income shown positive when credits exceed debits:  credit - debit
      - Expense shown positive when debits exceed credits: debit - credit
    """
    if acc_type == AccountTypeEnum.INCOME:
        return (credit - debit)
    return (debit - credit)


def _compute_period_amounts_fast(
    gl_rows: List[Dict[str, Any]],
    periods: List[PeriodDef],
    account_map: Dict[int, Account],
    accumulated_values: bool,
) -> Dict[int, Dict[str, float]]:
    """
    Fast calculation:
      - accumulated: running sum to each period.to_date
      - non-accumulated: sum within each period window
    """
    by_acc: Dict[int, List[Tuple[date, float]]] = defaultdict(list)

    for r in gl_rows:
        acc_id = int(r["account_id"])
        acc = account_map.get(acc_id)
        if not acc:
            continue

        d = r["posting_date"]
        if isinstance(d, datetime):
            d = d.date()

        debit = float(r.get("debit") or 0.0)
        credit = float(r.get("credit") or 0.0)
        amt = _daily_amount_for_pl(acc.account_type, debit, credit)

        by_acc[acc_id].append((d, amt))

    for acc_id in by_acc:
        by_acc[acc_id].sort(key=lambda x: x[0])

    balances: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for acc_id, entries in by_acc.items():
        i = 0
        n = len(entries)

        if accumulated_values:
            running = 0.0
            for p in periods:
                cutoff = p.to_date
                while i < n and entries[i][0] <= cutoff:
                    running += entries[i][1]
                    i += 1
                balances[acc_id][p.fieldname] = running
        else:
            for p in periods:
                # skip before p.from_date
                while i < n and entries[i][0] < p.from_date:
                    i += 1
                s = 0.0
                j = i
                while j < n and entries[j][0] <= p.to_date:
                    s += entries[j][1]
                    j += 1
                balances[acc_id][p.fieldname] = s
                i = j

    return balances


def _rollup_groups(
    accounts: List[Account],
    children: Dict[Optional[int], List[int]],
    depth: Dict[int, int],
    periods: List[PeriodDef],
    base_balances: Dict[int, Dict[str, float]],
) -> Dict[int, Dict[str, float]]:
    balances: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for acc_id, per in base_balances.items():
        for k, v in per.items():
            balances[acc_id][k] = float(v or 0.0)

    sorted_accounts = sorted(accounts, key=lambda a: depth.get(a.id, 0), reverse=True)
    for acc in sorted_accounts:
        if not acc.is_group:
            continue
        for p in periods:
            total = 0.0
            for cid in children.get(acc.id, []):
                total += float(balances[cid].get(p.fieldname, 0.0) or 0.0)
            balances[acc.id][p.fieldname] = total

    return balances


def _compute_totals(
    accounts: List[Account],
    balances: Dict[int, Dict[str, float]],
    periods: List[PeriodDef],
    account_map: Dict[int, Account],
) -> Dict[str, Dict[str, float]]:
    """
    Totals based on leaf accounts only.
    Adds Cost of Sales totals if detectable (heuristic).
    """
    total_income: Dict[str, float] = defaultdict(float)
    total_expense: Dict[str, float] = defaultdict(float)
    total_cost_of_sales: Dict[str, float] = defaultdict(float)

    for acc in accounts:
        if acc.is_group:
            continue
        acc_bal = balances.get(acc.id, {})
        for p in periods:
            v = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
            if acc.account_type == AccountTypeEnum.INCOME:
                total_income[p.fieldname] += v
            else:
                total_expense[p.fieldname] += v
                if _is_cost_of_sales_account(acc, account_map):
                    total_cost_of_sales[p.fieldname] += v

    gross_profit: Dict[str, float] = {}
    net_profit: Dict[str, float] = {}
    net_margin: Dict[str, float] = {}

    for p in periods:
        k = p.fieldname
        inc = float(total_income.get(k, 0.0) or 0.0)
        exp = float(total_expense.get(k, 0.0) or 0.0)
        cos = float(total_cost_of_sales.get(k, 0.0) or 0.0)

        gross_profit[k] = inc - cos
        net_profit[k] = inc - exp
        net_margin[k] = (net_profit[k] / inc * 100.0) if inc else 0.0

    return {
        "total_income": dict(total_income),
        "total_expense": dict(total_expense),
        "total_cost_of_sales": dict(total_cost_of_sales),
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "net_margin_percent": dict(net_margin),
    }


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    filters = filters or {}
    to_d = parse_date_flex(filters.get("to_date")) or date.today()
    from_d = parse_date_flex(filters.get("from_date")) or date(to_d.year, 1, 1)
    periodicity = (filters.get("periodicity") or "Yearly").strip()
    periods = _build_periods_for_date_range(from_d, to_d, periodicity)

    precision = int(get_currency_precision() or 2)
    show_total = _coerce_bool(filters.get("show_total_column", True))

    cols: List[Dict[str, Any]] = [
        data_column("account", "Account", 260),
        int_column("indent", "Indent", 60),
        data_column("account_code", "Account Code", 110),
        data_column("root_type", "Root Type", 110),
    ]
    for p in periods:
        cols.append(currency_column(p.fieldname, p.label, precision=precision))
    if show_total:
        cols.append(currency_column("total", "Total", precision=precision))
    return cols


# ---------------------------------------------------------------------------
# Main Report Class
# ---------------------------------------------------------------------------

class ProfitLossReport:
    @classmethod
    def get_filters(cls):
        return get_filters()

    @classmethod
    def get_columns(cls, filters=None):
        return get_columns(filters)

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        start = time.time()

        # 1) Normalize
        if not filters.get("company"):
            company_id_ctx = getattr(context, "company_id", None)
            if not company_id_ctx:
                raise ValueError("Company is required.")
            filters["company"] = int(company_id_ctx)

        company_id = int(filters["company"])
        branch_id = _parse_int(filters.get("branch_id"))
        include_closing = _coerce_bool(filters.get("include_closing_entries", True))
        show_zero_rows = _coerce_bool(filters.get("show_zero_rows", False))
        accumulated_values = _coerce_bool(filters.get("accumulated_values", False))
        show_only_last = _coerce_bool(filters.get("consolidate_columns", False))
        hide_group_amounts = _coerce_bool(filters.get("hide_group_amounts", False))
        show_total_col = _coerce_bool(filters.get("show_total_column", True))

        precision = int(get_currency_precision() or 2)
        tol = 10 ** (-(precision + 1))

        cost_center_id = _resolve_cost_center_id(
            session=session,
            company_id=company_id,
            branch_id=branch_id,
            cost_center_value=filters.get("cost_center"),
        )

        # 2) Periods
        periods, overall_from, overall_to = _build_periods(filters, session, company_id)
        if not periods:
            return {
                "columns": get_columns(filters),
                "data": [],
                "filters": _format_filters_for_output(filters),
                "summary": {},
                "chart": None,
                "report_name": "Profit & Loss",
                "execution_time": round(time.time() - start, 4),
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            }

        if show_only_last:
            periods = [periods[-1]]

        # 3) Accounts
        accounts = _load_pl_accounts(session, company_id)
        if not accounts:
            return {
                "columns": self._build_columns(periods, precision, show_total_col),
                "data": [],
                "filters": _format_filters_for_output(filters),
                "summary": {"periods": [], "totals": {}, "header": {}},
                "chart": None,
                "report_name": "Profit & Loss",
                "execution_time": round(time.time() - start, 4),
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            }

        account_ids = [a.id for a in accounts]

        # 4) GL rows (filtered in SQL)
        gl_rows = _load_pl_gl_daily(
            session=session,
            company_id=company_id,
            account_ids=account_ids,
            overall_from=overall_from,
            overall_to=overall_to,
            include_closing=include_closing,
            branch_id=branch_id,
            cost_center_id=cost_center_id,
        )

        # 5) Compute balances
        account_map, children, depth, roots = _build_account_tree(accounts)
        base_balances = _compute_period_amounts_fast(gl_rows, periods, account_map, accumulated_values)
        balances = _rollup_groups(accounts, children, depth, periods, base_balances)
        totals = _compute_totals(accounts, balances, periods, account_map)

        # 6) Build rows
        rows: List[Dict[str, Any]] = []

        def calc_total_for_row(row: Dict[str, Any]) -> float:
            if not show_total_col:
                return 0.0

            if accumulated_values:
                # For accumulated values, "Total" should be last period value (not sum of running totals).
                last_key = periods[-1].fieldname
                v = row.get(last_key)
                return float(v or 0.0)

            # Non-accumulated: sum selected periods
            s = 0.0
            for p in periods:
                v = row.get(p.fieldname)
                if isinstance(v, (int, float)):
                    s += float(v)
            return s

        def walk(acc_id: int) -> None:
            acc = account_map[acc_id]
            indent = depth.get(acc_id, 0)

            row: Dict[str, Any] = {
                "account": acc.name,
                "account_code": acc.code,
                "indent": indent,
                "root_type": acc.account_type.value,  # Income / Expense
                "is_group": acc.is_group,
                "account_id": acc.id,
            }

            acc_bal = balances.get(acc_id, {})
            for p in periods:
                v = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
                if acc.is_group and hide_group_amounts:
                    row[p.fieldname] = None
                else:
                    row[p.fieldname] = round(v, precision)

            # filter leaf zeros
            if not show_zero_rows and not acc.is_group:
                all_zero = True
                for p in periods:
                    vv = row.get(p.fieldname)
                    if isinstance(vv, (int, float)) and abs(float(vv)) > tol:
                        all_zero = False
                        break
                if all_zero:
                    return

            if show_total_col:
                row["total"] = round(calc_total_for_row(row), precision)

            rows.append(row)

            for cid in sorted(children.get(acc_id, []), key=lambda x: (account_map[x].code or "")):
                walk(cid)

        for rid in roots:
            walk(rid)

        # 7) Add ERP-style subtotal rows
        def add_summary_row(label: str, values: Dict[str, float], root_type: str) -> None:
            r: Dict[str, Any] = {
                "account": label,
                "account_code": "",
                "indent": 0,
                "root_type": root_type,
                "is_group": False,
                "account_id": None,
            }
            for p in periods:
                r[p.fieldname] = round(float(values.get(p.fieldname, 0.0) or 0.0), precision)

            if show_total_col:
                r["total"] = round(calc_total_for_row(r), precision)

            rows.append(r)

        add_summary_row("Total Income", totals["total_income"], "Income")

        # Only show Gross Profit + Cost of Sales if Cost of Sales is actually detected
        has_cos = any(abs(float(totals["total_cost_of_sales"].get(p.fieldname, 0.0) or 0.0)) > tol for p in periods)
        if has_cos:
            add_summary_row("Total Cost of Sales", totals["total_cost_of_sales"], "Expense")
            add_summary_row("Gross Profit", totals["gross_profit"], "Summary")

        add_summary_row("Total Expense", totals["total_expense"], "Expense")
        add_summary_row("Net Profit / Loss", totals["net_profit"], "Summary")

        # 8) Header summary
        last = periods[-1]
        k = last.fieldname

        summary = {
            "periods": [
                {"fieldname": p.fieldname, "label": p.label, "from_date": p.from_date.isoformat(), "to_date": p.to_date.isoformat()}
                for p in periods
            ],
            "totals": totals,
            "header": {
                "total_income": round(float(totals["total_income"].get(k, 0.0) or 0.0), precision),
                "total_expense": round(float(totals["total_expense"].get(k, 0.0) or 0.0), precision),
                "net_profit": round(float(totals["net_profit"].get(k, 0.0) or 0.0), precision),
                "net_margin_percent": round(float(totals["net_margin_percent"].get(k, 0.0) or 0.0), precision),
                "as_on_label": last.label,
            },
        }
        if has_cos:
            summary["header"]["total_cost_of_sales"] = round(float(totals["total_cost_of_sales"].get(k, 0.0) or 0.0), precision)
            summary["header"]["gross_profit"] = round(float(totals["gross_profit"].get(k, 0.0) or 0.0), precision)

        chart = self._build_chart(periods, totals, precision, accumulated_values, has_cos)

        return {
            "columns": self._build_columns(periods, precision, show_total_col),
            "data": rows,
            "filters": _format_filters_for_output(filters),
            "summary": summary,
            "chart": chart,
            "report_name": "Profit & Loss",
            "execution_time": round(time.time() - start, 4),
            "total_count": len(rows),
            "has_more": False,
            "next_cursor": None,
        }

    def _build_columns(self, periods: List[PeriodDef], precision: int, show_total: bool) -> List[Dict[str, Any]]:
        cols: List[Dict[str, Any]] = [
            data_column("account", "Account", 260),
            int_column("indent", "Indent", 60),
            data_column("account_code", "Account Code", 110),
            data_column("root_type", "Root Type", 110),
        ]
        for p in periods:
            cols.append(currency_column(p.fieldname, p.label, precision=precision))
        if show_total:
            cols.append(currency_column("total", "Total", precision=precision))
        return cols

    def _build_chart(
        self,
        periods: List[PeriodDef],
        totals: Dict[str, Dict[str, float]],
        precision: int,
        accumulated_values: bool,
        has_cost_of_sales: bool,
    ) -> Optional[Dict[str, Any]]:
        if not periods:
            return None

        labels = [p.label for p in periods]

        def series(key: str) -> List[float]:
            return [round(float(totals.get(key, {}).get(p.fieldname, 0.0) or 0.0), precision) for p in periods]

        income = series("total_income")
        expense = series("total_expense")
        net = series("net_profit")

        if all(v == 0 for v in (income + expense + net)):
            return None

        datasets = [
            {"name": "Income", "values": income},
            {"name": "Expense", "values": expense},
            {"name": "Net Profit / Loss", "values": net},
        ]

        if has_cost_of_sales:
            datasets.insert(2, {"name": "Cost of Sales", "values": series("total_cost_of_sales")})

        return {
            "type": "line" if accumulated_values else "bar",
            "title": "Profit & Loss Overview",
            "data": {"labels": labels, "datasets": datasets},
            "height": 300,
        }
