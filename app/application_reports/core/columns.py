# app/application_reports/core/columns.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
from .engine import ColumnDefinition, FilterDefinition

def currency_column(fieldname: str, label: str, width: int = 120, precision: int = 2) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Currency",
        "width": width,
        "precision": precision,
        "align": "right"
    }

def date_column(fieldname: str, label: str, width: int = 100) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Date",
        "width": width
    }

def link_column(fieldname: str, label: str, options: str, width: int = 120) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Link",
        "options": options,
        "width": width
    }

def data_column(fieldname: str, label: str, width: int = 150) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Data",
        "width": width
    }

def float_column(fieldname: str, label: str, width: int = 100, precision: int = 2) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Float",
        "width": width,
        "precision": precision,
        "align": "right"
    }

def int_column(fieldname: str, label: str, width: int = 80) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Int",
        "width": width,
        "align": "right"
    }

def check_column(fieldname: str, label: str, width: int = 80) -> ColumnDefinition:
    return {
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Check",
        "width": width,
        "align": "center"
    }
def source_document_filter() -> FilterDefinition:
    return {
        "fieldname": "source_document",
        "label": "Source Document",
        "fieldtype": "Data"
    }
# Predefined column sets
GL_COLUMNS = [
    date_column("posting_date", "Posting Date"),
    link_column("account", "Account", "Account"),
    data_column("account_name", "Account Name"),

    currency_column("debit", "Debit (Dr)"),
    currency_column("credit", "Credit (Cr)"),
    currency_column("running_balance", "Running Balance"),

    data_column("voucher_type", "Voucher Type", 140),
    data_column("voucher_no", "Voucher No", 160),

    data_column("against_account", "Against Account", 200),

    data_column("party_type", "Party Type", 110),
    int_column("party_id", "Party ID", 90),
    data_column("party_name", "Party Name", 160),

    data_column("cost_center", "Cost Center", 150),
    data_column("branch_name", "Branch", 150),

    data_column("remarks", "Remarks", 220),
]
STOCK_LEDGER_COLUMNS = [
    date_column("posting_date", "Date"),
    data_column("posting_time", "Time"),

    data_column("item_name", "Item"),
    data_column("warehouse", "Warehouse"),

    data_column("stock_uom", "Stock UOM"),
    data_column("transaction_uom", "Transaction UOM"),
    float_column("transaction_qty", "Transaction Qty", precision=6),

    data_column("voucher_type", "Voucher Type"),
    data_column("voucher_no", "Voucher No"),

    float_column("in_qty", "In Qty", precision=6),
    float_column("out_qty", "Out Qty", precision=6),
    float_column("balance_qty", "Balance Qty", precision=6),

    currency_column("incoming_rate", "Incoming Rate", precision=6),
    currency_column("outgoing_rate", "Outgoing Rate", precision=6),
    currency_column("valuation_rate", "Valuation Rate", precision=6),

    currency_column("stock_value_difference", "Stock Value Diff", precision=6),
    currency_column("running_stock_value", "Value After Txn", precision=6),

    data_column("branch", "Branch"),
    data_column("remarks", "Remarks", 200),
]



# app/application_reports/core/columns.py
ACCOUNTS_PAYABLE_COLUMNS = [
    link_column("supplier", "Supplier", "Supplier"),
    data_column("supplier_name", "Supplier Name"),
    data_column("supplier_group", "Supplier Group"),  # stays blank until you wire a real group table
    currency_column("total_invoiced", "Total Invoiced"),
    currency_column("total_paid", "Total Paid"),
    currency_column("total_debit_note", "Debit Notes"),
    currency_column("advance_amount", "Advance"),
    currency_column("outstanding_amount", "Outstanding"),
    currency_column("range1", "0-30 Days"),
    currency_column("range2", "31-60 Days"),
    currency_column("range3", "61-90 Days"),
    currency_column("range4", "90+ Days"),
]



# --- Stock Balance (Single Item) ---------------------------------------------
STOCK_BALANCE_SINGLE_ITEM_COLUMNS_FULL = [
    data_column("item_name", "Item", 220),
    data_column("item_group", "Item Group", 160),
    data_column("warehouse", "Warehouse", 200),
    data_column("stock_uom", "Stock UOM", 100),

    float_column("opening_qty", "Opening Qty", precision=6),
    currency_column("opening_value", "Opening Value", precision=6),

    float_column("in_qty", "In Qty", precision=6),
    currency_column("in_value", "In Value", precision=6),

    float_column("out_qty", "Out Qty", precision=6),
    currency_column("out_value", "Out Value", precision=6),

    float_column("balance_qty", "Balance Qty", precision=6),
    currency_column("valuation_rate", "Valuation Rate", precision=6),
    currency_column("balance_value", "Balance Value", precision=6),
]

# leaner (same data, less columns)
STOCK_BALANCE_SINGLE_ITEM_COLUMNS_COMPACT = [
    data_column("item_name", "Item", 220),
    data_column("warehouse", "Warehouse", 200),
    float_column("balance_qty", "Balance Qty", precision=6),
    currency_column("valuation_rate", "Valuation Rate", precision=6),
    currency_column("balance_value", "Balance Value", precision=6),
]

# --- Item Stock Ledger (history for one item+warehouse) ----------------------
ITEM_STOCK_LEDGER_COLUMNS_FULL = [
    date_column("posting_date", "Date"),
    data_column("posting_time", "Time"),

    data_column("item_name", "Item", 220),
    data_column("item_group", "Item Group", 160),
    data_column("warehouse", "Warehouse", 200),

    data_column("stock_uom", "Stock UOM", 100),
    data_column("transaction_uom_name", "Transaction UOM", 130),
    float_column("transaction_quantity", "Transaction Qty", precision=6),

    float_column("in_qty", "In Qty", precision=6),
    currency_column("in_value", "In Value", precision=6),

    float_column("out_qty", "Out Qty", precision=6),
    currency_column("out_value", "Out Value", precision=6),

    float_column("balance_qty", "Balance Qty", precision=6),
    currency_column("incoming_rate", "Incoming Rate", precision=6),
    currency_column("valuation_rate", "Valuation Rate", precision=6),
    currency_column("balance_value", "Balance Value", precision=6),

    data_column("voucher_type", "Voucher Type", 140),
    data_column("voucher_no", "Voucher No", 160),
]

# compact (fast list views)
ITEM_STOCK_LEDGER_COLUMNS_COMPACT = [
    date_column("posting_date", "Date"),
    data_column("posting_time", "Time"),
    data_column("warehouse", "Warehouse", 180),
    data_column("voucher_type", "Voucher Type", 120),
    data_column("voucher_no", "Voucher No", 140),

    data_column("stock_uom", "UOM", 80),
    float_column("in_qty", "In Qty", precision=6),
    float_column("out_qty", "Out Qty", precision=6),
    float_column("balance_qty", "Balance Qty", precision=6),

    currency_column("valuation_rate", "Valuation Rate", precision=6),
    currency_column("balance_value", "Balance Value", precision=6),
]















ACCOUNTS_RECEIVABLE_COLUMNS = [
    link_column("customer", "Customer", "Customer"),
    data_column("customer_name", "Customer Name"),
    currency_column("total_invoiced", "Total Invoiced"),
    currency_column("total_paid", "Total Paid"),
    currency_column("total_credit_note", "Credit Notes"),
    currency_column("outstanding_amount", "Outstanding"),
    currency_column("range1", "0-30 Days"),
    currency_column("range2", "31-60 Days"),
    currency_column("range3", "61-90 Days"),
    currency_column("range4", "90+ Days"),
]

PROFIT_LOSS_COLUMNS = [
    data_column("account", "Account", 250),
    currency_column("amount", "Amount"),
    int_column("indent", "Indent", 60),
    data_column("account_code", "Account Code", 100),
]

TRIAL_BALANCE_COLUMNS = [
    link_column("account", "Account", "Account"),
    data_column("account_name", "Account Name"),
    currency_column("opening_debit", "Opening (Dr)"),
    currency_column("opening_credit", "Opening (Cr)"),
    currency_column("debit", "Debit"),
    currency_column("credit", "Credit"),
    currency_column("closing_debit", "Closing (Dr)"),
    currency_column("closing_credit", "Closing (Cr)"),
]

# Standard filter definitions
def date_range_filters() -> List[FilterDefinition]:
    return [
        {
            "fieldname": "from_date",
            "label": "From Date",
            "fieldtype": "Date",
            "default": "2025-10-01",
            "required": True
        },
        {
            "fieldname": "to_date",
            "label": "To Date",
            "fieldtype": "Date",
            "default": "2025-10-31",
            "required": True
        }
    ]


def company_filter() -> FilterDefinition:
    return {
        "fieldname": "company",
        "label": "Company",
        "fieldtype": "Link",
        "options": "Company",
        "required": True
    }

def account_filter() -> FilterDefinition:
    return {
        "fieldname": "account",
        "label": "Account",
        "fieldtype": "Link",
        "options": "Account"
    }

def cost_center_filter() -> FilterDefinition:
    return {
        "fieldname": "cost_center",
        "label": "Cost Center",
        "fieldtype": "Link",
        "options": "Cost Center"
    }

def party_filter() -> FilterDefinition:
    return {
        "fieldname": "party",
        "label": "Party",
        "fieldtype": "Link",
        "options": "Party"
    }

def item_filter() -> FilterDefinition:
    return {
        "fieldname": "item_code",
        "label": "Item",
        "fieldtype": "Link",
        "options": "Item"
    }

def warehouse_filter() -> FilterDefinition:
    return {
        "fieldname": "warehouse",
        "label": "Warehouse",
        "fieldtype": "Link",
        "options": "Warehouse"
    }

def voucher_no_filter() -> FilterDefinition:
    return {
        "fieldname": "voucher_no",
        "label": "Voucher No",
        "fieldtype": "Data"
    }