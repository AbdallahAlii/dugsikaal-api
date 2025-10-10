# app/application_reports/scripts/profit_loss.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_

from app.security.rbac_effective import AffiliationContext


from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.models import Account, AccountBalance, AccountTypeEnum
from app.application_reports.core.engine import ReportMeta, ReportType, ColumnDefinition, FilterDefinition
from app.application_reports.core.columns import BALANCE_SHEET_COLUMNS, company_filter, PROFIT_LOSS_COLUMNS, \
    date_range_filters

log = logging.getLogger(__name__)


class ProfitLossReport:
    @classmethod
    def get_columns(cls, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        return PROFIT_LOSS_COLUMNS

    @classmethod
    def get_filters(cls) -> List[FilterDefinition]:
        return [
            company_filter(),
            *date_range_filters(),
            {
                "fieldname": "fiscal_year",
                "label": "Fiscal Year",
                "fieldtype": "Link",
                "options": "Fiscal Year"
            },
            {
                "fieldname": "show_zero_rows",
                "label": "Show Zero Amount Rows",
                "fieldtype": "Check",
                "default": False
            },
            {
                "fieldname": "include_provisional",
                "label": "Include Provisional Entries",
                "fieldtype": "Check",
                "default": False
            },
            {
                "fieldname": "show_percentage",
                "label": "Show Percentage Column",
                "fieldtype": "Check",
                "default": True
            }
        ]

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        self.validate_filters(filters)

        company_id = filters['company']
        from_date = filters['from_date']
        to_date = filters['to_date']
        show_zero_rows = filters.get('show_zero_rows', False)

        # Get revenue and expense accounts
        revenue_accounts = self._get_account_balances(session, company_id, AccountTypeEnum.INCOME, from_date, to_date)
        expense_accounts = self._get_account_balances(session, company_id, AccountTypeEnum.EXPENSE, from_date, to_date)

        # Build hierarchical report data
        data = self._build_report_data(revenue_accounts, expense_accounts, filters)

        # Calculate summary
        summary = self._calculate_summary(revenue_accounts, expense_accounts)

        # Generate chart data
        chart = self._generate_chart_data(revenue_accounts, expense_accounts)

        return {
            "data": data,
            "summary": summary,
            "chart": chart,
            "filters": filters
        }

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        if not filters.get('company'):
            raise ValueError("Company is required for Profit and Loss Statement")

        if not filters.get('from_date') or not filters.get('to_date'):
            raise ValueError("From Date and To Date are required for Profit and Loss Statement")

    def _get_account_balances(self, session: Session, company_id: int,
                              account_type: AccountTypeEnum, from_date: datetime, to_date: datetime) -> List[
        Dict[str, Any]]:
        try:
            # Simplified implementation - adjust based on your actual models
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

    def _build_report_data(self, revenue_accounts: List[Dict], expense_accounts: List[Dict],
                           filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = []
        show_zero_rows = filters.get('show_zero_rows', False)
        show_percentage = filters.get('show_percentage', True)

        # Calculate total revenue for percentages
        total_revenue = sum(acc['balance'] for acc in revenue_accounts if not acc['is_group'])

        # Revenue section
        data.append({
            "account": "REVENUE",
            "amount": 0,
            "indent": 0,
            "is_group": True,
            "bold": True,
            "account_type": "header"
        })

        total_revenue_calc = self._add_accounts_hierarchically(data, revenue_accounts, 1, show_zero_rows, total_revenue,
                                                               show_percentage)

        data.append({
            "account": "Total Revenue",
            "amount": total_revenue_calc,
            "indent": 0,
            "bold": True,
            "account_type": "total"
        })

        data.append({"account": "", "amount": "", "indent": 0})  # Spacer

        # Expenses section
        data.append({
            "account": "EXPENSES",
            "amount": 0,
            "indent": 0,
            "is_group": True,
            "bold": True,
            "account_type": "header"
        })

        total_expenses = self._add_accounts_hierarchically(data, expense_accounts, 1, show_zero_rows, total_revenue,
                                                           show_percentage)

        data.append({
            "account": "Total Expenses",
            "amount": total_expenses,
            "indent": 0,
            "bold": True,
            "account_type": "total"
        })

        data.append({"account": "", "amount": "", "indent": 0})  # Spacer

        # Net Profit/Loss
        net_profit = total_revenue_calc - total_expenses
        data.append({
            "account": "NET PROFIT",
            "amount": net_profit,
            "indent": 0,
            "bold": True,
            "account_type": "net_total"
        })

        return data

    def _add_accounts_hierarchically(self, data: List[Dict], accounts: List[Dict],
                                     indent: int, show_zero_rows: bool,
                                     total_revenue: float, show_percentage: bool) -> float:
        root_accounts = [acc for acc in accounts if acc.get('level', 0) == 0]
        total = 0.0

        for account in root_accounts:
            if not show_zero_rows and abs(account["balance"]) < 0.01:
                continue

            row_data = {
                "account": account["name"],
                "amount": account["balance"],
                "indent": indent,
                "is_group": account["is_group"],
                "account_code": account["code"],
                "account_type": "account"
            }

            if show_percentage and total_revenue and not account["is_group"]:
                row_data["percentage"] = round((account["balance"] / total_revenue) * 100, 1)

            data.append(row_data)

            if account["is_group"]:
                child_total = self._add_child_accounts(data, accounts, account["id"], indent + 1, show_zero_rows,
                                                       total_revenue, show_percentage)
                data.append({
                    "account": f"Total {account['name']}",
                    "amount": child_total,
                    "indent": indent,
                    "bold": True,
                    "account_type": "subtotal"
                })
                total += child_total
            else:
                total += account["balance"]

        return total

    def _add_child_accounts(self, data: List[Dict], accounts: List[Dict],
                            parent_id: int, indent: int, show_zero_rows: bool,
                            total_revenue: float, show_percentage: bool) -> float:
        child_accounts = [acc for acc in accounts if acc.get('parent_account_id') == parent_id]
        total = 0.0

        for account in child_accounts:
            if not show_zero_rows and abs(account["balance"]) < 0.01:
                continue

            row_data = {
                "account": account["name"],
                "amount": account["balance"],
                "indent": indent,
                "is_group": account["is_group"],
                "account_code": account["code"],
                "account_type": "account"
            }

            if show_percentage and total_revenue and not account["is_group"]:
                row_data["percentage"] = round((account["balance"] / total_revenue) * 100, 1)

            data.append(row_data)

            if account["is_group"]:
                grandchild_total = self._add_child_accounts(data, accounts, account["id"], indent + 1, show_zero_rows,
                                                            total_revenue, show_percentage)
                data.append({
                    "account": f"Total {account['name']}",
                    "amount": grandchild_total,
                    "indent": indent,
                    "bold": True,
                    "account_type": "subtotal"
                })
                total += grandchild_total
            else:
                total += account["balance"]

        return total

    def _calculate_summary(self, revenue_accounts: List[Dict], expense_accounts: List[Dict]) -> Dict[str, Any]:
        total_revenue = sum(acc['balance'] for acc in revenue_accounts if not acc['is_group'])
        total_expenses = sum(acc['balance'] for acc in expense_accounts if not acc['is_group'])
        net_profit = total_revenue - total_expenses

        gross_profit_margin = (net_profit / total_revenue * 100) if total_revenue else 0
        operating_margin = (net_profit / total_revenue * 100) if total_revenue else 0

        return {
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "gross_profit_margin": round(gross_profit_margin, 2),
            "operating_margin": round(operating_margin, 2)
        }

    def _generate_chart_data(self, revenue_accounts: List[Dict], expense_accounts: List[Dict]) -> Dict[str, Any]:
        total_revenue = sum(acc['balance'] for acc in revenue_accounts if not acc['is_group'])
        total_expenses = sum(acc['balance'] for acc in expense_accounts if not acc['is_group'])
        net_profit = total_revenue - total_expenses

        return {
            "type": "bar",
            "title": "Profit and Loss Overview",
            "data": {
                "labels": ["Revenue", "Expenses", "Net Profit"],
                "datasets": [{
                    "name": "Amount",
                    "values": [total_revenue, total_expenses, net_profit],
                    "colors": ["#28a745", "#dc3545", "#007bff"]
                }]
            },
            "height": 300
        }