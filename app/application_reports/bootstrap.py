
# app/application_reports/bootstrap.py
from __future__ import annotations
import logging
import os
from importlib import import_module

from app.application_reports.core.engine import ReportMeta, ReportType, ReportEngine, QueryReport, ScriptReport
from app.application_reports.core.columns import (
    company_filter, GL_COLUMNS,
    STOCK_LEDGER_COLUMNS, TRIAL_BALANCE_COLUMNS,
    ITEM_STOCK_LEDGER_COLUMNS_FULL, ITEM_STOCK_LEDGER_COLUMNS_COMPACT,
    STOCK_BALANCE_SINGLE_ITEM_COLUMNS_FULL, STOCK_BALANCE_SINGLE_ITEM_COLUMNS_COMPACT
)
from app.application_reports.core.safe_query_report import SafeQueryReport
from app.application_reports.scripts.balance_sheet import BalanceSheetReport
from app.application_reports.scripts.cash_flow import CashFlowReport

log = logging.getLogger(__name__)

def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "y", "on")
    return False

def bootstrap_reports(engine: ReportEngine) -> None:
    base_dir = os.path.dirname(__file__)
    sql_dir = os.path.join(base_dir, "sql")
    if not os.path.exists(sql_dir):
        os.makedirs(sql_dir)
        log.info(f"Created SQL directory: {sql_dir}")

    # General Ledger (query)
    gl_meta = ReportMeta(
        name="General Ledger",
        description="Complete record of all financial transactions",
        report_type=ReportType.QUERY,
        module="Accounts",
        category="Financial Statements"
    )
    gl_report = QueryReport(
        meta=gl_meta,
        sql_file=os.path.join(sql_dir, "general_ledger_query.sql"),
        columns=GL_COLUMNS
    )
    engine.register_report(gl_report)

    # Stock Ledger (query)
    sl_meta = ReportMeta(
        name="Stock Ledger",
        description="Complete record of all stock transactions",
        report_type=ReportType.QUERY,
        module="Stock",
        category="Inventory Reports"
    )
    sl_report = QueryReport(
        meta=sl_meta,
        sql_file=os.path.join(sql_dir, "stock_ledger_query.sql"),
        columns=STOCK_LEDGER_COLUMNS
    )
    engine.register_report(sl_report)

    # Stock Balance (single item) - SafeQueryReport
    sb_meta = ReportMeta(
        name="Stock Balance",
        description="Opening, In, Out, Balance for a single Item + Warehouse",
        report_type=ReportType.QUERY,
        module="Stock",
        category="Inventory Reports",
    )
    sb_report = SafeQueryReport(
        meta=sb_meta,
        sql_file=os.path.join(sql_dir, "stock_balance_single_item.sql"),
        columns=STOCK_BALANCE_SINGLE_ITEM_COLUMNS_FULL,
        required_all=["company"],
        required_any_groups=[["item_id", "item"]],
        columns_selector=lambda f: (
            STOCK_BALANCE_SINGLE_ITEM_COLUMNS_COMPACT if _bool(f.get("compact"))
            else STOCK_BALANCE_SINGLE_ITEM_COLUMNS_FULL
        ),
    )
    engine.register_report(sb_report)

    # Item Stock Ledger
    isl_meta = ReportMeta(
        name="Item Stock Ledger",
        description="Movement history for a single Item + Warehouse",
        report_type=ReportType.QUERY,
        module="Stock",
        category="Inventory Reports",
    )
    isl_report = SafeQueryReport(
        meta=isl_meta,
        sql_file=os.path.join(sql_dir, "item_stock_ledger.sql"),
        columns=ITEM_STOCK_LEDGER_COLUMNS_FULL,
        required_all=["company"],
        required_any_groups=[["item_id", "item"]],
        columns_selector=lambda f: (
            ITEM_STOCK_LEDGER_COLUMNS_COMPACT if _bool(f.get("compact"))
            else ITEM_STOCK_LEDGER_COLUMNS_FULL
        ),
    )
    engine.register_report(isl_report)

    # Balance Sheet (script)
    bs_meta = ReportMeta(
        name="Balance Sheet",
        description="Snapshot of company's financial position",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Financial Statements"
    )
    bs_report = ScriptReport(meta=bs_meta, script_class=BalanceSheetReport)
    engine.register_report(bs_report)

    # Profit & Loss (script)
    pl_meta = ReportMeta(
        name="Profit and Loss Statement",
        description="Company profitability over a period",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Financial Statements"
    )
    from app.application_reports.scripts.profit_loss import ProfitLossReport
    pl_report = ScriptReport(meta=pl_meta, script_class=ProfitLossReport)
    engine.register_report(pl_report)

    # Trial Balance (query)
    tb_meta = ReportMeta(
        name="Trial Balance",
        description="Summary of all account balances",
        report_type=ReportType.QUERY,
        module="Accounts",
        category="Financial Statements"
    )
    tb_report = QueryReport(
        meta=tb_meta,
        sql_file=os.path.join(sql_dir, "trial_balance_query.sql"),
        columns=TRIAL_BALANCE_COLUMNS
    )
    engine.register_report(tb_report)

    # ============================================================================
    # 2. ACCOUNTS RECEIVABLE REPORTS
    # ============================================================================

    from app.application_reports.scripts.accounts_receivable import (
        AccountsReceivableSummary, AccountsReceivableDetail
    )

    # AR Summary
    ar_summary_meta = ReportMeta(
        name="Accounts Receivable Summary",
        description="Customer outstanding balances with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Receivable Reports",
        cache_enabled=False,
        cache_ttl_s=0
    )
    engine.register_report(ScriptReport(meta=ar_summary_meta, script_class=AccountsReceivableSummary))

    # AR Detail - clear name
    ar_detail_meta = ReportMeta(
        name="Accounts Receivable Detail",
        description="Per-invoice receivable with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Receivable Reports",
        cache_enabled=False,
        cache_ttl_s=0
    )
    engine.register_report(ScriptReport(meta=ar_detail_meta, script_class=AccountsReceivableDetail))


    # ============================================================================
    # 3. ACCOUNTS PAYABLE REPORTS
    # ============================================================================

    from app.application_reports.scripts.accounts_payable import (
        AccountsPayableSummary, AccountsPayableDetail
    )
    # Cash Flow (script)
    cf_meta = ReportMeta(
        name="Cash Flow Statement",
        description="Cash movement from Operations, Investing, and Financing",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Financial Statements"
    )
    cf_report = ScriptReport(meta=cf_meta, script_class=CashFlowReport)
    engine.register_report(cf_report)

    # AP Summary
    ap_summary_meta = ReportMeta(
        name="Accounts Payable Summary",
        description="Supplier outstanding balances with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Payable Reports",
        cache_enabled=False,
        cache_ttl_s=0
    )
    engine.register_report(ScriptReport(meta=ap_summary_meta, script_class=AccountsPayableSummary))

    # AP Detail
    ap_detail_meta = ReportMeta(
        name="Accounts Payable Detail",
        description="Per-invoice payable with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Payable Reports",
        cache_enabled=False,
        cache_ttl_s=0
    )
    engine.register_report(ScriptReport(meta=ap_detail_meta, script_class=AccountsPayableDetail))

    log.info(f"✅ Bootstrapped {len(engine.list_reports())} reports")
    log.info(f"📊 Categories: {set(r['category'] for r in engine.list_reports())}")
