# app/application_reports/scripts/balance_sheet.py
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

from app.application_reports.core.columns import currency_column, data_column, int_column

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


def _resolve_cost_center_id(
    session: Session,
    company_id: int,
    branch_id: Optional[int],
    cost_center_value: Any,
) -> Optional[int]:
    """
    Your UI might send:
      - cost_center as ID (int/string)
      - cost_center as name (string)
    We resolve both safely.
    """
    if not cost_center_value:
        return None

    # Numeric ID path
    cc_id = _parse_int(cost_center_value)
    if cc_id:
        # verify it belongs to this company (+ optionally branch)
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

    # Name path
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

        # Behavior
        {"fieldname": "include_closing_entries", "label": "Include Period Closing Entries", "fieldtype": "Check", "default": 1},
        {"fieldname": "show_zero_rows", "label": "Show Zero Balance Accounts", "fieldtype": "Check", "default": 0},
        {"fieldname": "hide_group_amounts", "label": "Hide Group Amounts", "fieldtype": "Check", "default": 0},

        # In balance sheet, “consolidate columns” here means show just one column (last period)
        {"fieldname": "consolidate_columns", "label": "Show Only Last Period", "fieldtype": "Check", "default": 0},
    ]


def _format_filters_for_output(filters: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(filters)
    for k in ("from_date", "to_date"):
        if out.get(k) and isinstance(out[k], (date, datetime)):
            out[k] = format_date_for_display(out[k])
    return out


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

    f1 = session.query(FiscalYear).filter(
        FiscalYear.company_id == company_id,
        FiscalYear.name == from_fy_name,
    ).one_or_none()
    f2 = session.query(FiscalYear).filter(
        FiscalYear.company_id == company_id,
        FiscalYear.name == to_fy_name,
    ).one_or_none()
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
# Data loading
# ---------------------------------------------------------------------------

def _load_bs_accounts(session: Session, company_id: int) -> List[Account]:
    return (
        session.query(Account)
        .filter(
            Account.company_id == company_id,
            Account.enabled.is_(True),
            Account.report_type == ReportTypeEnum.BALANCE_SHEET,
            Account.account_type.in_([AccountTypeEnum.ASSET, AccountTypeEnum.LIABILITY, AccountTypeEnum.EQUITY]),
        )
        .all()
    )


def _load_gl_daily_net(
    session: Session,
    company_id: int,
    max_to_date: date,
    include_closing: bool,
    account_ids: List[int],
    branch_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Loads daily net movement per account with correct sign:
      Asset: (debit - credit)
      Liability/Equity: (credit - debit)

    Filters supported:
      - company_id (required)
      - account_ids (required; prevents pulling non-BS accounts)
      - posting_date <= max_to_date
      - only SUBMITTED journal entries
      - branch_id (optional)
      - cost_center_id (optional)
      - include_closing_entries: if False, exclude journal_entries.entry_type == 'Closing'
    """
    if not account_ids:
        return []

    sql = """
        SELECT
            gle.account_id,
            gle.posting_date::date AS posting_date,
            SUM(
                CASE
                    WHEN acc.account_type::text IN ('Asset','ASSET')
                        THEN (gle.debit - gle.credit)
                    ELSE (gle.credit - gle.debit)
                END
            ) AS amount
        FROM general_ledger_entries gle
        JOIN journal_entries je ON je.id = gle.journal_entry_id
        JOIN accounts acc ON acc.id = gle.account_id
        WHERE gle.company_id = :company_id
          AND gle.posting_date::date <= :max_to_date
          AND gle.account_id IN :account_ids
          AND acc.enabled = TRUE
          AND je.doc_status = 'SUBMITTED'
    """

    params: Dict[str, Any] = {
        "company_id": company_id,
        "max_to_date": max_to_date,
        "account_ids": account_ids,
    }

    if branch_id:
        sql += " AND gle.branch_id = :branch_id"
        params["branch_id"] = branch_id

    if cost_center_id:
        sql += " AND gle.cost_center_id = :cost_center_id"
        params["cost_center_id"] = cost_center_id

    if not include_closing:
        # Your enum value label is "Closing"
        sql += " AND je.entry_type::text <> 'Closing'"

    sql += """
        GROUP BY gle.account_id, gle.posting_date::date
        ORDER BY gle.account_id, posting_date
    """

    stmt = text(sql).bindparams(bindparam("account_ids", expanding=True))
    rows = session.execute(stmt, params).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tree + balances
# ---------------------------------------------------------------------------

def _build_account_tree(
    accounts: List[Account],
) -> Tuple[Dict[int, Account], Dict[Optional[int], List[int]], Dict[int, int], List[int]]:
    account_map: Dict[int, Account] = {a.id: a for a in accounts}
    children: Dict[Optional[int], List[int]] = defaultdict(list)

    for a in accounts:
        children[a.parent_account_id].append(a.id)

    depth: Dict[int, int] = {}
    roots = [a.id for a in accounts if a.parent_account_id not in account_map]

    def root_key(acc_id: int) -> Tuple[int, str]:
        a = account_map[acc_id]
        order = {
            AccountTypeEnum.ASSET: 0,
            AccountTypeEnum.LIABILITY: 1,
            AccountTypeEnum.EQUITY: 2,
        }.get(a.account_type, 9)
        return (order, a.code or "")

    roots.sort(key=root_key)

    def dfs(acc_id: int, lvl: int) -> None:
        depth[acc_id] = lvl
        for cid in sorted(children.get(acc_id, []), key=lambda x: (account_map[x].code or "")):
            dfs(cid, lvl + 1)

    for rid in roots:
        dfs(rid, 0)

    return account_map, children, depth, roots


def _compute_closing_balances_fast(
    gl_rows: List[Dict[str, Any]],
    periods: List[PeriodDef],
) -> Dict[int, Dict[str, float]]:
    """
    Fast closing-balance calculation:
    - group by account_id
    - within each account, cumulative sum across posting_date
    - fill each period.to_date in one pass
    """
    by_acc: Dict[int, List[Tuple[date, float]]] = defaultdict(list)
    for r in gl_rows:
        acc_id = int(r["account_id"])
        d = r["posting_date"]
        if isinstance(d, datetime):
            d = d.date()
        amt = float(r["amount"] or 0.0)
        by_acc[acc_id].append((d, amt))

    for acc_id in by_acc:
        by_acc[acc_id].sort(key=lambda x: x[0])

    periods_sorted = sorted(periods, key=lambda p: p.to_date)
    balances: Dict[int, Dict[str, float]] = defaultdict(dict)

    for acc_id, entries in by_acc.items():
        i = 0
        running = 0.0
        n = len(entries)

        for p in periods_sorted:
            cutoff = p.to_date
            while i < n and entries[i][0] <= cutoff:
                running += entries[i][1]
                i += 1
            balances[acc_id][p.fieldname] = running

    return balances


def _rollup_groups(
    accounts: List[Account],
    children: Dict[Optional[int], List[int]],
    depth: Dict[int, int],
    periods: List[PeriodDef],
    base_balances: Dict[int, Dict[str, float]],
) -> Dict[int, Dict[str, float]]:
    balances: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # seed
    for acc_id, per in base_balances.items():
        for k, v in per.items():
            balances[acc_id][k] = float(v or 0.0)

    # bottom-up (groups = sum(children))
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


def _compute_section_totals(
    accounts: List[Account],
    balances: Dict[int, Dict[str, float]],
    periods: List[PeriodDef],
) -> Dict[str, Dict[str, float]]:
    """
    Uses leaf accounts only to avoid double-counting.
    Signs are already normalized:
      Total Assets = sum(asset leaf balances)
      Total Liabilities = sum(liability leaf balances)
      Total Equity = sum(equity leaf balances)
      Provisional P/L = Assets - (Liabilities + Equity)
    """
    ta: Dict[str, float] = defaultdict(float)
    tl: Dict[str, float] = defaultdict(float)
    te: Dict[str, float] = defaultdict(float)

    for acc in accounts:
        if acc.is_group:
            continue
        acc_bal = balances.get(acc.id, {})
        for p in periods:
            v = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
            if acc.account_type == AccountTypeEnum.ASSET:
                ta[p.fieldname] += v
            elif acc.account_type == AccountTypeEnum.LIABILITY:
                tl[p.fieldname] += v
            elif acc.account_type == AccountTypeEnum.EQUITY:
                te[p.fieldname] += v

    ppl: Dict[str, float] = {}
    for p in periods:
        ppl[p.fieldname] = float(ta.get(p.fieldname, 0.0) - (tl.get(p.fieldname, 0.0) + te.get(p.fieldname, 0.0)))

    return {
        "total_assets": dict(ta),
        "total_liabilities": dict(tl),
        "total_equity": dict(te),
        "provisional_pl": ppl,
    }


# ---------------------------------------------------------------------------
# Columns (for UI / metadata calls)
# ---------------------------------------------------------------------------

def get_columns(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    filters = filters or {}
    to_d = parse_date_flex(filters.get("to_date")) or date.today()
    from_d = parse_date_flex(filters.get("from_date")) or date(to_d.year, 1, 1)
    periodicity = (filters.get("periodicity") or "Yearly").strip()
    periods = _build_periods_for_date_range(from_d, to_d, periodicity)

    cols: List[Dict[str, Any]] = [
        data_column("account", "Account", 260),
        int_column("indent", "Indent", 60),
        data_column("account_code", "Account Code", 110),
        data_column("root_type", "Root Type", 100),
    ]
    for p in periods:
        cols.append(currency_column(p.fieldname, p.label))
    return cols


# ---------------------------------------------------------------------------
# Main Report Class
# ---------------------------------------------------------------------------

class BalanceSheetReport:
    @classmethod
    def get_filters(cls):
        return get_filters()

    @classmethod
    def get_columns(cls, filters=None):
        return get_columns(filters)

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        start = time.time()

        # -----------------------------
        # 1) Normalize / validate
        # -----------------------------
        if not filters.get("company"):
            company_id_ctx = getattr(context, "company_id", None)
            if not company_id_ctx:
                raise ValueError("Company is required.")
            filters["company"] = int(company_id_ctx)

        company_id = int(filters["company"])

        branch_id = _parse_int(filters.get("branch_id"))
        include_closing = _coerce_bool(filters.get("include_closing_entries", True))
        show_zero_rows = _coerce_bool(filters.get("show_zero_rows", False))
        hide_group_amounts = _coerce_bool(filters.get("hide_group_amounts", False))
        show_only_last = _coerce_bool(filters.get("consolidate_columns", False))

        currency_precision = int(get_currency_precision() or 2)
        tol = 10 ** (-(currency_precision + 1))  # tiny tolerance to decide "zero"

        cost_center_id = _resolve_cost_center_id(
            session=session,
            company_id=company_id,
            branch_id=branch_id,
            cost_center_value=filters.get("cost_center"),
        )

        # -----------------------------
        # 2) Build periods
        # -----------------------------
        periods, overall_from, overall_to = _build_periods(filters, session, company_id)
        if not periods:
            return {
                "columns": get_columns(filters),
                "data": [],
                "filters": _format_filters_for_output(filters),
                "summary": {},
                "chart": None,
                "report_name": "Balance Sheet",
                "execution_time": round(time.time() - start, 4),
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            }

        if show_only_last:
            periods = [periods[-1]]

        # -----------------------------
        # 3) Load accounts + GL movements
        # -----------------------------
        accounts = _load_bs_accounts(session, company_id)
        if not accounts:
            return {
                "columns": self._build_columns(periods),
                "data": [],
                "filters": _format_filters_for_output(filters),
                "summary": {"periods": [], "totals": {}, "header": {}},
                "chart": None,
                "report_name": "Balance Sheet",
                "execution_time": round(time.time() - start, 4),
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            }

        account_ids = [a.id for a in accounts]

        gl_rows = _load_gl_daily_net(
            session=session,
            company_id=company_id,
            max_to_date=periods[-1].to_date,
            include_closing=include_closing,
            account_ids=account_ids,
            branch_id=branch_id,
            cost_center_id=cost_center_id,
        )

        # -----------------------------
        # 4) Compute balances
        # -----------------------------
        base_balances = _compute_closing_balances_fast(gl_rows, periods)
        account_map, children, depth, roots = _build_account_tree(accounts)
        balances = _rollup_groups(accounts, children, depth, periods, base_balances)
        totals = _compute_section_totals(accounts, balances, periods)

        # -----------------------------
        # 5) Build rows (tree)
        # -----------------------------
        rows: List[Dict[str, Any]] = []

        def walk(acc_id: int):
            acc = account_map[acc_id]
            indent = depth.get(acc_id, 0)

            row: Dict[str, Any] = {
                "account": acc.name,
                "account_code": acc.code,
                "indent": indent,
                "root_type": acc.account_type.value,
                "is_group": acc.is_group,
                "account_id": acc.id,
            }

            acc_bal = balances.get(acc_id, {})
            for p in periods:
                v = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
                if acc.is_group and hide_group_amounts:
                    row[p.fieldname] = None
                else:
                    row[p.fieldname] = round(v, currency_precision)

            # filter leaf zeros
            if not show_zero_rows and not acc.is_group:
                all_zero = True
                for p in periods:
                    v = row.get(p.fieldname)
                    if isinstance(v, (int, float)) and abs(float(v)) > tol:
                        all_zero = False
                        break
                if all_zero:
                    return

            rows.append(row)

            for cid in sorted(children.get(acc_id, []), key=lambda x: (account_map[x].code or "")):
                walk(cid)

        for rid in roots:
            walk(rid)

        # -----------------------------
        # 6) Inject Provisional Profit/Loss row (ERPNext-style)
        # -----------------------------
        pl_should_show = show_zero_rows
        for p in periods:
            if abs(float(totals["provisional_pl"].get(p.fieldname, 0.0) or 0.0)) > tol:
                pl_should_show = True
                break

        if pl_should_show:
            pl_row: Dict[str, Any] = {
                "account": "Provisional Profit/Loss (Current Period)",
                "account_code": "",
                "indent": 1,
                "root_type": "Equity",
                "is_group": False,
                "account_id": None,
            }
            for p in periods:
                pl_row[p.fieldname] = round(float(totals["provisional_pl"].get(p.fieldname, 0.0) or 0.0), currency_precision)
            rows.append(pl_row)

        # -----------------------------
        # 7) Summary + integrity check
        # -----------------------------
        last = periods[-1]
        k = last.fieldname
        last_assets = float(totals["total_assets"].get(k, 0.0) or 0.0)
        last_liab = float(totals["total_liabilities"].get(k, 0.0) or 0.0)
        last_equity = float(totals["total_equity"].get(k, 0.0) or 0.0)
        last_pl = float(totals["provisional_pl"].get(k, 0.0) or 0.0)

        liab_plus_equity_plus_pl = last_liab + last_equity + last_pl
        diff = round(last_assets - liab_plus_equity_plus_pl, currency_precision)

        summary = {
            "periods": [
                {
                    "fieldname": p.fieldname,
                    "label": p.label,
                    "from_date": p.from_date.isoformat(),
                    "to_date": p.to_date.isoformat(),
                }
                for p in periods
            ],
            "totals": totals,
            "header": {
                "total_assets": round(last_assets, currency_precision),
                "total_liabilities": round(last_liab, currency_precision),
                "total_equity": round(last_equity, currency_precision),
                "provisional_pl": round(last_pl, currency_precision),
                "total_liab_equity_pl": round(liab_plus_equity_plus_pl, currency_precision),
                "as_on_label": last.label,
                "integrity_diff": diff,  # should be ~0 when balanced (with P/L line)
            },
        }

        chart = self._build_chart(periods, totals, currency_precision)

        exec_time = round(time.time() - start, 4)

        return {
            "columns": self._build_columns(periods),
            "data": rows,
            "filters": _format_filters_for_output(filters),
            "summary": summary,
            "chart": chart,
            "report_name": "Balance Sheet",
            "execution_time": exec_time,
            "total_count": len(rows),
            "has_more": False,
            "next_cursor": None,
        }

    # -----------------------------
    # Column builder (uses exact periods)
    # -----------------------------
    def _build_columns(self, periods: List[PeriodDef]) -> List[Dict[str, Any]]:
        cols: List[Dict[str, Any]] = [
            data_column("account", "Account", 260),
            int_column("indent", "Indent", 60),
            data_column("account_code", "Account Code", 110),
            data_column("root_type", "Root Type", 100),
        ]
        for p in periods:
            cols.append(currency_column(p.fieldname, p.label))
        return cols

    # -----------------------------
    # Chart builder (simple overview)
    # -----------------------------
    def _build_chart(
        self,
        periods: List[PeriodDef],
        totals: Dict[str, Dict[str, float]],
        precision: int,
    ) -> Optional[Dict[str, Any]]:
        if not periods:
            return None

        labels = [p.label for p in periods]

        def series(key: str) -> List[float]:
            return [
                round(float(totals.get(key, {}).get(p.fieldname, 0.0) or 0.0), precision)
                for p in periods
            ]

        assets = series("total_assets")
        liab = series("total_liabilities")
        equity = series("total_equity")

        if all(v == 0 for v in assets + liab + equity):
            return None

        return {
            "type": "bar" if len(periods) > 1 else "line",
            "title": "Balance Sheet Overview",
            "data": {
                "labels": labels,
                "datasets": [
                    {"name": "Assets", "values": assets},
                    {"name": "Liabilities", "values": liab},
                    {"name": "Equity", "values": equity},
                ],
            },
            "height": 300,
        }
