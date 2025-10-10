# app/application_reports/scripts/balance_sheet.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.models import Account, AccountBalance, AccountTypeEnum
from app.application_reports.core.engine import ReportMeta, ReportType, ColumnDefinition, FilterDefinition
from app.application_reports.core.columns import BALANCE_SHEET_COLUMNS, company_filter

log = logging.getLogger(__name__)


class BalanceSheetReport:
    @classmethod
    def get_columns(cls, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        return BALANCE_SHEET_COLUMNS

    @classmethod
    def get_filters(cls) -> List[FilterDefinition]:
        return [
            company_filter(),
            {
                "fieldname": "fiscal_year",
                "label": "Fiscal Year",
                "fieldtype": "Link",
                "options": "Fiscal Year",
                "required": True
            },
            {
                "fieldname": "period_date",
                "label": "As On Date",
                "fieldtype": "Date",
                "default": datetime.now().date().isoformat(),
                "required": True
            },
            {
                "fieldname": "show_zero_rows",
                "label": "Show Zero Amount Rows",
                "fieldtype": "Check",
                "default": False
            },
            {
                "fieldname": "show_unclosed_fy_pl",
                "label": "Show Unclosed FY P&L",
                "fieldtype": "Check",
                "default": True
            },
            {
                "fieldname": "include_provisional",
                "label": "Include Provisional Entries",
                "fieldtype": "Check",
                "default": False
            }
        ]

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        self.validate_filters(filters)

        company_id = filters['company']
        period_date = filters['period_date']
        show_zero_rows = filters.get('show_zero_rows', False)

        # Get account balances with hierarchy
        assets = self._get_account_balances(session, company_id, AccountTypeEnum.ASSET, period_date)
        liabilities = self._get_account_balances(session, company_id, AccountTypeEnum.LIABILITY, period_date)
        equity = self._get_account_balances(session, company_id, AccountTypeEnum.EQUITY, period_date)

        # Build hierarchical report data
        data = self._build_report_data(assets, liabilities, equity, filters)

        # Calculate summary
        summary = self._calculate_summary(assets, liabilities, equity)

        # Generate chart data
        chart = self._generate_chart_data(assets, liabilities, equity)

        return {
            "data": data,
            "summary": summary,
            "chart": chart,
            "filters": filters
        }

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        if not filters.get('company'):
            raise ValueError("Company is required for Balance Sheet")

        if not filters.get('period_date'):
            raise ValueError("As On Date is required for Balance Sheet")

    def _get_account_balances(self, session: Session, company_id: int,
                              account_type: AccountTypeEnum, period_date: datetime) -> List[Dict[str, Any]]:
        try:
            # This is a simplified implementation - adjust based on your actual models
            query = select(
                Account.id,
                Account.code,
                Account.name,
                Account.is_group,
                Account.parent_account_id,
                Account.level,
                AccountBalance.current_balance
            ).join(
                AccountBalance, Account.id == AccountBalance.account_id
            ).where(
                and_(
                    Account.company_id == company_id,
                    Account.account_type == account_type,
                    Account.status == 'SUBMITTED'
                )
            )

            result = session.execute(query)
            accounts = []

            for row in result:
                accounts.append({
                    "id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "is_group": row.is_group,
                    "parent_account_id": row.parent_account_id,
                    "level": row.level,
                    "balance": float(row.current_balance or 0),
                    "account_type": account_type.value
                })

            return accounts

        except Exception as e:
            log.error(f"Error fetching account balances: {e}")
            raise

    def _build_report_data(self, assets: List[Dict], liabilities: List[Dict],
                           equity: List[Dict], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = []
        show_zero_rows = filters.get('show_zero_rows', False)

        # Assets section header
        data.append({
            "account": "ASSETS",
            "balance": 0,
            "indent": 0,
            "is_group": True,
            "bold": True,
            "account_type": "header"
        })

        total_assets = self._add_accounts_hierarchically(data, assets, 1, show_zero_rows)

        data.append({
            "account": "Total Assets",
            "balance": total_assets,
            "indent": 0,
            "bold": True,
            "account_type": "total"
        })

        data.append({"account": "", "balance": "", "indent": 0})  # Spacer

        # Liabilities & Equity section
        data.append({
            "account": "LIABILITIES AND EQUITY",
            "balance": 0,
            "indent": 0,
            "is_group": True,
            "bold": True,
            "account_type": "header"
        })

        total_liabilities = self._add_accounts_hierarchically(data, liabilities, 1, show_zero_rows)
        total_equity = self._add_accounts_hierarchically(data, equity, 1, show_zero_rows)

        total_liabilities_equity = total_liabilities + total_equity

        # Add subtotals
        data.append({
            "account": "Total Liabilities",
            "balance": total_liabilities,
            "indent": 1,
            "bold": True,
            "account_type": "subtotal"
        })

        data.append({
            "account": "Total Equity",
            "balance": total_equity,
            "indent": 1,
            "bold": True,
            "account_type": "subtotal"
        })

        data.append({
            "account": "Total Liabilities and Equity",
            "balance": total_liabilities_equity,
            "indent": 0,
            "bold": True,
            "account_type": "total"
        })

        return data

    def _add_accounts_hierarchically(self, data: List[Dict], accounts: List[Dict],
                                     indent: int, show_zero_rows: bool) -> float:
        root_accounts = [acc for acc in accounts if acc.get('level', 0) == 0]
        total = 0.0

        for account in root_accounts:
            if not show_zero_rows and abs(account["balance"]) < 0.01:
                continue

            data.append({
                "account": account["name"],
                "balance": account["balance"],
                "indent": indent,
                "is_group": account["is_group"],
                "account_code": account["code"],
                "account_type": "account"
            })

            if account["is_group"]:
                child_total = self._add_child_accounts(data, accounts, account["id"], indent + 1, show_zero_rows)
                data.append({
                    "account": f"Total {account['name']}",
                    "balance": child_total,
                    "indent": indent,
                    "bold": True,
                    "account_type": "subtotal"
                })
                total += child_total
            else:
                total += account["balance"]

        return total

    def _add_child_accounts(self, data: List[Dict], accounts: List[Dict],
                            parent_id: int, indent: int, show_zero_rows: bool) -> float:
        child_accounts = [acc for acc in accounts if acc.get('parent_account_id') == parent_id]
        total = 0.0

        for account in child_accounts:
            if not show_zero_rows and abs(account["balance"]) < 0.01:
                continue

            data.append({
                "account": account["name"],
                "balance": account["balance"],
                "indent": indent,
                "is_group": account["is_group"],
                "account_code": account["code"],
                "account_type": "account"
            })

            if account["is_group"]:
                grandchild_total = self._add_child_accounts(data, accounts, account["id"], indent + 1, show_zero_rows)
                data.append({
                    "account": f"Total {account['name']}",
                    "balance": grandchild_total,
                    "indent": indent,
                    "bold": True,
                    "account_type": "subtotal"
                })
                total += grandchild_total
            else:
                total += account["balance"]

        return total

    def _calculate_summary(self, assets: List[Dict], liabilities: List[Dict],
                           equity: List[Dict]) -> Dict[str, Any]:
        total_assets = sum(acc['balance'] for acc in assets if not acc['is_group'])
        total_liabilities = sum(acc['balance'] for acc in liabilities if not acc['is_group'])
        total_equity = sum(acc['balance'] for acc in equity if not acc['is_group'])

        debt_to_equity = total_liabilities / total_equity if total_equity else 0
        current_ratio = total_assets / total_liabilities if total_liabilities else 0

        return {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_worth": total_assets - total_liabilities,
            "debt_to_equity": round(debt_to_equity, 2),
            "current_ratio": round(current_ratio, 2)
        }

    def _generate_chart_data(self, assets: List[Dict], liabilities: List[Dict],
                             equity: List[Dict]) -> Dict[str, Any]:
        total_assets = sum(acc['balance'] for acc in assets if not acc['is_group'])
        total_liabilities = sum(acc['balance'] for acc in liabilities if not acc['is_group'])
        total_equity = sum(acc['balance'] for acc in equity if not acc['is_group'])

        return {
            "type": "pie",
            "title": "Balance Sheet Composition",
            "data": {
                "labels": ["Assets", "Liabilities", "Equity"],
                "datasets": [{
                    "name": "Amount",
                    "values": [total_assets, total_liabilities, total_equity],
                    "colors": ["#28a745", "#dc3545", "#007bff"]
                }]
            },
            "height": 300
        }