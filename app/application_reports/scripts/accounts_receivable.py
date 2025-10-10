# app/application_reports/scripts/accounts_receivable.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, case, or_

from app.security.rbac_effective import AffiliationContext
from app.application_reports.core.engine import ReportMeta, ReportType, ColumnDefinition, FilterDefinition
from app.application_reports.core.columns import ACCOUNTS_RECEIVABLE_COLUMNS, company_filter, date_range_filters

log = logging.getLogger(__name__)


class AccountsReceivableReport:
    @classmethod
    def get_columns(cls, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        return ACCOUNTS_RECEIVABLE_COLUMNS

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
                "fieldname": "ageing_based_on",
                "label": "Ageing Based On",
                "fieldtype": "Select",
                "options": "Due Date\nPosting Date",
                "default": "Due Date"
            },
            {
                "fieldname": "customer",
                "label": "Customer",
                "fieldtype": "Link",
                "options": "Customer"
            },
            {
                "fieldname": "customer_group",
                "label": "Customer Group",
                "fieldtype": "Link",
                "options": "Customer Group"
            },
            {
                "fieldname": "territory",
                "label": "Territory",
                "fieldtype": "Link",
                "options": "Territory"
            },
            {
                "fieldname": "range1",
                "label": "Range 1 (Days)",
                "fieldtype": "Int",
                "default": 30
            },
            {
                "fieldname": "range2",
                "label": "Range 2 (Days)",
                "fieldtype": "Int",
                "default": 60
            },
            {
                "fieldname": "range3",
                "label": "Range 3 (Days)",
                "fieldtype": "Int",
                "default": 90
            },
            {
                "fieldname": "range4",
                "label": "Range 4 (Days)",
                "fieldtype": "Int",
                "default": 120
            }
        ]

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> Dict[str, Any]:
        self.validate_filters(filters)

        company_id = filters['company']
        report_date = filters.get('report_date', date.today())
        ageing_based_on = filters.get('ageing_based_on', 'Due Date')

        # Get ageing ranges
        range1 = int(filters.get('range1', 30))
        range2 = int(filters.get('range2', 60))
        range3 = int(filters.get('range3', 90))
        range4 = int(filters.get('range4', 120))

        # Get customer outstanding data with ageing
        customers_data = self._get_customers_outstanding(
            session, company_id, report_date, ageing_based_on,
            range1, range2, range3, range4, filters
        )

        summary = self._calculate_summary(customers_data)
        chart = self._generate_chart_data(customers_data)

        return {
            "data": customers_data,
            "summary": summary,
            "chart": chart,
            "filters": filters,
            "ageing_ranges": {
                "range1": f"0-{range1} Days",
                "range2": f"{range1 + 1}-{range2} Days",
                "range3": f"{range2 + 1}-{range3} Days",
                "range4": f"{range3 + 1}+ Days"
            }
        }

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        if not filters.get('company'):
            raise ValueError("Company is required for Accounts Receivable Summary")

    def _get_customers_outstanding(self, session: Session, company_id: int,
                                   report_date: date, ageing_based_on: str,
                                   range1: int, range2: int, range3: int, range4: int,
                                   filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            # This is a placeholder implementation - replace with your actual models
            # For demonstration, we'll return sample data

            sample_customers = [
                {
                    "customer": "CUST-001",
                    "customer_name": "Customer One Pvt Ltd",
                    "total_invoiced": 15000.00,
                    "total_paid": 5000.00,
                    "total_credit_note": 500.00,
                    "outstanding_amount": 9500.00,
                    "invoices": [
                        {"due_date": report_date - timedelta(days=15), "amount": 3000.00},
                        {"due_date": report_date - timedelta(days=45), "amount": 4000.00},
                        {"due_date": report_date - timedelta(days=75), "amount": 2500.00},
                    ]
                },
                {
                    "customer": "CUST-002",
                    "customer_name": "Customer Two Inc",
                    "total_invoiced": 8000.00,
                    "total_paid": 3000.00,
                    "total_credit_note": 200.00,
                    "outstanding_amount": 4800.00,
                    "invoices": [
                        {"due_date": report_date - timedelta(days=25), "amount": 2000.00},
                        {"due_date": report_date - timedelta(days=100), "amount": 2800.00},
                    ]
                },
                {
                    "customer": "CUST-003",
                    "customer_name": "Customer Three LLC",
                    "total_invoiced": 12000.00,
                    "total_paid": 8000.00,
                    "total_credit_note": 1000.00,
                    "outstanding_amount": 3000.00,
                    "invoices": [
                        {"due_date": report_date - timedelta(days=5), "amount": 1500.00},
                        {"due_date": report_date - timedelta(days=35), "amount": 1500.00},
                    ]
                }
            ]

            # Apply customer filter if provided
            if filters.get('customer'):
                sample_customers = [c for c in sample_customers if c['customer'] == filters['customer']]

            # Calculate ageing buckets for each customer
            for customer in sample_customers:
                ageing_buckets = self._calculate_ageing_buckets(
                    customer["invoices"], report_date, range1, range2, range3, range4
                )
                customer.update(ageing_buckets)
                # Remove detailed invoices from final data
                customer.pop("invoices", None)

            return sample_customers

        except Exception as e:
            log.error(f"Error fetching accounts receivable data: {e}")
            raise

    def _calculate_ageing_buckets(self, invoices: List[Dict], report_date: date,
                                  range1: int, range2: int, range3: int, range4: int) -> Dict[str, float]:
        range1_amount = 0.0
        range2_amount = 0.0
        range3_amount = 0.0
        range4_amount = 0.0

        for invoice in invoices:
            days_outstanding = (report_date - invoice["due_date"]).days

            if days_outstanding <= range1:
                range1_amount += invoice["amount"]
            elif days_outstanding <= range2:
                range2_amount += invoice["amount"]
            elif days_outstanding <= range3:
                range3_amount += invoice["amount"]
            else:
                range4_amount += invoice["amount"]

        return {
            "range1": range1_amount,
            "range2": range2_amount,
            "range3": range3_amount,
            "range4": range4_amount
        }

    def _calculate_summary(self, customers_data: List[Dict]) -> Dict[str, Any]:
        total_outstanding = sum(cust["outstanding_amount"] for cust in customers_data)
        total_range1 = sum(cust["range1"] for cust in customers_data)
        total_range2 = sum(cust["range2"] for cust in customers_data)
        total_range3 = sum(cust["range3"] for cust in customers_data)
        total_range4 = sum(cust["range4"] for cust in customers_data)

        # Calculate percentages
        total_ageing = total_range1 + total_range2 + total_range3 + total_range4
        pct_range1 = (total_range1 / total_ageing * 100) if total_ageing else 0
        pct_range2 = (total_range2 / total_ageing * 100) if total_ageing else 0
        pct_range3 = (total_range3 / total_ageing * 100) if total_ageing else 0
        pct_range4 = (total_range4 / total_ageing * 100) if total_ageing else 0

        return {
            "total_customers": len(customers_data),
            "total_outstanding": total_outstanding,
            "total_range1": total_range1,
            "total_range2": total_range2,
            "total_range3": total_range3,
            "total_range4": total_range4,
            "pct_range1": round(pct_range1, 1),
            "pct_range2": round(pct_range2, 1),
            "pct_range3": round(pct_range3, 1),
            "pct_range4": round(pct_range4, 1),
        }

    def _generate_chart_data(self, customers_data: List[Dict]) -> Dict[str, Any]:
        total_range1 = sum(cust["range1"] for cust in customers_data)
        total_range2 = sum(cust["range2"] for cust in customers_data)
        total_range3 = sum(cust["range3"] for cust in customers_data)
        total_range4 = sum(cust["range4"] for cust in customers_data)

        return {
            "type": "bar",
            "title": "Accounts Receivable Ageing Analysis",
            "data": {
                "labels": ["0-30 Days", "31-60 Days", "61-90 Days", "90+ Days"],
                "datasets": [{
                    "name": "Outstanding Amount",
                    "values": [total_range1, total_range2, total_range3, total_range4],
                    "colors": ["#28a745", "#ffc107", "#fd7e14", "#dc3545"]
                }]
            },
            "height": 300
        }