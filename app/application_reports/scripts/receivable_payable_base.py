
# app/application_reports/scripts/receivable_payable_base.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional, Set
from datetime import date, datetime, timedelta
import time

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.application_reports.core.engine import BaseReport, ReportResult, ColumnDefinition, FilterDefinition
from app.security.rbac_effective import AffiliationContext
from app.application_reports.core.date_utils import parse_date_flex, format_date_for_display
from app.application_reports.core.accounting_utils import (
    get_party_types_from_account_type,
    calculate_ageing_buckets,
    get_invoice_outstanding_details,
    get_advance_payments,
    get_credit_notes_for_invoices,
    format_amount,
    get_currency_precision,
    ReportAccountTypeEnum
)

log = logging.getLogger(__name__)


class ReceivablePayableReport(BaseReport):
    """
    Base class for both Accounts Receivable and Accounts Payable reports.
    Follows industry standard: shows only unpaid invoices by default.
    """

    def __init__(self, account_type: ReportAccountTypeEnum, is_summary: bool = True):
        self.account_type = account_type
        self.is_summary = is_summary
        self.party_types = get_party_types_from_account_type(account_type)
        self.party_label = "Customer" if account_type == ReportAccountTypeEnum.RECEIVABLE else "Supplier"
        self.currency_precision = get_currency_precision()

        # Ageing ranges: Current, 1-30, 31-60, 61-90, 91+
        self.ageing_ranges = [0, 30, 60, 90]

    # ================ COLUMNS ================
    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        """Get columns based on report type."""
        is_summary = self.is_summary
        if filters and 'is_summary' in filters:
            try:
                is_summary = bool(filters['is_summary'])
            except (ValueError, TypeError):
                pass

        if is_summary:
            return self._get_summary_columns()
        else:
            return self._get_detail_columns()

    def _get_summary_columns(self) -> List[ColumnDefinition]:
        """Columns for summary report (one row per customer)."""
        columns = [
            {"fieldname": "party_id", "label": f"{self.party_label} ID", "fieldtype": "Int", "width": 80,
             "hidden": True},
            {"fieldname": "party_name", "label": self.party_label, "fieldtype": "Data", "width": 220},
            {"fieldname": "party_code", "label": f"{self.party_label} Code", "fieldtype": "Data", "width": 120},
            {"fieldname": "total_invoiced", "label": "Total Invoiced", "fieldtype": "Currency", "width": 120},
            {"fieldname": "outstanding_amount", "label": "Total Balance", "fieldtype": "Currency", "width": 120},
            {"fieldname": "current_range", "label": "Current", "fieldtype": "Currency", "width": 100},
            {"fieldname": "range1_30", "label": "1-30 Days", "fieldtype": "Currency", "width": 100},
            {"fieldname": "range31_60", "label": "31-60 Days", "fieldtype": "Currency", "width": 100},
            {"fieldname": "range61_90", "label": "61-90 Days", "fieldtype": "Currency", "width": 100},
            {"fieldname": "range91_plus", "label": "91+ Days", "fieldtype": "Currency", "width": 100},
        ]
        return columns

    def _get_detail_columns(self) -> List[ColumnDefinition]:
        """Columns for detail report (one row per invoice)."""
        columns = [
            {"fieldname": "party_name", "label": self.party_label, "fieldtype": "Data", "width": 200},
            {"fieldname": "posting_date", "label": "Invoice Date", "fieldtype": "Date", "width": 100},
            {"fieldname": "voucher_type", "label": "Invoice Type", "fieldtype": "Data", "width": 100},
            {"fieldname": "voucher_no", "label": "Invoice No", "fieldtype": "Data", "width": 160},
            {"fieldname": "due_date", "label": "Due Date", "fieldtype": "Date", "width": 100},
            {"fieldname": "invoice_amount", "label": "Invoice Amount", "fieldtype": "Currency", "width": 120},
            {"fieldname": "paid_amount", "label": "Paid Amount", "fieldtype": "Currency", "width": 120},
            {"fieldname": "outstanding_amount", "label": "Balance", "fieldtype": "Currency", "width": 120},
            {"fieldname": "age", "label": "Age (Days)", "fieldtype": "Int", "width": 80},
            {"fieldname": "current_range", "label": "Current", "fieldtype": "Currency", "width": 90},
            {"fieldname": "range1_30", "label": "1-30 Days", "fieldtype": "Currency", "width": 90},
            {"fieldname": "range31_60", "label": "31-60 Days", "fieldtype": "Currency", "width": 90},
            {"fieldname": "range61_90", "label": "61-90 Days", "fieldtype": "Currency", "width": 90},
            {"fieldname": "range91_plus", "label": "91+ Days", "fieldtype": "Currency", "width": 90},
            {"fieldname": "doc_status", "label": "Status", "fieldtype": "Data", "width": 100},
        ]
        return columns

    # ================ FILTERS ================
    def get_filters(self) -> List[FilterDefinition]:
        """Get filter definitions for the report."""
        filters = [
            {
                "fieldname": "company",
                "label": "Company",
                "fieldtype": "Link",
                "options": "Company",
                "required": True
            },
            {
                "fieldname": "report_date",
                "label": "As On Date",
                "fieldtype": "Date",
                "required": True,
                "default": date.today()
            },
            {
                "fieldname": "party",
                "label": self.party_label,
                "fieldtype": "Link",
                "options": f"{self.party_label}"
            },
            {
                "fieldname": "show_zero_balance",
                "label": "Show Zero Balance",
                "fieldtype": "Check",
                "default": False
            },
            {
                "fieldname": "ageing_based_on",
                "label": "Ageing Based On",
                "fieldtype": "Select",
                "options": "Due Date\nPosting Date",
                "default": "Due Date"
            }
        ]
        return filters

    # ================ MAIN EXECUTION ================
    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        """Main execution method."""
        start_time = time.time()

        try:
            self._validate_filters(filters)
            prepared_filters = self._prepare_filters(filters)

            # Get data based on report type
            if self.is_summary:
                data = self._get_summary_data(prepared_filters, session)
            else:
                data = self._get_detail_data(prepared_filters, session)

            execution_time = time.time() - start_time

            return {
                "columns": self.get_columns(prepared_filters),
                "data": data,
                "filters": self._format_filters_for_output(prepared_filters),
                "report_name": self.__class__.__name__,
                "execution_time": execution_time,
                "total_count": len(data),
                "summary": self._get_report_summary(data, prepared_filters),
                "chart": self._get_chart_data(data, prepared_filters),
                "has_more": False,
                "next_cursor": None,
            }

        except Exception as e:
            log.error(f"Error executing {self.__class__.__name__}: {e}", exc_info=True)
            raise

    # ================ FILTER PROCESSING ================
    def _validate_filters(self, filters: Dict[str, Any]) -> None:
        """Validate required filters."""
        if not filters.get("company"):
            raise ValueError("Company is required")

        report_date = parse_date_flex(filters.get("report_date"))
        if not report_date:
            raise ValueError("Valid report date is required")

    def _prepare_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare and normalize filters."""
        prepared = filters.copy()

        # Parse report date
        report_date = parse_date_flex(filters.get("report_date"))
        if not report_date:
            raise ValueError("Valid report date is required")

        # Use end of day for date comparison (important for invoices on the same day)
        report_date_end = datetime.combine(report_date, datetime.max.time())
        prepared["report_date"] = report_date
        prepared["report_date_end"] = report_date_end  # For SQL comparison

        # Convert company ID
        try:
            prepared["company"] = int(filters["company"])
        except (ValueError, TypeError):
            raise ValueError(f"Company must be a valid integer ID. Got: {filters.get('company')}")

        # Set defaults
        prepared.setdefault("show_zero_balance", False)
        prepared.setdefault("ageing_based_on", "Due Date")

        return prepared

    def _format_filters_for_output(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Format filters for JSON output."""
        output = filters.copy()

        # Remove internal fields
        if "report_date_end" in output:
            del output["report_date_end"]

        for date_field in ["report_date"]:
            if date_field in output and output[date_field]:
                if isinstance(output[date_field], (date, datetime)):
                    output[date_field] = format_date_for_display(output[date_field])

        return output

    # ================ DETAIL DATA ================
    def _get_detail_data(self, filters: Dict[str, Any], session: Session) -> List[Dict[str, Any]]:
        """Get detail data per invoice."""
        company_id = filters["company"]
        report_date = filters["report_date"]

        if self.account_type == ReportAccountTypeEnum.RECEIVABLE:
            data = self._get_receivable_detail_data(company_id, report_date, session, filters)
        else:
            data = self._get_payable_detail_data(company_id, report_date, session, filters)

        # Calculate ageing for each invoice
        formatted_data = []
        for item in data:
            self._format_detail_item(item, report_date)
            formatted_data.append(item)

        return formatted_data

    def _format_detail_item(self, item: Dict[str, Any], report_date: date) -> None:
        """Format detail item with ageing calculation."""
        # Format dates for display
        for date_field in ["posting_date", "due_date"]:
            dt_field = f"{date_field}_dt"
            if dt_field in item and item[dt_field]:
                # Convert datetime to date for display
                if isinstance(item[dt_field], datetime):
                    item[date_field] = format_date_for_display(item[dt_field].date())
                else:
                    item[date_field] = format_date_for_display(item[dt_field])

        # Calculate age and ageing buckets
        due_date_dt = item.get("due_date_dt") or item.get("posting_date_dt")
        if due_date_dt:
            # Extract date part from datetime
            if isinstance(due_date_dt, datetime):
                due_date_date = due_date_dt.date()
            else:
                due_date_date = due_date_dt

            # Calculate age in days
            age_days = (report_date - due_date_date).days
            item["age"] = max(0, age_days)

            # Calculate ageing buckets
            outstanding = item.get("outstanding_amount", 0)
            if outstanding > 0:
                # Industry standard ageing buckets
                if age_days <= 0:
                    item["current_range"] = outstanding
                    item["range1_30"] = 0.0
                    item["range31_60"] = 0.0
                    item["range61_90"] = 0.0
                    item["range91_plus"] = 0.0
                elif age_days <= 30:
                    item["current_range"] = 0.0
                    item["range1_30"] = outstanding
                    item["range31_60"] = 0.0
                    item["range61_90"] = 0.0
                    item["range91_plus"] = 0.0
                elif age_days <= 60:
                    item["current_range"] = 0.0
                    item["range1_30"] = 0.0
                    item["range31_60"] = outstanding
                    item["range61_90"] = 0.0
                    item["range91_plus"] = 0.0
                elif age_days <= 90:
                    item["current_range"] = 0.0
                    item["range1_30"] = 0.0
                    item["range31_60"] = 0.0
                    item["range61_90"] = outstanding
                    item["range91_plus"] = 0.0
                else:
                    item["current_range"] = 0.0
                    item["range1_30"] = 0.0
                    item["range31_60"] = 0.0
                    item["range61_90"] = 0.0
                    item["range91_plus"] = outstanding
            else:
                # Zero outstanding
                item["current_range"] = 0.0
                item["range1_30"] = 0.0
                item["range31_60"] = 0.0
                item["range61_90"] = 0.0
                item["range91_plus"] = 0.0
                item["age"] = 0

        # Format amounts
        self._format_amount_fields(item)

        # Remove temporary fields
        for field in ["due_date_dt", "posting_date_dt"]:
            if field in item:
                del item[field]

    def _get_receivable_detail_data(self, company_id: int, report_date: date,
                                    session: Session, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get receivable detail data (per Sales Invoice)."""
        # Use report_date_end for proper date comparison (end of day)
        report_date_end = filters.get("report_date_end", datetime.combine(report_date, datetime.max.time()))

        conditions = ["si.company_id = :company_id"]
        params = {"company_id": company_id, "report_date": report_date_end}

        # Get invoices up to report date (including those on the same day)
        conditions.append("si.posting_date <= :report_date")

        # Include all active invoice statuses (similar to old code)
        conditions.append("si.doc_status IN ('SUBMITTED', 'UNPAID', 'PARTIALLY_PAID', 'OVERDUE', 'PAID')")
        conditions.append("si.is_return = FALSE")

        # Filter by party if specified
        if filters.get("party"):
            conditions.append("si.customer_id = :party_id")
            params["party_id"] = filters["party"]

        # Filter by zero balance if needed - IMPORTANT: This is why you're missing invoices
        # When show_zero_balance=False, we show ALL invoices with outstanding > 0
        # When show_zero_balance=True, we show ALL invoices regardless of outstanding
        if not filters.get("show_zero_balance", False):
            conditions.append("si.outstanding_amount > 0")
        # If show_zero_balance=True, don't filter by outstanding_amount

        # Also show all invoices regardless of payment status (like old code)
        # Remove the condition that filters out PAID status

        query_str = f"""
            SELECT 
                si.id,
                si.code AS voucher_no,
                'Sales Invoice' AS voucher_type,
                si.posting_date,
                si.due_date,
                p.name AS party_name,
                p.id AS party_id,
                si.total_amount AS invoice_amount,
                si.paid_amount AS paid_on_invoice,
                si.outstanding_amount,
                si.doc_status
            FROM sales_invoices si
            JOIN parties p ON p.id = si.customer_id
            WHERE {' AND '.join(conditions)}
            ORDER BY p.name, si.posting_date, si.code
        """

        log.debug(f"📊 Receivable Detail Query: {query_str}")
        log.debug(f"📊 Query params: {params}")
        log.debug(f"📊 Company ID: {company_id}, Report date (end of day): {report_date_end}")

        try:
            query = text(query_str)
            result = session.execute(query, params).fetchall()

            data = []
            for row in result:
                item = {
                    "party_id": row.party_id,
                    "party_name": row.party_name,
                    "voucher_no": row.voucher_no,
                    "voucher_type": row.voucher_type,
                    "posting_date_dt": row.posting_date,
                    "due_date_dt": row.due_date or row.posting_date,
                    "invoice_amount": float(row.invoice_amount or 0),
                    "paid_amount": float(row.paid_on_invoice or 0),
                    "outstanding_amount": float(row.outstanding_amount or 0),
                    "doc_status": row.doc_status
                }
                data.append(item)

            log.debug(f"📊 Found {len(data)} invoices")
            return data

        except Exception as e:
            log.error(f"❌ Error executing receivable detail query: {e}", exc_info=True)
            raise

    def _get_payable_detail_data(self, company_id: int, report_date: date,
                                 session: Session, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get payable detail data (per Purchase Invoice)."""
        # Use report_date_end for proper date comparison
        report_date_end = filters.get("report_date_end", datetime.combine(report_date, datetime.max.time()))

        conditions = ["pi.company_id = :company_id"]
        params = {"company_id": company_id, "report_date": report_date_end}

        # Get invoices up to report date
        conditions.append("pi.posting_date <= :report_date")

        # Include all active invoice statuses
        conditions.append("pi.doc_status IN ('SUBMITTED', 'UNPAID', 'PARTIALLY_PAID', 'OVERDUE', 'PAID')")
        conditions.append("pi.is_return = FALSE")

        # Filter by party if specified
        if filters.get("party"):
            conditions.append("pi.supplier_id = :party_id")
            params["party_id"] = filters["party"]

        # Filter by zero balance if needed
        if not filters.get("show_zero_balance", False):
            conditions.append("pi.outstanding_amount > 0")

        query_str = f"""
            SELECT 
                pi.id,
                pi.code AS voucher_no,
                'Purchase Invoice' AS voucher_type,
                pi.posting_date,
                pi.due_date,
                p.name AS party_name,
                p.id AS party_id,
                pi.total_amount AS invoice_amount,
                pi.paid_amount AS paid_on_invoice,
                pi.outstanding_amount,
                pi.doc_status
                -- Removed: pi.bill_no, pi.bill_date (fields don't exist in your model)
            FROM purchase_invoices pi
            JOIN parties p ON p.id = pi.supplier_id
            WHERE {' AND '.join(conditions)}
            ORDER BY p.name, pi.posting_date, pi.code
        """

        try:
            query = text(query_str)
            result = session.execute(query, params).fetchall()

            data = []
            for row in result:
                item = {
                    "party_id": row.party_id,
                    "party_name": row.party_name,
                    "voucher_no": row.voucher_no,
                    "voucher_type": row.voucher_type,
                    "posting_date_dt": row.posting_date,
                    "due_date_dt": row.due_date or row.posting_date,
                    "invoice_amount": float(row.invoice_amount or 0),
                    "paid_amount": float(row.paid_on_invoice or 0),
                    "outstanding_amount": float(row.outstanding_amount or 0),
                    "doc_status": row.doc_status
                    # Removed: bill_no and bill_date fields
                }
                data.append(item)

            return data

        except Exception as e:
            log.error(f"❌ Error executing payable detail query: {e}", exc_info=True)
            raise

    # ================ SUMMARY DATA ================
    def _get_summary_data(self, filters: Dict[str, Any], session: Session) -> List[Dict[str, Any]]:
        """Get summary data grouped by party."""
        # First get detail data
        detail_data = self._get_detail_data(filters, session)

        if not detail_data:
            return []

        # Group by party ID (not name) to ensure unique grouping
        party_summary = {}

        for invoice in detail_data:
            party_id = invoice.get("party_id")
            party_name = invoice.get("party_name", "")

            if party_id not in party_summary:
                party_summary[party_id] = {
                    "party_id": party_id,
                    "party_name": party_name,
                    "party_code": self._get_party_code(session, party_id),
                    "total_invoiced": 0.0,
                    "outstanding_amount": 0.0,
                    "current_range": 0.0,
                    "range1_30": 0.0,
                    "range31_60": 0.0,
                    "range61_90": 0.0,
                    "range91_plus": 0.0,
                    "invoice_count": 0
                }

            # Aggregate values
            summary = party_summary[party_id]
            summary["total_invoiced"] += float(invoice.get("invoice_amount", 0))
            summary["outstanding_amount"] += float(invoice.get("outstanding_amount", 0))
            summary["invoice_count"] += 1

            # Aggregate ageing buckets (use the already calculated buckets from detail)
            summary["current_range"] += float(invoice.get("current_range", 0))
            summary["range1_30"] += float(invoice.get("range1_30", 0))
            summary["range31_60"] += float(invoice.get("range31_60", 0))
            summary["range61_90"] += float(invoice.get("range61_90", 0))
            summary["range91_plus"] += float(invoice.get("range91_plus", 0))

        # Convert to list and format
        result = []
        for party_id, summary_data in party_summary.items():
            # Format amounts
            self._format_amount_fields(summary_data)
            result.append(summary_data)

        # Sort by outstanding amount (descending)
        result.sort(key=lambda x: x.get("outstanding_amount", 0), reverse=True)

        return result

    def _get_party_code(self, session: Session, party_id: int) -> str:
        """Get party code by ID."""
        if not party_id:
            return ""

        try:
            query = text("""
                SELECT code FROM parties WHERE id = :party_id
            """)
            result = session.execute(query, {"party_id": party_id}).fetchone()
            return result.code if result else ""
        except Exception as e:
            log.error(f"Error getting party code: {e}")
            return ""

    # ================ HELPER METHODS ================
    def _format_amount_fields(self, item: Dict[str, Any]) -> None:
        """Format amount fields with proper precision."""
        amount_fields = [
            "total_invoiced", "outstanding_amount", "invoice_amount", "paid_amount",
            "current_range", "range1_30", "range31_60", "range61_90", "range91_plus"
        ]

        for field in amount_fields:
            if field in item:
                item[field] = format_amount(item[field], self.currency_precision)

    def _get_report_summary(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate report summary statistics."""
        if self.is_summary:
            return self._get_summary_report_summary(data, filters)
        else:
            return self._get_detail_report_summary(data, filters)

    def _get_detail_report_summary(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics for detail report."""
        total_outstanding = sum(row.get("outstanding_amount", 0) for row in data)
        total_invoiced = sum(row.get("invoice_amount", 0) for row in data)

        # Count unique customers
        party_count = len(set(row.get("party_name", "") for row in data if row.get("party_name")))

        # Calculate ageing totals
        ageing_totals = {
            "current_range": sum(row.get("current_range", 0) for row in data),
            "range1_30": sum(row.get("range1_30", 0) for row in data),
            "range31_60": sum(row.get("range31_60", 0) for row in data),
            "range61_90": sum(row.get("range61_90", 0) for row in data),
            "range91_plus": sum(row.get("range91_plus", 0) for row in data)
        }

        summary = {
            f"total_{'customers' if self.account_type == ReportAccountTypeEnum.RECEIVABLE else 'suppliers'}": party_count,
            "total_invoiced": format_amount(total_invoiced, self.currency_precision),
            "total_outstanding": format_amount(total_outstanding, self.currency_precision),
        }

        # Add ageing totals to summary
        summary.update({f"total_{k}": format_amount(v, self.currency_precision)
                        for k, v in ageing_totals.items()})

        return summary

    def _get_summary_report_summary(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Dict[str, Any]:
        """Generate summary statistics for summary report."""
        total_outstanding = sum(row.get("outstanding_amount", 0) for row in data)
        total_invoiced = sum(row.get("total_invoiced", 0) for row in data)

        # Count unique parties
        party_count = len(data)

        # Calculate ageing totals
        ageing_totals = {
            "current_range": sum(row.get("current_range", 0) for row in data),
            "range1_30": sum(row.get("range1_30", 0) for row in data),
            "range31_60": sum(row.get("range31_60", 0) for row in data),
            "range61_90": sum(row.get("range61_90", 0) for row in data),
            "range91_plus": sum(row.get("range91_plus", 0) for row in data)
        }

        summary = {
            f"total_{'customers' if self.account_type == ReportAccountTypeEnum.RECEIVABLE else 'suppliers'}": party_count,
            "total_invoiced": format_amount(total_invoiced, self.currency_precision),
            "total_outstanding": format_amount(total_outstanding, self.currency_precision),
        }

        # Add ageing totals to summary
        summary.update({f"total_{k}": format_amount(v, self.currency_precision)
                        for k, v in ageing_totals.items()})

        return summary

    def _get_chart_data(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate chart data for ageing analysis."""
        if not data:
            return None

        # Calculate totals for each ageing bucket
        if self.is_summary:
            # Summary report: data already has aggregated buckets
            range_totals = [
                sum(row.get("current_range", 0) for row in data),
                sum(row.get("range1_30", 0) for row in data),
                sum(row.get("range31_60", 0) for row in data),
                sum(row.get("range61_90", 0) for row in data),
                sum(row.get("range91_plus", 0) for row in data)
            ]
        else:
            # Detail report: calculate from individual invoices
            range_totals = [0.0, 0.0, 0.0, 0.0, 0.0]
            for row in data:
                range_totals[0] += row.get("current_range", 0)
                range_totals[1] += row.get("range1_30", 0)
                range_totals[2] += row.get("range31_60", 0)
                range_totals[3] += row.get("range61_90", 0)
                range_totals[4] += row.get("range91_plus", 0)

        # Check if all ranges are zero
        if all(total == 0 for total in range_totals):
            return None

        labels = ["Current", "1-30 Days", "31-60 Days", "61-90 Days", "91+ Days"]
        values = [format_amount(val, self.currency_precision) for val in range_totals]

        return {
            "type": "bar",
            "title": f"{self.account_type.value} Ageing Analysis",
            "data": {
                "labels": labels,
                "datasets": [{
                    "name": "Outstanding Amount",
                    "values": values
                }]
            },
            "height": 300
        }

