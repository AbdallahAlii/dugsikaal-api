from __future__ import annotations
import logging
import os
from importlib import import_module
from typing import Dict

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.models import Account, AccountBalance, AccountTypeEnum
from app.application_reports.core.engine import ReportMeta, ReportType, ColumnDefinition, FilterDefinition, \
    ReportEngine, QueryReport, ScriptReport
from app.application_reports.core.columns import BALANCE_SHEET_COLUMNS, company_filter, GL_COLUMNS, \
    STOCK_LEDGER_COLUMNS, TRIAL_BALANCE_COLUMNS

log = logging.getLogger(__name__)


def bootstrap_reports(engine: ReportEngine) -> None:
    """
    Bootstrap all standard reports with Frappe-style metadata
    """

    base_dir = os.path.dirname(__file__)
    sql_dir = os.path.join(base_dir, "sql")

    # Ensure SQL directory exists
    if not os.path.exists(sql_dir):
        os.makedirs(sql_dir)
        log.info(f"Created SQL directory: {sql_dir}")

    # General Ledger Report
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

    # Stock Ledger Report
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

    # Balance Sheet Report
    bs_meta = ReportMeta(
        name="Balance Sheet",
        description="Snapshot of company's financial position",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Financial Statements"
    )
    from app.application_reports.scripts.balance_sheet import BalanceSheetReport
    bs_report = ScriptReport(meta=bs_meta, script_class=BalanceSheetReport)
    engine.register_report(bs_report)

    # Accounts Receivable Summary
    ar_meta = ReportMeta(
        name="Accounts Receivable Summary",
        description="Customer outstanding with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Receivable Reports"
    )
    from app.application_reports.scripts.accounts_receivable import AccountsReceivableReport
    ar_report = ScriptReport(meta=ar_meta, script_class=AccountsReceivableReport)
    engine.register_report(ar_report)

    # Profit and Loss Statement
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

    # Trial Balance
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

    # Accounts Payable Summary
    ap_meta = ReportMeta(
        name="Accounts Payable Summary",
        description="Supplier outstanding with ageing analysis",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Payable Reports"
    )
    # from app.application_reports.scripts.accounts_receivable import AccountsPayableReport
    # ap_report = ScriptReport(meta=ap_meta, script_class=AccountsPayableReport)
    # engine.register_report(ap_report)

    # Bank Reconciliation Statement
    brs_meta = ReportMeta(
        name="Bank Reconciliation Statement",
        description="Reconcile bank statements with company records",
        report_type=ReportType.SCRIPT,
        module="Accounts",
        category="Banking Reports"
    )
    from app.application_reports.scripts.bank_reconciliation import BankReconciliationReport
    brs_report = ScriptReport(meta=brs_meta, script_class=BankReconciliationReport)
    engine.register_report(brs_report)

    log.info(f"✅ Bootstrapped {len(engine.list_reports())} standard reports")


def register_custom_reports(engine: ReportEngine, custom_reports_config: Dict) -> None:
    """
    Register custom reports from configuration
    """
    for report_config in custom_reports_config.get('reports', []):
        try:
            if report_config['type'] == 'query':
                meta = ReportMeta(**report_config['meta'])
                report = QueryReport(
                    meta=meta,
                    sql_file=report_config['sql_file'],
                    columns=report_config.get('columns', [])
                )
                engine.register_report(report)
                log.info(f"Registered custom query report: {meta.name}")

            elif report_config['type'] == 'script':
                meta = ReportMeta(**report_config['meta'])
                script_class = import_string(report_config['script_class'])
                report = ScriptReport(meta=meta, script_class=script_class)
                engine.register_report(report)
                log.info(f"Registered custom script report: {meta.name}")

        except Exception as e:
            log.error(f"Failed to register custom report {report_config.get('name')}: {e}")


def import_string(dotted_path: str):
    """Import a class from dotted path string"""
    module_path, class_name = dotted_path.rsplit('.', 1)
    module = import_module(module_path)
    return getattr(module, class_name)