# app/application_reports/scripts/balance_sheet.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext

from app.application_accounting.chart_of_accounts.models import (
    Account,
    AccountTypeEnum,
    ReportTypeEnum,
    GeneralLedgerEntry,
    FiscalYear,
)
from app.application_reports.core.columns import (
    currency_column,
    data_column,
    int_column,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class PeriodDef:
    fieldname: str  # safe key for data row, e.g. "p_2024", "p_2024_q1"
    label: str      # header label, e.g. "2024", "2024-Q1", "Jan-2024"
    from_date: date
    to_date: date


def _parse_date_flex(v: Any) -> Optional[date]:
    """Same idea as in Accounts Payable report."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        s = v.strip()
        for fmt in (
            "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d",
            "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y",
        ):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                continue
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None
    return None


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "y", "on")
    return False


def _add_months(d: date, months: int) -> date:
    """Simple add months without external libs."""
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
    """
    Turn labels like '2024', '2024-Q1', 'Jan-2024' into safe fieldname keys.
    """
    import re
    base = label.strip().lower()
    base = re.sub(r"[^0-9a-z]+", "_", base)
    base = base.strip("_")
    if not base:
        base = "period"
    return f"p_{base}"


# ---------------------------------------------------------------------------
# Filter + Column definitions (ERP-style)
# ---------------------------------------------------------------------------

def get_filters() -> List[Dict[str, Any]]:
    """
    Frontend filters for Balance Sheet.
    Mirrors ERPNext: Company, Branch, Cost Center, Based On, Date Range / Fiscal Year, Periodicity.
    """
    return [
        # Core
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
        {"fieldname": "branch_id", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "cost_center", "label": "Cost Center", "fieldtype": "Link", "options": "Cost Center"},

        # Basis
        {
            "fieldname": "basis",
            "label": "Based On",
            "fieldtype": "Select",
            "options": "Date Range\nFiscal Year",
            "default": "Date Range",
            "required": True,
        },

        # Date Range
        {"fieldname": "from_date", "label": "From Date", "fieldtype": "Date"},
        {"fieldname": "to_date", "label": "To Date", "fieldtype": "Date"},

        # Fiscal Year range
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

        # Behaviour flags
        {
            "fieldname": "include_closing_entries",
            "label": "Include Period Closing Entries",
            "fieldtype": "Check",
            "default": 1,
        },
        {
            "fieldname": "show_zero_rows",
            "label": "Show Zero Balance Accounts",
            "fieldtype": "Check",
            "default": 0,
        },
        {
            "fieldname": "hide_group_amounts",
            "label": "Hide Group Amounts",
            "fieldtype": "Check",
            "default": 0,
        },
        {
            "fieldname": "consolidate_columns",
            "label": "Consolidate Columns",
            "fieldtype": "Check",
            "default": 0,
        },
    ]


def _build_periods_for_date_range(
    from_date: date,
    to_date: date,
    periodicity: str,
) -> List[PeriodDef]:
    """
    Build periods for BASIS = Date Range.
    periodicity: 'yearly' | 'quarterly' | 'monthly'
    """
    periods: List[PeriodDef] = []
    periodicity = periodicity.lower()

    if periodicity == "yearly":
        start_year = from_date.year
        end_year = to_date.year
        for year in range(start_year, end_year + 1):
            p_from = from_date if year == start_year else date(year, 1, 1)
            p_to = to_date if year == end_year else date(year, 12, 31)
            label = str(year)
            fieldname = _sanitize_fieldname(label)
            periods.append(PeriodDef(fieldname, label, p_from, p_to))
        return periods

    # Quarterly / Monthly → rolling window using add_months
    cur_start = from_date
    while cur_start <= to_date:
        if periodicity == "quarterly":
            span_months = 3
            # Label "YYYY-Qx" based on month
            quarter = ((cur_start.month - 1) // 3) + 1
            label = f"{cur_start.year}-Q{quarter}"
        else:  # monthly
            span_months = 1
            label = cur_start.strftime("%b-%Y")  # "Jan-2024"

        next_start = _add_months(cur_start, span_months)
        p_to = min(next_start - timedelta(days=1), to_date)
        p_from = cur_start

        fieldname = _sanitize_fieldname(label)
        periods.append(PeriodDef(fieldname, label, p_from, p_to))

        cur_start = p_to + timedelta(days=1)

    return periods


def _build_periods_for_fiscal_year(
    session: Session,
    company_id: int,
    from_fy_name: str,
    to_fy_name: str,
    periodicity: str,
) -> Tuple[List[PeriodDef], date, date]:
    """
    Build periods for BASIS = Fiscal Year.
    Returns (periods, min_date, max_date)
    """
    periodicity = periodicity.lower()

    # Load fiscal years by name
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

    # Ensure correct order by date
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

    periods: List[PeriodDef] = []
    overall_min = fy_list[0].start_date.date()
    overall_max = fy_list[-1].end_date.date()

    for fy in fy_list:
        fy_start = fy.start_date.date()
        fy_end = fy.end_date.date()

        if periodicity == "yearly":
            label = fy.name
            fieldname = _sanitize_fieldname(label)
            periods.append(PeriodDef(fieldname, label, fy_start, fy_end))
            continue

        # quarterly / monthly inside each FY
        cur_start = fy_start
        while cur_start <= fy_end:
            if periodicity == "quarterly":
                span_months = 3
                quarter = ((cur_start.month - 1) // 3) + 1
                label = f"{fy.name} Q{quarter}"
            else:  # monthly
                span_months = 1
                label = f"{cur_start.strftime('%b-%Y')} ({fy.name})"

            next_start = _add_months(cur_start, span_months)
            p_to = min(next_start - timedelta(days=1), fy_end)
            p_from = cur_start

            fieldname = _sanitize_fieldname(label)
            periods.append(PeriodDef(fieldname, label, p_from, p_to))

            cur_start = p_to + timedelta(days=1)

    return periods, overall_min, overall_max


def _build_periods(
    filters: Dict[str, Any],
    session: Session,
    company_id: int,
) -> Tuple[List[PeriodDef], date, date]:
    """
    Core period builder. Decides between Date Range / Fiscal Year.
    Returns (periods, overall_from_date, overall_to_date).
    """
    basis_raw = (filters.get("basis") or "Date Range").strip().lower()
    periodicity = (filters.get("periodicity") or "Yearly").strip().lower()

    if basis_raw.startswith("fiscal"):
        from_fy_name = (filters.get("from_fiscal_year") or "").strip()
        to_fy_name = (filters.get("to_fiscal_year") or "").strip()
        if not from_fy_name or not to_fy_name:
            raise ValueError("From Fiscal Year and To Fiscal Year are required when Based On = Fiscal Year.")
        periods, overall_min, overall_max = _build_periods_for_fiscal_year(
            session=session,
            company_id=company_id,
            from_fy_name=from_fy_name,
            to_fy_name=to_fy_name,
            periodicity=periodicity,
        )
        return periods, overall_min, overall_max

    # Date Range path
    to_date = _parse_date_flex(filters.get("to_date")) or date.today()
    from_date = _parse_date_flex(filters.get("from_date"))
    if not from_date:
        # default to start of the year of to_date
        from_date = date(to_date.year, 1, 1)

    periods = _build_periods_for_date_range(from_date, to_date, periodicity)
    if not periods:
        raise ValueError("No periods could be derived from the selected date range.")

    overall_min = periods[0].from_date
    overall_max = periods[-1].to_date
    return periods, overall_min, overall_max


def _load_bs_accounts(session: Session, company_id: int) -> List[Account]:
    """
    Load all Balance Sheet accounts (Assets, Liabilities, Equity) for a company.
    """
    return (
        session.query(Account)
        .filter(
            Account.company_id == company_id,
            Account.enabled.is_(True),
            Account.report_type == ReportTypeEnum.BALANCE_SHEET,
            Account.account_type.in_(
                [AccountTypeEnum.ASSET, AccountTypeEnum.LIABILITY, AccountTypeEnum.EQUITY]
            ),
        )
        .all()
    )


def _load_gl_aggregated(
    session: Session,
    company_id: int,
    max_to_date: date,
    branch_id: Optional[int] = None,
    cost_center_name: Optional[str] = None,
    include_closing: bool = True,
) -> List[Dict[str, Any]]:
    """
    Load aggregated GL by account + posting_date for Balance Sheet accounts.

    - Only SUBMITTED journal entries
    - Only Asset / Liability / Equity accounts
    - Only enabled accounts
    - Up to max_to_date (inclusive)

    NOTE:
    - branch_id, cost_center_name, include_closing are accepted to match the
      execute() call signature; you can wire them into the SQL WHEN your GL
      schema fields are confirmed.
    """
    sql = """
        SELECT
            gle.account_id,
            gle.posting_date::date         AS posting_date,
            SUM(gle.debit - gle.credit)    AS amount
        FROM general_ledger_entries gle
        JOIN journal_entries je ON je.id = gle.journal_entry_id
        JOIN accounts acc ON acc.id = gle.account_id
        WHERE gle.company_id = :company
          AND gle.posting_date::date <= :max_to_date
          -- report_type is a PostgreSQL ENUM; cast to text so both
          -- 'Balance Sheet' and 'BALANCE_SHEET' enum labels are accepted.
          AND acc.report_type::text IN ('Balance Sheet', 'BALANCE_SHEET')
          AND acc.enabled = TRUE
          AND je.doc_status = 'SUBMITTED'
       AND acc.account_type::text IN ('Asset','Liability','Equity','ASSET','LIABILITY','EQUITY')

        GROUP BY gle.account_id, gle.posting_date::date
        ORDER BY gle.account_id, posting_date
    """

    params = {
        "company": company_id,
        "max_to_date": max_to_date,
    }

    rows = session.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _build_account_tree(accounts: List[Account]) -> Tuple[
    Dict[int, Account],
    Dict[Optional[int], List[int]],
    Dict[int, int],
]:
    """
    Build:
    - account_map: id -> Account
    - children: parent_id -> [child_id...]
    - depth: account_id -> level (0 = root)
    """
    account_map: Dict[int, Account] = {a.id: a for a in accounts}
    children: Dict[Optional[int], List[int]] = defaultdict(list)

    for a in accounts:
        children[a.parent_account_id].append(a.id)

    # simple DFS to compute depth
    depth: Dict[int, int] = {}

    def dfs(acc_id: int, lvl: int) -> None:
        depth[acc_id] = lvl
        for cid in children.get(acc_id, []):
            dfs(cid, lvl + 1)

    # roots = accounts whose parent is None or not in map
    roots = [a for a in accounts if a.parent_account_id not in account_map]

    # sort roots by account_type then code
    def _root_sort_key(a: Account):
        at = a.account_type
        order = {
            AccountTypeEnum.ASSET: 0,
            AccountTypeEnum.LIABILITY: 1,
            AccountTypeEnum.EQUITY: 2,
        }.get(at, 9)
        return (order, a.code or "")

    roots.sort(key=_root_sort_key)

    for r in roots:
        dfs(r.id, 0)

    return account_map, children, depth


def _compute_account_balances_per_period(
    gl_rows: List[Dict[str, Any]],
    periods: List[PeriodDef],
) -> Dict[int, Dict[str, float]]:
    """
    For each account, and each period.fieldname, compute closing balance as of period.to_date.
    gl_rows: (account_id, posting_date, amount)
    Returns: balances[account_id][period.fieldname] = float
    """
    by_acc: Dict[int, List[Tuple[date, float]]] = defaultdict(list)
    for r in gl_rows:
        acc_id = int(r["account_id"])
        posting = r["posting_date"]
        if isinstance(posting, datetime):
            posting = posting.date()
        amt = float(r["amount"] or 0.0)
        by_acc[acc_id].append((posting, amt))

    # ensure sorted
    for acc_id in by_acc:
        by_acc[acc_id].sort(key=lambda x: x[0])

    balances: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for acc_id, entries in by_acc.items():
        # Precompute prefix sums (posting_date -> cumulative)
        dates: List[date] = []
        prefix: List[float] = []
        running = 0.0
        for d, amt in entries:
            running += amt
            dates.append(d)
            prefix.append(running)

        # For each period, closing = last prefix where date <= to_date
        for p in periods:
            closing = 0.0
            # linear scan is fine (accounts not huge in practice); can optimize if needed
            for idx, d in enumerate(dates):
                if d <= p.to_date:
                    closing = prefix[idx]
                else:
                    break
            balances[acc_id][p.fieldname] = closing

    return balances


def _rollup_group_balances(
    accounts: List[Account],
    children: Dict[Optional[int], List[int]],
    periods: List[PeriodDef],
    leaf_balances: Dict[int, Dict[str, float]],
) -> Dict[int, Dict[str, float]]:
    """
    Roll-up balances to group accounts bottom-up.
    leaf_balances may already contain some group balances (if GL hits group accounts directly),
    but we recompute groups as sum(children).
    """
    balances: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # start with whatever we have for detail accounts
    for acc_id, per in leaf_balances.items():
        for fld, val in per.items():
            balances[acc_id][fld] = val

    # compute depth map to process bottom-up
    _, _, depth = _build_account_tree(accounts)
    # sort accounts by depth descending
    sorted_accounts = sorted(accounts, key=lambda a: depth.get(a.id, 0), reverse=True)

    for acc in sorted_accounts:
        if not acc.is_group:
            continue
        # sum children balances
        for p in periods:
            total = 0.0
            for child_id in children.get(acc.id, []):
                total += balances[child_id].get(p.fieldname, 0.0)
            balances[acc.id][p.fieldname] = total

    return balances


def _compute_totals(
    accounts: List[Account],
    balances: Dict[int, Dict[str, float]],
    periods: List[PeriodDef],
) -> Dict[str, Dict[str, float]]:
    """
    Compute Total Assets / Liabilities / Equity / Provisional P&L per period.
    Only leaf accounts are used to avoid double-counting.
    """
    totals_assets: Dict[str, float] = defaultdict(float)
    totals_liab: Dict[str, float] = defaultdict(float)
    totals_equity: Dict[str, float] = defaultdict(float)

    # leaf = not group
    for acc in accounts:
        if acc.is_group:
            continue
        acc_bal = balances.get(acc.id, {})
        for p in periods:
            val = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
            if acc.account_type == AccountTypeEnum.ASSET:
                totals_assets[p.fieldname] += val
            elif acc.account_type == AccountTypeEnum.LIABILITY:
                totals_liab[p.fieldname] += val
            elif acc.account_type == AccountTypeEnum.EQUITY:
                totals_equity[p.fieldname] += val

    provisional_pl: Dict[str, float] = {}
    for p in periods:
        a = totals_assets.get(p.fieldname, 0.0)
        l = totals_liab.get(p.fieldname, 0.0)
        e = totals_equity.get(p.fieldname, 0.0)
        provisional_pl[p.fieldname] = a - (l + e)

    return {
        "total_assets": dict(totals_assets),
        "total_liabilities": dict(totals_liab),
        "total_equity": dict(totals_equity),
        "provisional_pl": provisional_pl,
    }


def get_columns(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Dynamic column model for Balance Sheet.
    - Account, Indent, Account Code, Root Type
    - + one currency column per period.
    """
    filters = filters or {}
    # we don't have session here; so just derive periods roughly from filters
    # using only date range. For fiscal-year-based calls to /columns, the
    # frontend usually calls /execute shortly after, so this is "best effort".
    to_date = _parse_date_flex(filters.get("to_date")) or date.today()
    from_date = _parse_date_flex(filters.get("from_date")) or date(to_date.year, 1, 1)
    periodicity = (filters.get("periodicity") or "Yearly").strip().lower()

    periods = _build_periods_for_date_range(from_date, to_date, periodicity)

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

    def execute(
        self,
        filters: Dict[str, Any],
        session: Session,
        context: AffiliationContext,
    ) -> Dict[str, Any]:
        # -------------------------------------------------------------------
        # 1) Normalize / validate filters
        # -------------------------------------------------------------------
        if not filters.get("company"):
            # fallback to context if available
            company_id = getattr(context, "company_id", None)
            if not company_id:
                raise ValueError("Company is required.")
            filters["company"] = int(company_id)
        company_id = int(filters["company"])

        branch_id = filters.get("branch_id")
        if isinstance(branch_id, str) and branch_id.strip() != "":
            try:
                branch_id = int(branch_id)
            except Exception:
                branch_id = None
        elif not branch_id:
            branch_id = None

        cost_center_name = (filters.get("cost_center") or "").strip() or None

        include_closing = _coerce_bool(filters.get("include_closing_entries"))
        show_zero_rows = _coerce_bool(filters.get("show_zero_rows"))
        hide_group_amounts = _coerce_bool(filters.get("hide_group_amounts"))
        consolidate_columns = _coerce_bool(filters.get("consolidate_columns"))

        # Build periods (using DB for fiscal-year mode)
        periods, overall_from, overall_to = _build_periods(filters, session, company_id)

        # -------------------------------------------------------------------
        # 2) Load accounts + GL movements
        # -------------------------------------------------------------------
        accounts = _load_bs_accounts(session, company_id)
        if not accounts:
            return {
                "columns": get_columns(filters),
                "data": [],
                "filters": filters,
                "summary": {
                    "periods": [],
                    "totals": {},
                },
                "chart": None,
                "has_more": False,  # to disable outer paging
            }

        gl_rows = _load_gl_aggregated(
            session=session,
            company_id=company_id,
            max_to_date=overall_to,
            branch_id=branch_id,
            cost_center_name=cost_center_name,
            include_closing=include_closing,
        )

        # -------------------------------------------------------------------
        # 3) Compute balances per account & period
        # -------------------------------------------------------------------
        leaf_balances = _compute_account_balances_per_period(gl_rows, periods)
        account_map, children, depth = _build_account_tree(accounts)
        balances = _rollup_group_balances(accounts, children, periods, leaf_balances)
        totals = _compute_totals(accounts, balances, periods)

        # -------------------------------------------------------------------
        # 4) Build rows in tree order
        # -------------------------------------------------------------------
        rows: List[Dict[str, Any]] = []

        # roots (same as in _build_account_tree)
        roots = [a for a in accounts if a.parent_account_id not in account_map]

        def _root_sort_key(a: Account):
            at = a.account_type
            order = {
                AccountTypeEnum.ASSET: 0,
                AccountTypeEnum.LIABILITY: 1,
                AccountTypeEnum.EQUITY: 2,
            }.get(at, 9)
            return (order, a.code or "")

        roots.sort(key=_root_sort_key)

        def walk(acc_id: int):
            acc = account_map[acc_id]
            indent = depth.get(acc_id, 0)

            row: Dict[str, Any] = {
                "account": acc.name,
                "account_code": acc.code,
                "indent": indent,
                "root_type": acc.account_type.value,
                "is_group": acc.is_group,
                "account_id": acc.id,  # helpful for frontend, even if no column
            }

            # attach balances for each period
            acc_bal = balances.get(acc_id, {})
            # If hide_group_amounts: zero / blank out group rows
            for p in periods:
                val = float(acc_bal.get(p.fieldname, 0.0) or 0.0)
                if acc.is_group and hide_group_amounts:
                    row[p.fieldname] = None
                else:
                    row[p.fieldname] = round(val, 2)

            # skip zero rows if requested (only non-group or optionally all)
            if not show_zero_rows and not acc.is_group:
                # check if all periods are zero/None
                all_zero = True
                for p in periods:
                    v = row.get(p.fieldname)
                    if v not in (0, 0.0, None):
                        all_zero = False
                        break
                if all_zero:
                    # do not append this leaf row
                    pass
                else:
                    rows.append(row)
            else:
                rows.append(row)

            # recurse children (sorted by code)
            for cid in sorted(children.get(acc_id, []), key=lambda cid: account_map[cid].code or ""):
                walk(cid)

        for r in roots:
            walk(r.id)

        # -------------------------------------------------------------------
        # 5) Consolidate columns (optional) – simple implementation:
        #    If consolidate_columns = True → add a "Total" column as sum of all periods.
        #    (We still keep individual period columns; frontend can choose what to show.)
        # -------------------------------------------------------------------
        if consolidate_columns:
            total_field = "p_total"
            for row in rows:
                total_val = 0.0
                for p in periods:
                    v = row.get(p.fieldname)
                    if isinstance(v, (int, float)):
                        total_val += float(v)
                row[total_field] = round(total_val, 2)

            # Add Total column meta at the end via summary
            totals["total_column"] = {"fieldname": total_field, "label": "Total"}

        # Header cards use latest period (right-most)
        last_period = periods[-1]
        last_key = last_period.fieldname
        last_assets = totals["total_assets"].get(last_key, 0.0)
        last_liab = totals["total_liabilities"].get(last_key, 0.0)
        last_equity = totals["total_equity"].get(last_key, 0.0)
        last_pl = totals["provisional_pl"].get(last_key, 0.0)

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
                "total_assets": round(last_assets, 2),
                "total_liabilities": round(last_liab, 2),
                "total_equity": round(last_equity, 2),
                "provisional_pl": round(last_pl, 2),
                "as_on_label": last_period.label,
            },
        }

        # Use dynamic columns based on actual periods
        cols: List[Dict[str, Any]] = [
            data_column("account", "Account", 260),
            int_column("indent", "Indent", 60),
            data_column("account_code", "Account Code", 110),
            data_column("root_type", "Root Type", 100),
        ]
        for p in periods:
            cols.append(currency_column(p.fieldname, p.label))
        if consolidate_columns:
            cols.append(currency_column("p_total", "Total"))

        return {
            "columns": cols,
            "data": rows,
            "filters": filters,
            "summary": summary,
            "chart": None,
            "has_more": False,   # IMPORTANT: disable generic paging truncation
            "next_cursor": None,
        }
