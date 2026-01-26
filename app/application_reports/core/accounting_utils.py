# app/application_reports/core/accounting_utils.py
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import date, datetime
from decimal import Decimal
import logging
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_

# Import your enums from your models
from app.application_accounting.chart_of_accounts.models import (
    AccountTypeEnum,
    PartyTypeEnum,
    JournalEntryTypeEnum,
    DebitOrCreditEnum
)
from app.application_accounting.chart_of_accounts.finance_model import PaymentTypeEnum



class ReportAccountTypeEnum(str, Enum):
    """Account types for reporting purposes"""
    RECEIVABLE = "Receivable"
    PAYABLE = "Payable"
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    INCOME = "Income"
    EXPENSE = "Expense"
    BANK = "Bank"
    CASH = "Cash"
log = logging.getLogger(__name__)


def get_party_types_from_account_type(account_type: ReportAccountTypeEnum) -> List[str]:
    """
    Maps account type to party types (Frappe pattern).

    Args:
        account_type: "Receivable" or "Payable"

    Returns:
        List of party type strings
    """
    mapping = {
        ReportAccountTypeEnum.RECEIVABLE: [
            PartyTypeEnum.CUSTOMER,
            # PartyTypeEnum.STUDENT,
            PartyTypeEnum.SHAREHOLDER
        ],
        ReportAccountTypeEnum.PAYABLE: [
            PartyTypeEnum.SUPPLIER,
            PartyTypeEnum.EMPLOYEE,
            PartyTypeEnum.SHAREHOLDER
        ],
    }
    return mapping.get(account_type, [])


def get_advance_payment_doctypes() -> List[str]:
    """
    Returns doctypes that can be considered advance payments.
    """
    return ["PaymentEntry", "JournalEntry"]


def get_accounting_dimensions(session: Session, company_id: int) -> List[str]:
    """
    Returns active accounting dimensions for filtering.
    In your system, these are fields in GeneralLedgerEntry.
    """
    # Check which dimensions are used in your GLE table
    dimensions = []

    # Cost Center is always a dimension if you have cost_centers table
    try:
        result = session.execute(text("""
            SELECT COUNT(*) FROM cost_centers WHERE company_id = :company_id
        """), {"company_id": company_id}).scalar()
        if result and result > 0:
            dimensions.append("cost_center")
    except Exception:
        pass

    # Add other dimensions based on your schema
    # For example, if you have projects, branches, departments, etc.

    return dimensions


def get_dimension_with_children(session: Session, dimension_name: str, value_id: int) -> List[int]:
    """
    Get dimension value with its hierarchical children.
    Since your models don't have parent-child relationships,
    just return the single ID.
    """
    return [value_id]


def get_cost_centers_with_children(session: Session, cost_center_id: int) -> List[int]:
    """
    Get cost center IDs including children.
    Since your CostCenter model doesn't have parent_id, return single ID.
    """
    return [cost_center_id]


def get_currency_precision() -> int:
    """
    Get decimal precision for currency.
    Since you don't have currency table, use default.
    """
    return 2  # Default precision


def parse_date_flex(date_value) -> Optional[date]:
    """
    Flexible date parser.
    """
    if date_value is None:
        return None

    if isinstance(date_value, date):
        return date_value

    if isinstance(date_value, datetime):
        return date_value.date()

    if isinstance(date_value, str):
        date_str = date_value.strip()
        if not date_str:
            return None

        # Try ISO format first
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        except ValueError:
            pass

        # Try common formats
        date_formats = [
            "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y",
            "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
            "%d.%m.%Y", "%m.%d.%Y", "%Y.%m.%d"
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Try without timezone
        try:
            return datetime.strptime(date_str.split('T')[0], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            pass

    return None


def calculate_ageing_buckets(due_date: Optional[date], report_date: date,
                             amount: float, ranges: List[int]) -> Dict[str, float]:
    """
    Calculate ageing buckets for an amount.
    """
    if not due_date or amount == 0:
        return {f"range{i + 1}": 0.0 for i in range(len(ranges) + 1)}

    age_days = (report_date - due_date).days

    buckets = {f"range{i + 1}": 0.0 for i in range(len(ranges) + 1)}

    if age_days <= 0:
        buckets["range1"] = amount
    elif age_days <= ranges[0]:
        buckets["range1"] = amount
    elif age_days <= ranges[1]:
        buckets["range2"] = amount
    elif age_days <= ranges[2]:
        buckets["range3"] = amount
    elif age_days <= ranges[3]:
        buckets["range4"] = amount
    else:
        buckets["range5"] = amount

    return buckets


def get_invoice_outstanding_details(session: Session, company_id: int,
                                    report_date: date, invoice_ids: List[int],
                                    is_receivable: bool = True) -> Dict[int, Dict[str, Any]]:
    """
    Get payment allocations and outstanding for invoices.
    """
    if not invoice_ids:
        return {}

    # Determine doctype based on receivable/payable
    if is_receivable:
        doctype_code = "SALES_INVOICE"
    else:
        doctype_code = "PURCHASE_INVOICE"

    # Get document type ID
    dt_result = session.execute(
        text("SELECT id FROM document_types WHERE code = :code"),
        {"code": doctype_code}
    ).scalar()

    if not dt_result:
        return {}

    doctype_id = dt_result

    # Query payment allocations
    payment_query = text("""
        SELECT 
            pi.source_doc_id AS invoice_id,
            SUM(pi.allocated_amount) AS total_allocated,
            COUNT(DISTINCT pe.id) AS payment_count
        FROM payment_items pi
        JOIN payment_entries pe ON pe.id = pi.payment_id
        WHERE pe.company_id = :company_id
          AND pe.doc_status = 'SUBMITTED'
          AND pe.posting_date <= :report_date
          AND pi.source_doctype_id = :doctype_id
          AND pi.source_doc_id = ANY(:invoice_ids)
        GROUP BY pi.source_doc_id
    """)

    result = session.execute(
        payment_query,
        {
            "company_id": company_id,
            "report_date": report_date,
            "doctype_id": doctype_id,
            "invoice_ids": invoice_ids
        }
    ).fetchall()

    payment_details = {}
    for row in result:
        payment_details[row.invoice_id] = {
            "allocated_amount": float(row.total_allocated or 0),
            "payment_count": row.payment_count
        }

    # Add entries for invoices with no payments
    for inv_id in invoice_ids:
        if inv_id not in payment_details:
            payment_details[inv_id] = {
                "allocated_amount": 0.0,
                "payment_count": 0
            }

    return payment_details


def get_advance_payments(session: Session, company_id: int, report_date: date,
                         party_type: PartyTypeEnum, party_ids: List[int] = None) -> Dict[int, float]:
    """
    Get unallocated advance payments for parties.
    """
    # Determine payment type based on party type
    if party_type == PartyTypeEnum.CUSTOMER:
        payment_type = PaymentTypeEnum.RECEIVE.value
    else:
        payment_type = PaymentTypeEnum.PAY.value

    query_params = {
        "company_id": company_id,
        "report_date": report_date,
        "payment_type": payment_type,
        "party_type": party_type.value
    }

    query = text("""
        SELECT 
            pe.party_id,
            SUM(pe.unallocated_amount) AS advance_amount
        FROM payment_entries pe
        WHERE pe.company_id = :company_id
          AND pe.doc_status = 'SUBMITTED'
          AND pe.payment_type = :payment_type
          AND pe.party_type = :party_type
          AND pe.posting_date <= :report_date
          AND pe.unallocated_amount > 0
    """)

    if party_ids:
        query = text("""
            SELECT 
                pe.party_id,
                SUM(pe.unallocated_amount) AS advance_amount
            FROM payment_entries pe
            WHERE pe.company_id = :company_id
              AND pe.doc_status = 'SUBMITTED'
              AND pe.payment_type = :payment_type
              AND pe.party_type = :party_type
              AND pe.posting_date <= :report_date
              AND pe.unallocated_amount > 0
              AND pe.party_id = ANY(:party_ids)
            GROUP BY pe.party_id
        """)
        query_params["party_ids"] = party_ids

    result = session.execute(query, query_params).fetchall()

    return {row.party_id: float(row.advance_amount or 0) for row in result}


def get_credit_notes_for_invoices(session: Session, company_id: int,
                                  report_date: date, invoice_ids: List[int],
                                  is_receivable: bool = True) -> Dict[int, float]:
    """
    Get credit/debit notes for invoices.
    """
    if not invoice_ids:
        return {}

    if is_receivable:
        # Sales returns (credit notes)
        query = text("""
            SELECT 
                si.return_against_id AS invoice_id,
                SUM(ABS(si.total_amount)) AS credit_amount
            FROM sales_invoices si
            WHERE si.company_id = :company_id
              AND si.is_return = TRUE
              AND si.doc_status = 'SUBMITTED'
              AND si.posting_date <= :report_date
              AND si.return_against_id = ANY(:invoice_ids)
            GROUP BY si.return_against_id
        """)
    else:
        # Purchase returns (debit notes)
        query = text("""
            SELECT 
                pi.return_against_id AS invoice_id,
                SUM(ABS(pi.total_amount)) AS debit_amount
            FROM purchase_invoices pi
            WHERE pi.company_id = :company_id
              AND pi.is_return = TRUE
              AND pi.doc_status = 'SUBMITTED'
              AND pi.posting_date <= :report_date
              AND pi.return_against_id = ANY(:invoice_ids)
            GROUP BY pi.return_against_id
        """)

    result = session.execute(
        query,
        {
            "company_id": company_id,
            "report_date": report_date,
            "invoice_ids": invoice_ids
        }
    ).fetchall()

    credit_notes = {}
    for row in result:
        if is_receivable:
            credit_notes[row.invoice_id] = float(row.credit_amount or 0)
        else:
            credit_notes[row.invoice_id] = float(row.debit_amount or 0)

    return credit_notes


def format_amount(value: float, precision: int = 2) -> float:
    """
    Format amount with specified precision.
    """
    if value is None:
        return 0.0

    try:
        factor = 10 ** precision
        return round(value * factor) / factor
    except (TypeError, ValueError):
        return 0.0


def build_query_conditions(filters: Dict[str, Any], table_alias: str = "") -> Tuple[str, Dict[str, Any]]:
    """
    Build SQL WHERE conditions from filters.
    """
    conditions = []
    params = {}

    for key, value in filters.items():
        if value is None:
            continue

        column_name = key
        if table_alias:
            column_name = f"{table_alias}.{key}"

        if isinstance(value, list):
            if value:
                placeholders = ', '.join([f':{key}_{i}' for i in range(len(value))])
                conditions.append(f"{column_name} IN ({placeholders})")
                for i, v in enumerate(value):
                    params[f"{key}_{i}"] = v
        elif isinstance(value, (str, int, float)):
            conditions.append(f"{column_name} = :{key}")
            params[key] = value
        elif isinstance(value, bool):
            conditions.append(f"{column_name} = :{key}")
            params[key] = value
        elif isinstance(value, date):
            conditions.append(f"{column_name}::date = :{key}")
            params[key] = value

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    return where_clause, params