# app/application_reports/scripts/accounts_receivable.py
from __future__ import annotations
from typing import Dict, Any, List, Optional

from app.application_reports.core.accounting_utils import ReportAccountTypeEnum
from app.application_reports.scripts.receivable_payable_base import ReceivablePayableReport



# ================ CONCRETE IMPLEMENTATIONS ================
# These should be in a separate file, but included here for completeness

class AccountsReceivableDetail(ReceivablePayableReport):
    """Accounts Receivable Detail Report"""
    def __init__(self):
        super().__init__(ReportAccountTypeEnum.RECEIVABLE, is_summary=False)


class AccountsReceivableSummary(ReceivablePayableReport):
    """Accounts Receivable Summary Report"""
    def __init__(self):
        super().__init__(ReportAccountTypeEnum.RECEIVABLE, is_summary=True)


