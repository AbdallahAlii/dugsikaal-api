
# seed_data/gl_templates/data.py
from __future__ import annotations
from typing import List, Dict, Any

"""
Declarative GL templates, split into TEMPLATE_DEFS (headers) and TEMPLATE_ITEMS (lines).

This file defines the accounting logic for all business transactions.
- A "Return" is for the physical return of goods (e.g., customer returns a damaged item).
- A "Cancellation" is a full reversal of a document, typically to correct a data entry error.
"""

# For documentation / reference in your posting service (non-enforcing)
AMOUNT_SOURCES = {
    # Common
    "DOCUMENT_TOTAL": "Grand total (what customer/supplier owes or gets)",
    "DOCUMENT_SUBTOTAL": "Net before tax/rounding/charges",
    "TAX_AMOUNT": "Total tax for the document",
    "DISCOUNT_AMOUNT": "Total discount allowed on the document",
    "ROUND_OFF_POSITIVE": "Positive round-off amount (expense)",
    "ROUND_OFF_NEGATIVE": "Negative round-off amount (income)",
    "AMOUNT_PAID": "Amount paid now (on purchase documents)",
    "AMOUNT_RECEIVED": "Amount received now (on sales/receipts)",
    "AMOUNT_REFUNDED": "Amount refunded",
    "WRITE_OFF_AMOUNT": "Amount written off",
    # Sales COGS
    "COST_OF_GOODS_SOLD": "COGS for shipped goods",
    "COGS_REVERSAL": "COGS to reverse on returns (only restocked items)",
    # Purchase / GRNI
    "INVENTORY_PURCHASE_COST": "Receipt cost (valuation) for purchases",
    "INVOICE_MATCHED_GRNI_VALUE": "Matched value vs receipts (clear GRNI)",
    "PURCHASE_VARIANCE_DEBIT": "Purchase price variance (debit)",
    "PURCHASE_VARIANCE_CREDIT": "Purchase price variance (credit)",
    "INVOICE_STOCK_VALUE": "Stock value on direct purchase invoice",
    "INVOICE_SERVICE_VALUE": "Service value on direct purchase invoice",
    "RETURN_STOCK_VALUE": "Stock value on purchase return",
    "RETURN_DOCUMENT_TOTAL": "Gross total on purchase return (incl. tax)",
    "RETURN_TAX_AMOUNT": "Tax to reverse on purchase return",
    # Depreciation
    "DEPRECIATION_AMOUNT": "Depreciation amount for the period",

    # Stock Reconciliation - Frappe Style

    "STOCK_VALUE_DIFFERENCE": "Value difference for stock reconciliation (per line, can be + or -)",
    # Stock Reconciliation

    "STOCK_RECON_DIFFERENCE": "Signed total value difference for stock reconciliation "
                              "(>0 = gain, <0 = loss)",
    # Stock Entry (Material Receipt / Issue / Adjustment)
    "STOCK_ENTRY_DIFFERENCE": "Signed total stock value difference for Stock Entry "
                              "(>0 = gain, <0 = loss)",
    # --- NEW for PCV ---
    "PROFIT_AMOUNT": "Positive net P&L (profit)",
    "LOSS_AMOUNT": "Positive net loss",


}


# Use constants (no accidental 'D'/'C' strings)
DEBIT = "DEBIT"
CREDIT = "CREDIT"

# ==============================================================================
# 1) TEMPLATE HEADERS (TEMPLATE_DEFS)
# ==============================================================================
TEMPLATE_DEFS: List[Dict[str, Any]] = [
    # --------------------------------------------------------------------------
    # --- Sales & Accounts Receivable ---
    # --------------------------------------------------------------------------
    # --- NEW: Period Closing Voucher ---
    dict(
        doctype_code="PERIOD_CLOSING_VOUCHER",
        code="PERIOD_CLOSING",
        label="Period Closing Voucher",
        description="Transfers net P&L to Retained Earnings using P&L Summary account.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="SALES_INV_AR",
        label="Sales Invoice (Financial Only)",
        description="Books receivables and income. Use when stock is delivered via a Delivery Note. DR A/R; CR Income; CR Tax.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="SALES_INV_WITH_STOCK",
        label="Sales Invoice (Direct Stock & Finance)",
        description="A single transaction for both financial booking and stock delivery. DR A/R; CR Income; DR COGS; CR Inventory.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="DELIVERY_NOTE",
        code="DELIVERY_NOTE_COGS",
        label="COGS on Delivery",
        description="Records the cost of goods sold and reduces inventory at the time of shipment. DR COGS; CR Inventory.",
        is_active=True,
        is_primary=True,
    ),

    # Sales Returns & Cancellations
    dict(
        doctype_code="SALES_INVOICE",
        code="SALES_RETURN_CREDIT",
        label="Sales Return (Credit Note)",
        description="Reverse income and AR. Optionally reverse COGS if restocked.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="CANCEL_SALES_INVOICE",
        label="Cancel Sales Invoice",
        description="Exact reversal of a submitted Sales Invoice.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="DELIVERY_NOTE",
        code="CANCEL_DELIVERY_NOTE",
        label="Cancel Delivery Note",
        description="Exact reversal of a submitted Delivery Note.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="AR_WRITE_OFF",
        label="Write-off Customer Balance",
        description="DR Bad Debt Expense; CR A/R for uncollectible balances.",
        is_active=True,
        is_primary=False,
    ),

    # --------------------------------------------------------------------------
    # --- Purchasing & Accounts Payable --- Buying
    # --------------------------------------------------------------------------
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="PURCHASE_RECEIPT_GRNI",
        label="Purchase Receipt (Inventory + GRNI)",
        description="DR Inventory; CR GRNI on receipt. No A/P yet.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_AGAINST_RECEIPT",
        label="Purchase Invoice (Clear GRNI)",
        description="DR GRNI; DR Tax; CR A/P (+ variance lines).",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_DIRECT",
        label="Purchase Invoice (Direct)",
        description="No prior receipt. DR Inventory (stock) and/or DR Expense (services); DR Tax; CR A/P.",
        is_active=True,
        is_primary=False,
    ),

    # Purchase Returns & Cancellations
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_RETURN_INVOICED",
        label="Purchase Return (After Invoice / Debit Note)",
        description="DR A/P; CR Inventory; CR Tax (debit note).",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="PURCHASE_RETURN_GRNI",
        label="Purchase Return (Before Invoice / GRNI)",
        description="Reverse GRNI: DR GRNI; CR Inventory.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="CANCEL_PURCHASE_INVOICE",
        label="Cancel Purchase Invoice (Against Receipt)",
        description="Exact reversal of PI posted against GRNI.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="CANCEL_PURCHASE_INVOICE_DIRECT",
        label="Cancel Purchase Invoice (Direct)",
        description="Exact reversal of direct PI (no receipt).",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="CANCEL_PURCHASE_RECEIPT",
        label="Cancel Purchase Receipt",
        description="Exact reversal of a submitted Purchase Receipt.",
        is_active=True,
        is_primary=False,
    ),
    # --------------------------------------------------------------------------
    # --- Inventory & Stock ---
    # --------------------------------------------------------------------------
    dict(
        doctype_code="STOCK_RECONCILIATION",
        code="STOCK_RECON_GENERAL",
        label="Stock Reconciliation",
        description="Adjusts inventory to match physical count. DR/CR Stock; CR/DR Difference Account.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="STOCK_ENTRY",
        code="STOCK_ENTRY_GENERAL",
        label="Stock Entry (Manual Stock Adjustments)",
        description="Adjusts inventory via Stock Entry (Material Receipt / Issue / Adjustment). "
                    "DR/CR Stock; CR/DR Difference Account based on signed difference.",
        is_active=True,
        is_primary=True,
    ),
    # --------------------------------------------------------------------------
    # --- Payments & Bank/Cash ---
    # --------------------------------------------------------------------------
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="PAYMENT_RECEIVE",
        label="Receipt (Receive)",
        description="DR Bank/Cash; CR Party Ledger (A/R for Customer, A/P for Supplier refund if you prefer).",
        is_active=True,
        is_primary=True,  # ← keep this True
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="PAYMENT_PAY",
        label="Payment (Pay)",
        description="DR Party Ledger (A/P for Supplier, A/R for Customer refund if you prefer); CR Bank/Cash.",
        is_active=True,
        is_primary=False,  # ← change to False
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="PAYMENT_INTERNAL_TRANSFER",
        label="Internal Transfer",
        description="Cash/Bank to Cash/Bank. DR Target; CR Source.",
        is_active=True,
        is_primary=False,  # ← change to False
    ),

    # --------------------------------------------------------------------------
    # --- Other & Internal ---
    # --------------------------------------------------------------------------
    dict(
        doctype_code="DEPRECIATION_ENTRY",
        code="DEPRECIATION_STANDARD",
        label="Depreciation",
        description="DR Depreciation Expense; CR Accumulated Depreciation.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="JOURNAL_ENTRY",
        code="MANUAL_JOURNAL",
        label="Manual Journal",
        description="For manual accounting adjustments.",
        is_active=True,
        is_primary=True,
    ),




    dict(
        doctype_code="EXPENSE_CLAIM",
        code="EXPENSE_DIRECT_LINE",
        label="Direct Expense",
        description="Records direct expense payments. DR Expense Account; CR Cash/Bank Account.",
        is_active=True,
        is_primary=True,
    ),
]

# ==============================================================================
# 2) TEMPLATE LINES (TEMPLATE_ITEMS)
# ==============================================================================
TEMPLATE_ITEMS: List[Dict[str, Any]] = [
    # --- NEW: Period Closing Voucher rules ---
    # LOSS: DR Retained Earnings; CR P&L Summary
    dict(template_code="PERIOD_CLOSING", sequence=10, effect=DEBIT,
         account_code=None, amount_source="LOSS_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="retained_earnings_account_id"),
    dict(template_code="PERIOD_CLOSING", sequence=20, effect=CREDIT,
         account_code=None, amount_source="LOSS_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="pl_summary_account_id"),
    # PROFIT: DR P&L Summary; CR Retained Earnings
    dict(template_code="PERIOD_CLOSING", sequence=30, effect=DEBIT,
         account_code=None, amount_source="PROFIT_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="pl_summary_account_id"),
    dict(template_code="PERIOD_CLOSING", sequence=40, effect=CREDIT,
         account_code=None, amount_source="PROFIT_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="retained_earnings_account_id"),
    # --------------------------------------------------------------------------
    # --- Sales & A/R Items ---
    # --------------------------------------------------------------------------
    # Sales Invoice (Financials Only)
    dict(template_code="SALES_INV_AR", sequence=10, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_AR", sequence=20, effect=CREDIT, account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_INV_AR", sequence=30, effect=CREDIT,
         account_code=None, amount_source="TAX_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="tax_account_id"),
    dict(template_code="SALES_INV_AR", sequence=40, effect=DEBIT,  account_code="5116", amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=50, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=60, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    # Inline receipt on SI: DR Cash/Bank; CR A/R (party ledger)
    dict(template_code="SALES_INV_AR", sequence=65, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    dict(template_code="SALES_INV_AR", sequence=70, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=False, requires_dynamic_account=True, context_key="party_ledger_account_id"),

    # Sales Invoice (Stock and Financials)
    dict(template_code="SALES_INV_WITH_STOCK", sequence=10, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=20, effect=CREDIT, account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=30, effect=CREDIT,
         account_code=None, amount_source="TAX_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="tax_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=40, effect=DEBIT,  account_code="5011", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=50, effect=CREDIT, account_code="1141", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=60, effect=DEBIT,  account_code="5116", amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=70, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=80, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),



    # Inline receipt on SI: DR Cash/Bank; CR A/R (party ledger)
    dict(template_code="SALES_INV_WITH_STOCK", sequence=85, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=90, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=False, requires_dynamic_account=True, context_key="party_ledger_account_id"),

    # Delivery Note (Stock Only)
    dict(template_code="DELIVERY_NOTE_COGS", sequence=10, effect=DEBIT, account_code="5011",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DELIVERY_NOTE_COGS", sequence=20, effect=CREDIT, account_code="1141",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),

    # -- Sales Return (Credit Note) – SI is_return=True
    dict(template_code="SALES_RETURN_CREDIT", sequence=10, effect=DEBIT,
         account_code=None, amount_source="DOCUMENT_SUBTOTAL",
         is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=20, effect=DEBIT,
         account_code=None, amount_source="TAX_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="tax_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=30, effect=CREDIT,
         account_code=None, amount_source="DOCUMENT_TOTAL",
         is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=40, effect=DEBIT,
         account_code="1141", amount_source="COGS_REVERSAL",
         is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_RETURN_CREDIT", sequence=50, effect=CREDIT,
         account_code="5011", amount_source="COGS_REVERSAL",
         is_required=False, requires_dynamic_account=False, context_key=None),
    # OPTIONAL: Inline refund on Sales Return (NOT needed if you use Payment Entry)
    dict(template_code="SALES_RETURN_CREDIT", sequence=55, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_REFUNDED",
         is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=56, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_REFUNDED",
         is_required=False, requires_dynamic_account=True, context_key="party_ledger_account_id"),

    # -- Cancel Sales Invoice (exact reversal of SI_AR)
    dict(template_code="CANCEL_SALES_INVOICE", sequence=10, effect=CREDIT,
         account_code=None, amount_source="DOCUMENT_TOTAL",
         is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="CANCEL_SALES_INVOICE", sequence=20, effect=DEBIT,
         account_code=None, amount_source="DOCUMENT_SUBTOTAL",
         is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="CANCEL_SALES_INVOICE", sequence=30, effect=DEBIT,
         account_code=None, amount_source="TAX_AMOUNT",
         is_required=False, requires_dynamic_account=True, context_key="tax_account_id"),

    # -- Cancel Delivery Note (exact reversal of DELIVERY_NOTE_COGS)
    dict(template_code="CANCEL_DELIVERY_NOTE", sequence=10, effect=CREDIT,
         account_code="5011", amount_source="COST_OF_GOODS_SOLD",
         is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="CANCEL_DELIVERY_NOTE", sequence=20, effect=DEBIT,
         account_code="1141", amount_source="COST_OF_GOODS_SOLD",
         is_required=True, requires_dynamic_account=False, context_key=None),

    # --------------------------------------------------------------------------
    # --- Purchasing & A/P Items ---
    # --------------------------------------------------------------------------
      # -- Purchase Receipt (GRNI)
        dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=10, effect=DEBIT,
             account_code="1141", amount_source="INVENTORY_PURCHASE_COST",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=20, effect=CREDIT,
             account_code="2210", amount_source="INVENTORY_PURCHASE_COST",
             is_required=True, requires_dynamic_account=False, context_key=None),

        # -- Purchase Invoice (Against Receipt)
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=10, effect=DEBIT,
             account_code="2210", amount_source="INVOICE_MATCHED_GRNI_VALUE",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=20, effect=CREDIT,
             account_code=None, amount_source="DOCUMENT_TOTAL",
             is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=30, effect=DEBIT,
             account_code="2311", amount_source="TAX_AMOUNT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=40, effect=DEBIT,
             account_code="5012", amount_source="PURCHASE_VARIANCE_DEBIT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=50, effect=CREDIT,
             account_code="5012", amount_source="PURCHASE_VARIANCE_CREDIT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=60, effect=DEBIT,
             account_code="5113", amount_source="ROUND_OFF_POSITIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=70, effect=CREDIT,
             account_code="4153", amount_source="ROUND_OFF_NEGATIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),

        # Inline payment on PI (Against Receipt): DR A/P; CR Cash/Bank
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=75, effect=DEBIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=80, effect=CREDIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),

        # -- Purchase Invoice (Direct)
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=10, effect=DEBIT,
             account_code="1141", amount_source="INVOICE_STOCK_VALUE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=20, effect=DEBIT,
             account_code="5014", amount_source="INVOICE_SERVICE_VALUE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=30, effect=CREDIT,
             account_code=None, amount_source="DOCUMENT_TOTAL",
             is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=40, effect=DEBIT,
             account_code="2311", amount_source="TAX_AMOUNT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=50, effect=DEBIT,
             account_code="5113", amount_source="ROUND_OFF_POSITIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=60, effect=CREDIT,
             account_code="4153", amount_source="ROUND_OFF_NEGATIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),

        # Inline payment on PI (Direct): DR A/P; CR Cash/Bank
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=75, effect=DEBIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=80, effect=CREDIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),

        # -- Purchase Return (After Invoice / PI is_return=True → Debit Note)
        dict(template_code="PURCHASE_RETURN_INVOICED", sequence=10, effect=DEBIT,
             account_code=None, amount_source="RETURN_DOCUMENT_TOTAL",
             is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="PURCHASE_RETURN_INVOICED", sequence=20, effect=CREDIT,
             account_code="1141", amount_source="RETURN_STOCK_VALUE",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_RETURN_INVOICED", sequence=30, effect=CREDIT,
             account_code="2311", amount_source="RETURN_TAX_AMOUNT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        # Inline refund on Purchase Return:
        # For normal debit note (no refund): AMOUNT_PAID = 0 → no effect.
        # For refund (your case): AMOUNT_PAID is NEGATIVE (e.g. -16.5)
        #   - Bank: effect=CREDIT with negative amount → DR Bank (cash in)
        #   - AP:   effect=DEBIT  with negative amount → CR Creditors (clear credit balance)
        dict(template_code="PURCHASE_RETURN_INVOICED", sequence=35, effect=CREDIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="cash_bank_account_id"),
        dict(template_code="PURCHASE_RETURN_INVOICED", sequence=36, effect=DEBIT,
             account_code=None, amount_source="AMOUNT_PAID",
             is_required=False, requires_dynamic_account=True, context_key="accounts_payable_account_id"),

    # -- Purchase Return (Before Invoice / PR is_return=True → reverse GRNI)
        dict(template_code="PURCHASE_RETURN_GRNI", sequence=10, effect=DEBIT,
             account_code="2210", amount_source="RETURN_STOCK_VALUE",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="PURCHASE_RETURN_GRNI", sequence=20, effect=CREDIT,
             account_code="1141", amount_source="RETURN_STOCK_VALUE",
             is_required=True, requires_dynamic_account=False, context_key=None),

        # -- Cancel Purchase Invoice (Against Receipt)
        dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=10, effect=CREDIT,
             account_code="2210", amount_source="INVOICE_MATCHED_GRNI_VALUE",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=20, effect=DEBIT,
             account_code=None, amount_source="DOCUMENT_TOTAL",
             is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=30, effect=CREDIT,
             account_code="2311", amount_source="TAX_AMOUNT",
             is_required=False, requires_dynamic_account=False, context_key=None),

        # -- Cancel Purchase Invoice (Direct)
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=10, effect=DEBIT,
             account_code=None, amount_source="DOCUMENT_TOTAL",
             is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=20, effect=CREDIT,
             account_code="1141", amount_source="INVOICE_STOCK_VALUE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=30, effect=CREDIT,
             account_code="5014", amount_source="INVOICE_SERVICE_VALUE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=40, effect=CREDIT,
             account_code="2311", amount_source="TAX_AMOUNT",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=50, effect=CREDIT,
             account_code="5113", amount_source="ROUND_OFF_POSITIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_INVOICE_DIRECT", sequence=60, effect=DEBIT,
             account_code="4153", amount_source="ROUND_OFF_NEGATIVE",
             is_required=False, requires_dynamic_account=False, context_key=None),

        # -- Cancel Purchase Receipt (reverse PR GRNI)
        dict(template_code="CANCEL_PURCHASE_RECEIPT", sequence=10, effect=CREDIT,
             account_code="1141", amount_source="INVENTORY_PURCHASE_COST",
             is_required=True, requires_dynamic_account=False, context_key=None),
        dict(template_code="CANCEL_PURCHASE_RECEIPT", sequence=20, effect=DEBIT,
             account_code="2210", amount_source="INVENTORY_PURCHASE_COST",
             is_required=True, requires_dynamic_account=False, context_key=None),

    # --------------------------------------------------------------------------
    # --- Stock Reconciliation Items ---
    # --------------------------------------------------------------------------

    # Stock Reconciliation - Following your existing pattern
    # We'll handle gain/loss logic in the service layer
    # --- Stock Reconciliation Items ---
    dict(
        template_code="STOCK_RECON_GENERAL",
        sequence=10,
        effect=DEBIT,
        account_code="1141",  # Stock in Hand
        amount_source="STOCK_RECON_DIFFERENCE",
        is_required=True,
        requires_dynamic_account=False,
        context_key=None,
    ),
    dict(
        template_code="STOCK_RECON_GENERAL",
        sequence=20,
        effect=CREDIT,
        account_code=None,  # Difference Account (Opening / Stock Adjustment)
        amount_source="STOCK_RECON_DIFFERENCE",
        is_required=True,
        requires_dynamic_account=True,
        context_key="difference_account_id",
    ),
    # --- Stock Entry Items ---
    # This uses the signed total stock value difference from the SLEs.
    # - If STOCK_ENTRY_DIFFERENCE > 0 → Inventory gain:
    #       DR Inventory (1141), CR Difference Account
    # - If STOCK_ENTRY_DIFFERENCE < 0 → Inventory loss:
    #       DR Difference Account, CR Inventory
    #   (handled via signed amounts just like Stock Reconciliation)
    dict(
        template_code="STOCK_ENTRY_GENERAL",
        sequence=10,
        effect=DEBIT,
        account_code="1141",  # Inventory / Stock in Hand
        amount_source="STOCK_ENTRY_DIFFERENCE",
        is_required=True,
        requires_dynamic_account=False,
        context_key=None,
    ),
    dict(
        template_code="STOCK_ENTRY_GENERAL",
        sequence=20,
        effect=CREDIT,
        account_code=None,  # Difference Account (Stock Adjustments, etc.)
        amount_source="STOCK_ENTRY_DIFFERENCE",
        is_required=True,
        requires_dynamic_account=True,
        context_key="difference_account_id",
    ),

    # --------------------------------------------------------------------------
    # --- Payments & Bank/Cash Items ---
    # --------------------------------------------------------------------------
    # --- PAYMENT_RECEIVE ------------------------------------------------------
    # DR Bank/Cash (dynamic from header paid_to or explicit cash_bank_account_id)
    dict(template_code="PAYMENT_RECEIVE", sequence=10, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    # CR Party Ledger (typically A/R 1131 for Customer receipt)
    dict(template_code="PAYMENT_RECEIVE", sequence=20, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_RECEIVED",
         is_required=True, requires_dynamic_account=True, context_key="party_ledger_account_id"),

    # --- PAYMENT_PAY ----------------------------------------------------------
    # DR Party Ledger (typically A/P 2111 for Supplier payment)
    dict(template_code="PAYMENT_PAY", sequence=10, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_PAID",
         is_required=True, requires_dynamic_account=True, context_key="party_ledger_account_id"),
    # CR Bank/Cash
    dict(template_code="PAYMENT_PAY", sequence=20, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_PAID",
         is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),

    # --- PAYMENT_INTERNAL_TRANSFER -------------------------------------------
    # DR Target Bank/Cash (paid_to)
    dict(template_code="PAYMENT_INTERNAL_TRANSFER", sequence=10, effect=DEBIT,
         account_code=None, amount_source="AMOUNT_PAID",
         is_required=True, requires_dynamic_account=True, context_key="paid_to_account_id"),
    # CR Source Bank/Cash (paid_from)
    dict(template_code="PAYMENT_INTERNAL_TRANSFER", sequence=20, effect=CREDIT,
         account_code=None, amount_source="AMOUNT_PAID",
         is_required=True, requires_dynamic_account=True, context_key="paid_from_account_id"),
    # --------------------------------------------------------------------------
    # --- Other & Internal Items ---
    # --------------------------------------------------------------------------
    # Depreciation
    dict(template_code="DEPRECIATION_STANDARD", sequence=10, effect=DEBIT,  account_code="5119", amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DEPRECIATION_STANDARD", sequence=20, effect=CREDIT, account_code="1230", amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),

    # --------------------------------------------------------------------------
    # --- expense related ---
    # --------------------------------------------------------------------------
    dict(template_code="EXPENSE_DIRECT_LINE", sequence=10, effect=DEBIT,
         account_code=None, amount_source="DOCUMENT_TOTAL",
         is_required=True, requires_dynamic_account=True, context_key="expense_account_id"),
    dict(template_code="EXPENSE_DIRECT_LINE", sequence=20, effect=CREDIT,
         account_code=None, amount_source="DOCUMENT_TOTAL",
         is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    # Manual Journal: no default items
]