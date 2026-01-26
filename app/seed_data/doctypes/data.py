# seed_data/doctypes/data.py
from __future__ import annotations
from typing import List, Dict

# Central registry for document types used across modules.
# Fields:
# - code: stable UPPER_SNAKE identifier stored in ledgers
# - label: human-facing title
# - domain: "INVENTORY" | "FINANCE" | "ASSETS" | "PAYROLL" | "OTHER"
# - affects_stock: whether stock ledger should accept this doc
# - affects_gl: whether general ledger should accept this doc

DOCTYPE_TYPES: List[Dict] = [
    # ---------- Inventory core ----------
    dict(code="STOCK_ENTRY",          label="Stock Entry",          domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="STOCK_RECONCILIATION", label="Stock Reconciliation", domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="PURCHASE_RECEIPT",     label="Purchase Receipt",     domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="DELIVERY_NOTE",        label="Delivery Note",        domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="SALES_RETURN",         label="Sales Return",         domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="PURCHASE_RETURN",      label="Purchase Return",      domain="INVENTORY", affects_stock=True,  affects_gl=True),
    dict(code="LANDED_COST_VOUCHER",  label="Landed Cost Voucher",  domain="INVENTORY", affects_stock=False, affects_gl=True),

    # If you keep this separate from STOCK_ENTRY, it usually does NOT affect GL:
    # (warehouse-to-warehouse transfer inside the same company)
    dict(code="STOCK_TRANSFER",       label="Stock Transfer",       domain="INVENTORY", affects_stock=True,  affects_gl=False),

    # Manufacturing: often represented by a Stock Entry (Manufacture).
    # Keep if you maintain a separate manufacturing doc driving stock & GL.
    dict(code="MANUFACTURING_ENTRY",  label="Manufacturing Entry",  domain="INVENTORY", affects_stock=True,  affects_gl=True),

    # Execution/quality helpers (no ledgers directly)
    dict(code="QUALITY_INSPECTION",   label="Quality Inspection",   domain="INVENTORY", affects_stock=False, affects_gl=False),
    dict(code="JOB_CARD",             label="Job Card",             domain="INVENTORY", affects_stock=False, affects_gl=False),

    # ---------- Finance ----------
    dict(code="SALES_INVOICE",        label="Sales Invoice",        domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="SALES_DELIVERY_NOTE", label="Sales Delivery Note", domain="INVENTORY", affects_stock=True, affects_gl=True),

    dict(code="PURCHASE_INVOICE",     label="Purchase Invoice",     domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="PAYMENT_ENTRY",        label="Payment Entry",        domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="RECEIPT_ENTRY",        label="Receipt Entry",        domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="JOURNAL_ENTRY",        label="Journal Entry",        domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="EXPENSE_CLAIM",        label="Expense Claim",        domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="BANK_RECONCILIATION",  label="Bank Reconciliation",  domain="FINANCE",   affects_stock=False, affects_gl=False),
    dict(code="LOAN_REPAYMENT",       label="Loan Repayment",       domain="FINANCE",   affects_stock=False, affects_gl=True),
    dict(code="FINANCIAL_PERIOD_CLOSING", label="Financial Period Closing", domain="FINANCE", affects_stock=False, affects_gl=True),
    dict(code="JOURNAL_ENTRY_REVERSAL", label="Journal Entry Reversal", domain="FINANCE", affects_stock=False, affects_gl=True),

    # Planning docs (no ledgers)
    dict(code="MATERIAL_REQUEST",     label="Material Request",     domain="FINANCE",   affects_stock=False, affects_gl=False),
    dict(code="PURCHASE_ORDER",       label="Purchase Order",       domain="FINANCE",   affects_stock=False, affects_gl=False),
    dict(code="SALES_ORDER",          label="Sales Order",          domain="FINANCE",   affects_stock=False, affects_gl=False),

    # ---------- Assets ----------
    dict(code="ASSET_DEPRECIATION",   label="Asset Depreciation",   domain="ASSETS",    affects_stock=False, affects_gl=True),
    dict(code="DEPRECIATION_ENTRY",   label="Depreciation Entry",   domain="ASSETS",    affects_stock=False, affects_gl=True),

    # ---------- Education ----------
    dict(code="STUDENT",              label="Student",              domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="INSTRUCTOR",           label="Instructor",           domain="EDUCATION", affects_stock=False, affects_gl=False),

    dict(code="FEE_STRUCTURE", label="Fee Structure", domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="FEE_SCHEDULE", label="Fee Schedule", domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="FEES", label="Fees", domain="EDUCATION", affects_stock=False, affects_gl=False),

    dict(code="STUDENT_ATTENDANCE", label="Student Attendance", domain="EDUCATION", affects_stock=False,
         affects_gl=False),

    dict(code="ASSESSMENT_EVENT", label="Assessment Event", domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="ASSESSMENT_MARK", label="Assessment Mark", domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="GRADE_RECALC_JOB", label="Grade Recalc Job", domain="EDUCATION", affects_stock=False, affects_gl=False),
    dict(code="STUDENT_ANNUAL_RESULT", label="Student Annual Result", domain="EDUCATION", affects_stock=False,
         affects_gl=False),

    # ---------- Other ----------
    dict(code="PAYROLL_JOURNAL",      label="Payroll Journal",      domain="OTHER",     affects_stock=False, affects_gl=True),
    dict(code="OPENING_ENTRY",        label="Opening Entry",        domain="OTHER",     affects_stock=False, affects_gl=True),
    dict(code="CLOSING_ENTRY",        label="Closing Entry",        domain="OTHER",     affects_stock=False, affects_gl=True),
    dict(code="ADJUSTMENT_ENTRY",     label="Adjustment Entry",     domain="OTHER",     affects_stock=False, affects_gl=True),
]
