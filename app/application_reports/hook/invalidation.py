# app/application_reports/hooks/invalidation.py
from __future__ import annotations
import logging
from app.application_reports.core.cache import ReportCache

log = logging.getLogger(__name__)

# One cache client; version-bump based (cheap / O(1))
_rc = ReportCache(enabled=True)

# Key report families
_FINANCIAL_REPORTS = (
    "General Ledger",
    "Accounts Receivable Summary",
    "Accounts Receivable",
    "Accounts Payable Summary",
    "Accounts Payable",
    "Trial Balance",
    "Balance Sheet",
    "Profit and Loss",
)

_STOCK_REPORTS = (
    "Stock Ledger",
    "Stock Balance",
    "Item Stock Ledger",
)

def invalidate_financial_reports_for_company(company_id: int) -> None:
    if not company_id:
        return
    for rpt in _FINANCIAL_REPORTS:
        _rc.bump_company(rpt, company_id)
    log.info("🔥 invalidated FINANCIAL reports for company=%s (bumped %s)", company_id, len(_FINANCIAL_REPORTS))

def invalidate_stock_reports_for_company(company_id: int) -> None:
    if not company_id:
        return
    for rpt in _STOCK_REPORTS:
        _rc.bump_company(rpt, company_id)
    log.info("🔥 invalidated STOCK reports for company=%s (bumped %s)", company_id, len(_STOCK_REPORTS))

def invalidate_all_core_reports_for_company(company_id: int, *, include_stock: bool = True) -> None:
    """
    Convenience for docs that affect both finance and stock (e.g., Sales Invoice with update_stock).
    """
    invalidate_financial_reports_for_company(company_id)
    if include_stock:
        invalidate_stock_reports_for_company(company_id)
