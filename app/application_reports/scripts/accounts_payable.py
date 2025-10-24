# app/application_reports/scripts/accounts_payable.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta

from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.models import Account, AccountBalance, AccountTypeEnum
from app.application_reports.core.engine import ReportMeta, ReportType, ColumnDefinition, FilterDefinition
from app.application_reports.core.columns import BALANCE_SHEET_COLUMNS, company_filter, PROFIT_LOSS_COLUMNS, \
    date_range_filters, ACCOUNTS_RECEIVABLE_COLUMNS

log = logging.getLogger(__name__)


class AccountsPayableReport:
    @classmethod
    def get_columns(cls, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        # Reuse AR columns but rename for AP
        columns = ACCOUNTS_RECEIVABLE_COLUMNS.copy()
        for col in columns:
            if col['fieldname'] == 'customer':
                col['label'] = 'Supplier'
                col['options'] = 'Supplier'
            elif col['fieldname'] == 'customer_name':
                col['label'] = 'Supplier Name'
        return columns

    @classmethod
    def get_filters(cls) -> List[FilterDefinition]:
        return [
            company_filter(),
            {
                "fieldname": "report_date",
                "label": "As On Date",
                "fieldtype": "Date",
                "default": datetime.now().date().isoformat(),
                "required": True
            },
            {
                "fieldname": "supplier",
                "label": "Supplier",
                "fieldtype": "Link",
                "options": "Supplier"
            },
            {
                "fieldname": "supplier_group",
                "label": "Supplier Group",
                "fieldtype": "Link",
                "options": "Supplier Group"
            }
        ]

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        # Implementation similar to AccountsReceivableReport but for suppliers
        # This is a simplified placeholder

        return {
            "data": [],
            "summary": {},
            "chart": {},
            "filters": filters
        }