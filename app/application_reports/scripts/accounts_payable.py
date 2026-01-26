# app/application_reports/scripts/accounts_payable.py
from __future__ import annotations
from typing import Dict, Any, List, Optional

from app.application_reports.core.accounting_utils import ReportAccountTypeEnum
from app.application_reports.scripts.receivable_payable_base import ReceivablePayableReport


class AccountsPayableSummary(ReceivablePayableReport):
    """
    Accounts Payable Summary Report (grouped by Supplier)
    """

    def __init__(self):
        super().__init__(account_type=ReportAccountTypeEnum.PAYABLE, is_summary=True)


class AccountsPayableDetail(ReceivablePayableReport):
    """
    Accounts Payable Detail Report (per Purchase Invoice)
    """

    def __init__(self):
        super().__init__(account_type=ReportAccountTypeEnum.PAYABLE, is_summary=False)