
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
    "STOCK_VALUE_DIFFERENCE": "Value difference for stock reconciliation (positive for gains, negative for losses)",
    # Stock Reconciliation
    "STOCK_RECON_DIFFERENCE": "Absolute value difference for stock reconciliation",
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

    # --- Sales Returns, Cancellations & Write-Offs ---
    dict(
        doctype_code="SALES_RETURN",
        code="SALES_RETURN_CREDIT",
        label="Sales Return (Credit Note)",
        description="Handles customer returns. Reverses income and A/R. Optionally reverses COGS if items are restocked.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="CANCEL_SALES_INVOICE",
        label="Cancel Sales Invoice",
        description="A full and exact reversal of a submitted Sales Invoice. Used to correct errors.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="DELIVERY_NOTE",
        code="CANCEL_DELIVERY_NOTE",
        label="Cancel Delivery Note",
        description="A full and exact reversal of a submitted Delivery Note.",
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
    # --- Purchasing & Accounts Payable ---
    # --------------------------------------------------------------------------
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="PURCHASE_RECEIPT_GRNI",
        label="Purchase Receipt (Inventory + GRNI)",
        description="Records received stock and accrues a liability in 'Goods Received Not Invoiced'. DR Inventory; CR GRNI.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_AGAINST_RECEIPT",
        label="Purchase Invoice (Clear GRNI)",
        description="Books the supplier's bill against a prior receipt. DR GRNI; DR Tax; CR A/P.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_DIRECT",
        label="Purchase Invoice (Direct)",
        description="Books a bill for services or items without a prior receipt. DR Expense/Inventory; DR Tax; CR A/P.",
        is_active=True,
        is_primary=False,
    ),

    # --- Purchase Returns, Cancellations & Write-Offs ---
    dict(
        doctype_code="PURCHASE_RETURN",
        code="PURCHASE_RETURN_INVOICED",
        label="Purchase Return (After Invoice / Debit Note)",
        description="Returns goods after invoicing. Creates a debit note against the supplier. DR A/P; CR Inventory; CR Tax.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_RETURN",
        code="PURCHASE_RETURN_GRNI",
        label="Purchase Return (Before Invoice / GRNI)",
        description="Returns goods before the supplier's invoice is booked. Reverses the GRNI entry. DR GRNI; CR Inventory.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="CANCEL_PURCHASE_INVOICE",
        label="Cancel Purchase Invoice",
        description="A full and exact reversal of a submitted Purchase Invoice.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="CANCEL_PURCHASE_RECEIPT",
        label="Cancel Purchase Receipt",
        description="A full and exact reversal of a submitted Purchase Receipt.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="AP_WRITE_OFF",
        label="Write-off Supplier Balance",
        description="DR A/P; CR Write-off Income for unpayable balances.",
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
    # --------------------------------------------------------------------------
    # --- Payments & Bank/Cash ---
    # --------------------------------------------------------------------------
    dict(
        doctype_code="RECEIPT_ENTRY",
        code="RECEIPT_FROM_CUSTOMER",
        label="Receipt from Customer",
        description="Records money received from a customer. DR Bank; CR A/R.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="PAYMENT_TO_SUPPLIER",
        label="Payment to Supplier",
        description="Records money paid to a supplier. DR A/P; CR Bank.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="REFUND_TO_CUSTOMER",
        label="Refund to Customer",
        description="Records a cash refund to a customer, settling a credit note. DR A/R; CR Bank.",
        is_active=True,
        is_primary=False,
    ),
    dict(
        doctype_code="RECEIPT_ENTRY", # Can be RECEIPT_ENTRY or PAYMENT_ENTRY
        code="REFUND_FROM_SUPPLIER",
        label="Refund from Supplier",
        description="Records a cash refund from a supplier, settling a debit note. DR Bank; CR A/P.",
        is_active=True,
        is_primary=False,
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
]

# ==============================================================================
# 2) TEMPLATE LINES (TEMPLATE_ITEMS)
# ==============================================================================
TEMPLATE_ITEMS: List[Dict[str, Any]] = [
    # --------------------------------------------------------------------------
    # --- Sales & A/R Items ---
    # --------------------------------------------------------------------------
    # Sales Invoice (Financials Only)
    dict(template_code="SALES_INV_AR", sequence=10, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_AR", sequence=20, effect=CREDIT, account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_INV_AR", sequence=30, effect=CREDIT, account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=40, effect=DEBIT,  account_code="5116", amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=50, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=60, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # Sales Invoice (Stock and Financials)
    dict(template_code="SALES_INV_WITH_STOCK", sequence=10, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=20, effect=CREDIT, account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=30, effect=CREDIT, account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=40, effect=DEBIT,  account_code="5011", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=50, effect=CREDIT, account_code="1141", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=60, effect=DEBIT,  account_code="5116", amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=70, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=80, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # Delivery Note (Stock Only)
    dict(template_code="DELIVERY_NOTE_COGS", sequence=10, effect=DEBIT,  account_code="5011", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DELIVERY_NOTE_COGS", sequence=20, effect=CREDIT, account_code="1141", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),

    # --- Sales Returns, Cancellations & Write-Off Items ---
    # Sales Return (Credit Note)
    dict(template_code="SALES_RETURN_CREDIT", sequence=10, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=20, effect=DEBIT,  account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_RETURN_CREDIT", sequence=30, effect=CREDIT, account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=40, effect=DEBIT,  account_code="1141", amount_source="COGS_REVERSAL", is_required=False, requires_dynamic_account=False, context_key=None), # Optional if restocked
    dict(template_code="SALES_RETURN_CREDIT", sequence=50, effect=CREDIT, account_code="5011", amount_source="COGS_REVERSAL", is_required=False, requires_dynamic_account=False, context_key=None), # Optional if restocked

    # Cancel Sales Invoice (Exact reversal of SALES_INV_AR)
    dict(template_code="CANCEL_SALES_INVOICE", sequence=10, effect=CREDIT, account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="CANCEL_SALES_INVOICE", sequence=20, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True, context_key="income_account_id"),
    dict(template_code="CANCEL_SALES_INVOICE", sequence=30, effect=DEBIT,  account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),

    # Cancel Delivery Note (Exact reversal of DELIVERY_NOTE_COGS)
    dict(template_code="CANCEL_DELIVERY_NOTE", sequence=10, effect=CREDIT, account_code="5011", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="CANCEL_DELIVERY_NOTE", sequence=20, effect=DEBIT,  account_code="1141", amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),

    # A/R Write-Off
    dict(template_code="AR_WRITE_OFF", sequence=10, effect=DEBIT,  account_code="5118", amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="AR_WRITE_OFF", sequence=20, effect=CREDIT, account_code=None, amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),

    # --------------------------------------------------------------------------
    # --- Purchasing & A/P Items ---
    # --------------------------------------------------------------------------
    # Purchase Receipt (GRNI)
    dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=10, effect=DEBIT,  account_code="1141", amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=20, effect=CREDIT, account_code="2210", amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),

    # Purchase Invoice (Against Receipt)
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=10, effect=DEBIT,  account_code="2210", amount_source="INVOICE_MATCHED_GRNI_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=20, effect=CREDIT, account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=30, effect=DEBIT,  account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=40, effect=DEBIT,  account_code="5012", amount_source="PURCHASE_VARIANCE_DEBIT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=50, effect=CREDIT, account_code="5012", amount_source="PURCHASE_VARIANCE_CREDIT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=60, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=70, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # Purchase Invoice (Direct)
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=10, effect=DEBIT,  account_code="1141", amount_source="INVOICE_STOCK_VALUE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=20, effect=DEBIT,  account_code="5014", amount_source="INVOICE_SERVICE_VALUE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=30, effect=CREDIT, account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=40, effect=DEBIT,  account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=50, effect=DEBIT,  account_code="5113", amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=60, effect=CREDIT, account_code="4153", amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- Purchase Returns, Cancellations & Write-Off Items ---
    # Purchase Return (After Invoice / Debit Note)
    dict(template_code="PURCHASE_RETURN_INVOICED", sequence=10, effect=DEBIT,  account_code=None, amount_source="RETURN_DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_RETURN_INVOICED", sequence=20, effect=CREDIT, account_code="1141", amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_INVOICED", sequence=30, effect=CREDIT, account_code="2311", amount_source="RETURN_TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),

    # Purchase Return (Before Invoice / GRNI)
    dict(template_code="PURCHASE_RETURN_GRNI", sequence=10, effect=DEBIT,  account_code="2210", amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_GRNI", sequence=20, effect=CREDIT, account_code="1141", amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),

    # Cancel Purchase Invoice (Exact reversal of PURCHASE_INVOICE_AGAINST_RECEIPT)
    dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=10, effect=CREDIT, account_code="2210", amount_source="INVOICE_MATCHED_GRNI_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=20, effect=DEBIT,  account_code=None, amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="CANCEL_PURCHASE_INVOICE", sequence=30, effect=CREDIT, account_code="2311", amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),

    # Cancel Purchase Receipt (Exact reversal of PURCHASE_RECEIPT_GRNI)
    dict(template_code="CANCEL_PURCHASE_RECEIPT", sequence=10, effect=CREDIT, account_code="1141", amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="CANCEL_PURCHASE_RECEIPT", sequence=20, effect=DEBIT,  account_code="2210", amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),

    # A/P Write-Off
    dict(template_code="AP_WRITE_OFF", sequence=10, effect=DEBIT,  account_code=None, amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="AP_WRITE_OFF", sequence=20, effect=CREDIT, account_code="4153", amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    # --------------------------------------------------------------------------
    # --- Stock Reconciliation Items ---
    # --------------------------------------------------------------------------

    # Stock Reconciliation - Following your existing pattern
    # We'll handle gain/loss logic in the service layer
    dict(template_code="STOCK_RECON_GENERAL", sequence=10, effect=DEBIT, account_code="1141",
         amount_source="STOCK_RECON_DIFFERENCE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="STOCK_RECON_GENERAL", sequence=20, effect=CREDIT, account_code=None,
         amount_source="STOCK_RECON_DIFFERENCE", is_required=False, requires_dynamic_account=True,
         context_key="difference_account_id"),
    # --------------------------------------------------------------------------
    # --- Payments & Bank/Cash Items ---
    # --------------------------------------------------------------------------
    # Receipt from Customer
    dict(template_code="RECEIPT_FROM_CUSTOMER", sequence=10, effect=DEBIT,  account_code=None, amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    dict(template_code="RECEIPT_FROM_CUSTOMER", sequence=20, effect=CREDIT, account_code=None, amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),

    # Payment to Supplier
    dict(template_code="PAYMENT_TO_SUPPLIER", sequence=10, effect=DEBIT,  account_code=None, amount_source="AMOUNT_PAID", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),
    dict(template_code="PAYMENT_TO_SUPPLIER", sequence=20, effect=CREDIT, account_code=None, amount_source="AMOUNT_PAID", is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),

    # Refund to Customer
    dict(template_code="REFUND_TO_CUSTOMER", sequence=10, effect=DEBIT,  account_code=None, amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True, context_key="accounts_receivable_account_id"),
    dict(template_code="REFUND_TO_CUSTOMER", sequence=20, effect=CREDIT, account_code=None, amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),

    # Refund from Supplier
    dict(template_code="REFUND_FROM_SUPPLIER", sequence=10, effect=DEBIT,  account_code=None, amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True, context_key="cash_bank_account_id"),
    dict(template_code="REFUND_FROM_SUPPLIER", sequence=20, effect=CREDIT, account_code=None, amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True, context_key="accounts_payable_account_id"),

    # --------------------------------------------------------------------------
    # --- Other & Internal Items ---
    # --------------------------------------------------------------------------
    # Depreciation
    dict(template_code="DEPRECIATION_STANDARD", sequence=10, effect=DEBIT,  account_code="5119", amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DEPRECIATION_STANDARD", sequence=20, effect=CREDIT, account_code="1230", amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),

    # Manual Journal: no default items
]