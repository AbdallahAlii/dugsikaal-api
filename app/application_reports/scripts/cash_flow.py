# app/application_reports/scripts/cash_flow.py
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
from app.application_reports.core.columns import currency_column, data_column, int_column

from app.application_accounting.chart_of_accounts.models import Account, FiscalYear  # same as Balance Sheet

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Period model
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class PeriodDef:
    fieldname: str
    label: str
    from_date: date
    to_date: date


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
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
    out = dict(filters or {})
    for k in ("from_date", "to_date"):
        if out.get(k) and isinstance(out[k], (date, datetime)):
            out[k] = format_date_for_display(out[k])
    return out


# -----------------------------------------------------------------------------
# Filters (ERP-style)
# -----------------------------------------------------------------------------
def get_filters() -> List[Dict[str, Any]]:
    return [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
        {"fieldname": "branch_id", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "cost_center_id", "label": "Cost Center", "fieldtype": "Link", "options": "Cost Center"},

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
            "default": "Monthly",
            "required": True,
        },

        {"fieldname": "include_closing_entries", "label": "Include Period Closing Entries", "fieldtype": "Check", "default": 1},
        {"fieldname": "show_opening_and_closing_balance", "label": "Show Opening & Closing Cash Balance", "fieldtype": "Check", "default": 1},

        # optional overrides (when your COA naming is not standard)
        {"fieldname": "cash_account_ids", "label": "Cash/Bank Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "receivable_account_ids", "label": "Receivable Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "payable_account_ids", "label": "Payable Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "stock_account_ids", "label": "Inventory/Stock Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "fixed_asset_account_ids", "label": "Fixed Asset Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "equity_loan_account_ids", "label": "Equity/Loan Account IDs (comma)", "fieldtype": "Data"},
        {"fieldname": "depreciation_account_ids", "label": "Depreciation Account IDs (comma)", "fieldtype": "Data"},
    ]


def _parse_csv_ids(v: Any) -> List[int]:
    if not v:
        return []
    s = str(v).strip()
    if not s:
        return []
    out: List[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


# -----------------------------------------------------------------------------
# Period building (same style as your Balance Sheet)
# -----------------------------------------------------------------------------
def _build_periods_for_date_range(from_date: date, to_date: date, periodicity: str) -> List[PeriodDef]:
    periodicity = (periodicity or "Monthly").strip().lower()
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
    periodicity = (periodicity or "Monthly").strip().lower()

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
    periodicity = (filters.get("periodicity") or "Monthly").strip()

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


# -----------------------------------------------------------------------------
# Account grouping (safe heuristic + overrides)
# -----------------------------------------------------------------------------
def _load_accounts_for_company(session: Session, company_id: int) -> List[Account]:
    return (
        session.query(Account)
        .filter(Account.company_id == company_id, Account.enabled.is_(True))
        .all()
    )


def _pick_ids_by_heuristic(accounts: List[Account]) -> Dict[str, List[int]]:
    """
    Heuristic grouping based on common COA naming patterns.
    You can override all of these via filters CSV IDs.
    """
    def norm(s: Any) -> str:
        return str(s or "").strip().upper()

    groups = {
        "cash": [],
        "receivable": [],
        "payable": [],
        "stock": [],
        "fixed_asset": [],
        "equity_loan": [],
        "depreciation": [],
        "income_expense": [],
    }

    for a in accounts:
        if getattr(a, "is_group", False):
            continue

        name = norm(getattr(a, "name", ""))
        code = norm(getattr(a, "code", ""))
        atype = norm(getattr(a, "account_type", ""))   # could be enum or string; string compare is safe
        rtype = norm(getattr(a, "report_type", ""))

        # Profit/Loss accounts
        if atype in ("INCOME", "EXPENSE") or rtype in ("PROFIT_LOSS", "PROFIT AND LOSS", "PROFIT_AND_LOSS"):
            groups["income_expense"].append(a.id)

        # Depreciation
        if "DEPRECIATION" in name or "DEPR" in code:
            groups["depreciation"].append(a.id)

        # Receivable / Payable control accounts
        if "RECEIVABLE" in name or "ACCOUNTS RECEIVABLE" in name or code.startswith("AR"):
            groups["receivable"].append(a.id)
        if "PAYABLE" in name or "ACCOUNTS PAYABLE" in name or code.startswith("AP"):
            groups["payable"].append(a.id)

        # Inventory
        if "INVENTORY" in name or "STOCK" in name:
            groups["stock"].append(a.id)

        # Fixed assets
        if "FIXED ASSET" in name or "EQUIPMENT" in name or "VEHICLE" in name or "FURNITURE" in name:
            groups["fixed_asset"].append(a.id)

        # Equity + loans (financing)
        if atype in ("EQUITY", "LIABILITY") and ("CAPITAL" in name or "EQUITY" in name or "LOAN" in name or "BORROW" in name):
            groups["equity_loan"].append(a.id)

        # Cash/Bank
        if ("CASH" in name or "BANK" in name or "WALLET" in name) and atype in ("ASSET", ""):
            groups["cash"].append(a.id)

    return groups


# -----------------------------------------------------------------------------
# GL loaders (safe + fast)
# -----------------------------------------------------------------------------
def _load_gl_sum_by_account_between(
    session: Session,
    company_id: int,
    from_date: date,
    to_date: date,
    account_ids: List[int],
    include_closing: bool,
    branch_id: Optional[int],
    cost_center_id: Optional[int],
) -> Dict[int, float]:
    """
    Returns period net amount for each account_id as:
      (credit - debit)  -> works for net profit when accounts are Income/Expense.
    """
    if not account_ids:
        return {}

    sql = """
        SELECT
            gle.account_id,
            SUM(gle.credit - gle.debit) AS amt
        FROM general_ledger_entries gle
        JOIN journal_entries je ON je.id = gle.journal_entry_id
        WHERE gle.company_id = :company_id
          AND je.doc_status = 'SUBMITTED'
          AND gle.posting_date::date BETWEEN :from_date AND :to_date
          AND gle.account_id IN :account_ids
    """
    params: Dict[str, Any] = {
        "company_id": company_id,
        "from_date": from_date,
        "to_date": to_date,
        "account_ids": account_ids,
    }

    if branch_id:
        sql += " AND gle.branch_id = :branch_id"
        params["branch_id"] = branch_id
    if cost_center_id:
        sql += " AND gle.cost_center_id = :cost_center_id"
        params["cost_center_id"] = cost_center_id

    if not include_closing:
        sql += " AND COALESCE(je.entry_type::text,'') <> 'Closing'"

    sql += " GROUP BY gle.account_id"

    stmt = text(sql).bindparams(bindparam("account_ids", expanding=True))
    rows = session.execute(stmt, params).mappings().all()
    return {int(r["account_id"]): float(r["amt"] or 0.0) for r in rows}


def _load_balance_as_of(
    session: Session,
    company_id: int,
    as_of_date: date,
    account_ids: List[int],
    include_closing: bool,
    branch_id: Optional[int],
    cost_center_id: Optional[int],
) -> float:
    """
    Returns SUM(balance) for a group of accounts as of a date (<= as_of_date),
    where balance is normalized to be positive on its normal side:
      Asset/Expense: debit - credit
      Liability/Equity/Income: credit - debit
    """
    if not account_ids:
        return 0.0

    sql = """
        SELECT
            SUM(
                CASE
                    WHEN UPPER(COALESCE(acc.account_type::text,'')) IN ('ASSET','EXPENSE')
                        THEN (gle.debit - gle.credit)
                    ELSE (gle.credit - gle.debit)
                END
            ) AS bal
        FROM general_ledger_entries gle
        JOIN journal_entries je ON je.id = gle.journal_entry_id
        JOIN accounts acc ON acc.id = gle.account_id
        WHERE gle.company_id = :company_id
          AND je.doc_status = 'SUBMITTED'
          AND gle.posting_date::date <= :as_of_date
          AND gle.account_id IN :account_ids
          AND acc.enabled = TRUE
    """
    params: Dict[str, Any] = {
        "company_id": company_id,
        "as_of_date": as_of_date,
        "account_ids": account_ids,
    }

    if branch_id:
        sql += " AND gle.branch_id = :branch_id"
        params["branch_id"] = branch_id
    if cost_center_id:
        sql += " AND gle.cost_center_id = :cost_center_id"
        params["cost_center_id"] = cost_center_id

    if not include_closing:
        sql += " AND COALESCE(je.entry_type::text,'') <> 'Closing'"

    stmt = text(sql).bindparams(bindparam("account_ids", expanding=True))
    row = session.execute(stmt, params).first()
    return float(row[0] or 0.0) if row else 0.0


# -----------------------------------------------------------------------------
# Columns
# -----------------------------------------------------------------------------
def get_columns(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    filters = filters or {}
    # build periods based on provided filters (best effort; fallback to monthly YTD)
    to_d = parse_date_flex(filters.get("to_date")) or date.today()
    from_d = parse_date_flex(filters.get("from_date")) or date(to_d.year, 1, 1)
    periodicity = (filters.get("periodicity") or "Monthly").strip()
    periods = _build_periods_for_date_range(from_d, to_d, periodicity)

    cols: List[Dict[str, Any]] = [
        data_column("section", "Section", 320),
        int_column("indent", "Indent", 60),
    ]
    for p in periods:
        cols.append(currency_column(p.fieldname, p.label, width=140))
    cols.append(currency_column("total", "Total", width=140))
    return cols


# -----------------------------------------------------------------------------
# Main report
# -----------------------------------------------------------------------------
class CashFlowReport:
    @classmethod
    def get_filters(cls):
        return get_filters()

    @classmethod
    def get_columns(cls, filters=None):
        return get_columns(filters)

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        start = time.time()

        # ---- normalize ----
        if not filters.get("company"):
            ctx_company = getattr(context, "company_id", None)
            if not ctx_company:
                raise ValueError("Company is required.")
            filters["company"] = int(ctx_company)

        company_id = int(filters["company"])
        branch_id = _parse_int(filters.get("branch_id"))
        cost_center_id = _parse_int(filters.get("cost_center_id"))

        include_closing = _coerce_bool(filters.get("include_closing_entries", True))
        show_open_close = _coerce_bool(filters.get("show_opening_and_closing_balance", True))

        precision = int(get_currency_precision() or 2)

        # ---- periods ----
        periods, overall_from, overall_to = _build_periods(filters, session, company_id)

        # ---- accounts + grouping ----
        accounts = _load_accounts_for_company(session, company_id)
        heur = _pick_ids_by_heuristic(accounts)

        # overrides from filters (comma list)
        cash_ids = _parse_csv_ids(filters.get("cash_account_ids")) or heur["cash"]
        ar_ids = _parse_csv_ids(filters.get("receivable_account_ids")) or heur["receivable"]
        ap_ids = _parse_csv_ids(filters.get("payable_account_ids")) or heur["payable"]
        stock_ids = _parse_csv_ids(filters.get("stock_account_ids")) or heur["stock"]
        fa_ids = _parse_csv_ids(filters.get("fixed_asset_account_ids")) or heur["fixed_asset"]
        fin_ids = _parse_csv_ids(filters.get("equity_loan_account_ids")) or heur["equity_loan"]
        dep_ids = _parse_csv_ids(filters.get("depreciation_account_ids")) or heur["depreciation"]
        ie_ids = heur["income_expense"]  # profit = sum(credit - debit) over Income+Expense

        # If no cash accounts found, we still produce report (but opening/closing cash may be 0)
        # Users can override with cash_account_ids.

        # ---- compute per period ----
        rows: List[Dict[str, Any]] = []

        def add_row(label: str, indent: int, values_by_period: Dict[str, float]) -> None:
            total = sum(values_by_period.get(p.fieldname, 0.0) for p in periods)
            row = {"section": label, "indent": indent}
            for p in periods:
                row[p.fieldname] = round(float(values_by_period.get(p.fieldname, 0.0) or 0.0), precision)
            row["total"] = round(float(total), precision)
            rows.append(row)

        def add_header(label: str) -> None:
            rows.append({"section": label, "indent": 0})

        def add_blank() -> None:
            rows.append({})

        ops_total: Dict[str, float] = {}
        inv_total: Dict[str, float] = {}
        fin_total: Dict[str, float] = {}

        # Helper: compute change in balance group within a period:
        # closing(as_of to_date) - opening(as_of day_before_from_date)
        def period_change(group_ids: List[int], p: PeriodDef) -> float:
            opening_asof = p.from_date - timedelta(days=1)
            opening = _load_balance_as_of(
                session, company_id, opening_asof, group_ids, include_closing, branch_id, cost_center_id
            )
            closing = _load_balance_as_of(
                session, company_id, p.to_date, group_ids, include_closing, branch_id, cost_center_id
            )
            return float(closing - opening)

        # Helper: compute net profit for period (income-expense):
        def period_net_profit(p: PeriodDef) -> float:
            sums = _load_gl_sum_by_account_between(
                session, company_id, p.from_date, p.to_date, ie_ids, include_closing, branch_id, cost_center_id
            )
            return float(sum(sums.values()) if sums else 0.0)

        # Helper: depreciation expense for period (add-back)
        def period_depreciation(p: PeriodDef) -> float:
            if not dep_ids:
                return 0.0
            sums = _load_gl_sum_by_account_between(
                session, company_id, p.from_date, p.to_date, dep_ids, include_closing, branch_id, cost_center_id
            )
            # dep expense accounts usually behave like Expense, so (credit - debit) is negative.
            # We want a positive add-back number: abs(total_negative) is safe.
            val = float(sum(sums.values()) if sums else 0.0)
            return abs(val)

        # ----- Operations -----
        add_header("Cash Flow from Operations")

        net_profit_vals: Dict[str, float] = {}
        dep_vals: Dict[str, float] = {}
        ar_change_vals: Dict[str, float] = {}
        ap_change_vals: Dict[str, float] = {}
        stock_change_vals: Dict[str, float] = {}
        ops_vals: Dict[str, float] = {}

        for p in periods:
            npv = period_net_profit(p)
            dep = period_depreciation(p)

            # Working capital changes (cash impact)
            d_ar = period_change(ar_ids, p)     # + means AR increased => cash decreases
            d_ap = period_change(ap_ids, p)     # + means AP increased => cash increases
            d_stock = period_change(stock_ids, p)  # + means inventory increased => cash decreases

            cash_ar = -d_ar
            cash_ap = +d_ap
            cash_stock = -d_stock

            net_profit_vals[p.fieldname] = npv
            dep_vals[p.fieldname] = dep
            ar_change_vals[p.fieldname] = cash_ar
            ap_change_vals[p.fieldname] = cash_ap
            stock_change_vals[p.fieldname] = cash_stock

            ops = npv + dep + cash_ar + cash_ap + cash_stock
            ops_vals[p.fieldname] = ops
            ops_total[p.fieldname] = ops

        add_row("Net Profit / (Loss)", 1, net_profit_vals)
        add_row("Depreciation (Add Back)", 1, dep_vals)
        add_row("Net Change in Accounts Receivable", 1, ar_change_vals)
        add_row("Net Change in Accounts Payable", 1, ap_change_vals)
        add_row("Net Change in Inventory", 1, stock_change_vals)
        add_row("Net Cash from Operations", 0, ops_vals)
        add_blank()

        # ----- Investing -----
        add_header("Cash Flow from Investing")

        inv_vals: Dict[str, float] = {}
        fa_change_vals: Dict[str, float] = {}

        for p in periods:
            d_fa = period_change(fa_ids, p)      # + means FA increased => cash out
            cash_fa = -d_fa
            fa_change_vals[p.fieldname] = cash_fa
            inv_vals[p.fieldname] = cash_fa
            inv_total[p.fieldname] = cash_fa

        add_row("Net Change in Fixed Assets", 1, fa_change_vals)
        add_row("Net Cash from Investing", 0, inv_vals)
        add_blank()

        # ----- Financing -----
        add_header("Cash Flow from Financing")

        fin_vals: Dict[str, float] = {}
        fin_change_vals: Dict[str, float] = {}

        for p in periods:
            d_fin = period_change(fin_ids, p)    # + means equity/loan increased => cash in
            cash_fin = +d_fin
            fin_change_vals[p.fieldname] = cash_fin
            fin_vals[p.fieldname] = cash_fin
            fin_total[p.fieldname] = cash_fin

        add_row("Net Change in Equity / Loans", 1, fin_change_vals)
        add_row("Net Cash from Financing", 0, fin_vals)
        add_blank()

        # ----- Net Change in Cash -----
        net_change_vals: Dict[str, float] = {}
        for p in periods:
            net_change = float(ops_total.get(p.fieldname, 0.0) + inv_total.get(p.fieldname, 0.0) + fin_total.get(p.fieldname, 0.0))
            net_change_vals[p.fieldname] = net_change

        add_row("Net Change in Cash", 0, net_change_vals)

        # ----- Opening/Closing Cash -----
        if show_open_close:
            # Opening cash at start of first period (as of day before)
            first = periods[0]
            opening_cash = _load_balance_as_of(
                session,
                company_id,
                first.from_date - timedelta(days=1),
                cash_ids,
                include_closing,
                branch_id,
                cost_center_id,
            )
            running = float(opening_cash)

            opening_row: Dict[str, float] = {}
            closing_row: Dict[str, float] = {}

            for i, p in enumerate(periods):
                if i == 0:
                    opening_row[p.fieldname] = float(opening_cash)
                else:
                    opening_row[p.fieldname] = float(running)
                running += float(net_change_vals.get(p.fieldname, 0.0) or 0.0)
                closing_row[p.fieldname] = float(running)

            add_blank()
            add_row("Opening Cash / Bank", 0, opening_row)
            add_row("Closing Cash / Bank", 0, closing_row)

        # ---- columns ----
        cols = self._build_columns(periods)

        exec_time = round(time.time() - start, 4)
        return {
            "columns": cols,
            "data": rows,
            "filters": _format_filters_for_output(filters),
            "summary": None,
            "chart": None,
            "report_name": "Cash Flow Statement",
            "execution_time": exec_time,
            "total_count": len(rows),
            "has_more": False,
            "next_cursor": None,
        }

    def _build_columns(self, periods: List[PeriodDef]) -> List[Dict[str, Any]]:
        cols: List[Dict[str, Any]] = [
            data_column("section", "Section", 320),
            int_column("indent", "Indent", 60),
        ]
        for p in periods:
            cols.append(currency_column(p.fieldname, p.label, width=140))
        cols.append(currency_column("total", "Total", width=140))
        return cols
