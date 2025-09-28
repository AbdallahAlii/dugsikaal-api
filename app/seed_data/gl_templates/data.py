# seed_data/gl_templates/data.py
from __future__ import annotations
from typing import List, Dict, Any

"""
Declarative GL templates, split into TEMPLATE_DEFS (headers) and TEMPLATE_ITEMS (lines).

- doctype_code: matches seed_data/doctypes/data.py (e.g., "SALES_INVOICE")
- account_code: from your COA (seed_data/coa/data.py), e.g., "4101" (Sales Income)
- effect: "DEBIT" | "CREDIT"
- amount_source: string keys your posting service computes (see AMOUNT_SOURCES)
- requires_dynamic_account: True for party/bank-specific lines (account_id left NULL)
- context_key: runtime resolver key (e.g., "accounts_receivable_account_id")
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
    "RECEIPT_STOCK_VALUE": "Total accepted stock value on receipt",
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
}

# Use constants (no accidental 'D'/'C' strings)
DEBIT = "DEBIT"
CREDIT = "CREDIT"

# -------------------------
# 1) Template headers
# -------------------------
TEMPLATE_DEFS: List[Dict[str, Any]] = [
    # --- Sales ---
    dict(
        doctype_code="SALES_INVOICE",
        code="SALES_INV_AR",
        label="Sales Invoice (Accounts Receivable)",
        description="DR A/R; CR Income (+ VAT). No stock movement.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="SALES_INVOICE",
        code="SALES_INV_WITH_STOCK",
        label="Sales Invoice (Direct Stock & Finance)",
        description="DR A/R; CR Income (+ VAT); DR COGS; CR Inventory.",
        is_active=True,
        is_primary=False,
    ),

    dict(
        doctype_code="DELIVERY_NOTE",
        code="DELIVERY_NOTE_COGS",
        label="COGS on Delivery",
        description="DR COGS; CR Inventory at delivery time.",
        is_active=True,
        is_primary=True,
    ),

    dict(
        doctype_code="SALES_RETURN",
        code="SALES_RETURN_CREDIT",
        label="Sales Return (Credit to Customer A/R)",
        description="Reverse income & VAT; credit customer A/R. Optionally reverse COGS/Inventory if restocked.",
        is_active=True,
        is_primary=True,
    ),

    # Cash/Bank movements on customer side
    dict(
        doctype_code="RECEIPT_ENTRY",
        code="RECEIPT_FROM_CUSTOMER",
        label="Receipt from Customer",
        description="DR Cash/Bank; CR A/R (settle invoices or create customer credit/prepayment).",
        is_active=True,
        is_primary=True,   # primary for RECEIPT_ENTRY
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="REFUND_TO_CUSTOMER",
        label="Refund to Customer",
        description="DR A/R (apply against credit/note); CR Cash/Bank.",
        is_active=True,
        is_primary=False,  # not primary; PAYMENT_TO_SUPPLIER can remain primary
    ),

    dict(
        doctype_code="SALES_INVOICE",
        code="AR_WRITE_OFF",
        label="Write-off Customer Balance",
        description="DR Bad Debt Expense; CR A/R for uncollectible balances.",
        is_active=True,
        is_primary=False,
    ),

    # --- Buying / GRNI ---
    dict(
        doctype_code="PURCHASE_RECEIPT",
        code="PURCHASE_RECEIPT_GRNI",
        label="Purchase Receipt (Inventory + GRNI)",
        description="DR 1141 Inventory (stock items only); CR 2210 Stock Received but Not Billed (GRNI).",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_AGAINST_RECEIPT",
        label="Purchase Invoice (Clear GRNI + A/P)",
        description="DR 2210 GRNI (matched value); DR 2311 VAT (input); CR A/P.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_INVOICE",
        code="PURCHASE_INVOICE_DIRECT",
        label="Purchase Invoice (Direct to A/P + Inventory/Expense)",
        description="DR 1141 Inventory (stock) and/or DR Expense (services); DR 2311 VAT; CR A/P.",
        is_active=True,
        is_primary=False,
    ),

    # Payments / refunds (A/P)
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="PAYMENT_TO_SUPPLIER",
        label="Payment to Supplier",
        description="DR 2111 Creditors (A/P); CR Cash/Bank. (Supports advances when no invoice.)",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PAYMENT_ENTRY",
        code="REFUND_FROM_SUPPLIER",
        label="Refund from Supplier",
        description="DR Cash/Bank; CR 2111 Creditors (reduce debit balance / advance).",
        is_active=True,
        is_primary=False,
    ),

    # Purchase returns
    dict(
        doctype_code="PURCHASE_RETURN",
        code="PURCHASE_RETURN_AGAINST_INVOICE",
        label="Purchase Return (After Invoice)",
        description="CR Inventory (1141) for returned stock; DR A/P (2111). DR/CR VAT as needed.",
        is_active=True,
        is_primary=True,
    ),
    dict(
        doctype_code="PURCHASE_RETURN",
        code="PURCHASE_RETURN_AGAINST_RECEIPT",
        label="Purchase Return (Before Invoice / GRNI)",
        description="CR Inventory (1141); DR GRNI (2210) to reverse the receipt.",
        is_active=True,
        is_primary=False,
    ),

    dict(
        doctype_code="PURCHASE_INVOICE",
        code="AP_WRITE_OFF",
        label="Write-off Supplier Balance",
        description="DR 2111 Creditors; CR 4153 Round Off Income or chosen write-off income.",
        is_active=True,
        is_primary=False,
    ),

    # Depreciation
    dict(
        doctype_code="DEPRECIATION_ENTRY",
        code="DEPRECIATION_STANDARD",
        label="Depreciation",
        description="DR Depreciation Expense (5119); CR Accumulated Depreciation (1230).",
        is_active=True,
        is_primary=True,
    ),

    # Manual journal
    dict(
        doctype_code="JOURNAL_ENTRY",
        code="MANUAL_JOURNAL",
        label="Manual Journal (No Defaults)",
        description="Admin-defined lines in UI/service.",
        is_active=True,
        is_primary=True,
    ),
]

# -------------------------
# 2) Template items (lines)
# -------------------------
TEMPLATE_ITEMS: List[Dict[str, Any]] = [
    # --- SALES INVOICE (A/R only) ---
    dict(template_code="SALES_INV_AR", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_AR", sequence=20, effect=CREDIT, account_code=None,
         amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True,
         context_key="income_account_id"),
    dict(template_code="SALES_INV_AR", sequence=30, effect=CREDIT, account_code="2311",
         amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=40, effect=DEBIT,  account_code="5116",
         amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=50, effect=DEBIT,  account_code="5113",
         amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_AR", sequence=60, effect=CREDIT, account_code="4153",
         amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- SALES INVOICE (Direct Stock & Finance) ---
    dict(template_code="SALES_INV_WITH_STOCK", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=20, effect=CREDIT, account_code=None,
         amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True,
         context_key="income_account_id"),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=30, effect=CREDIT, account_code="2311",
         amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=40, effect=DEBIT,  account_code="5011",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=50, effect=CREDIT, account_code="1141",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=60, effect=DEBIT,  account_code="5116",
         amount_source="DISCOUNT_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=70, effect=DEBIT,  account_code="5113",
         amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_INV_WITH_STOCK", sequence=80, effect=CREDIT, account_code="4153",
         amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- DELIVERY NOTE (COGS only) ---
    dict(template_code="DELIVERY_NOTE_COGS", sequence=10, effect=DEBIT,  account_code="5011",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DELIVERY_NOTE_COGS", sequence=20, effect=CREDIT, account_code="1141",
         amount_source="COST_OF_GOODS_SOLD", is_required=True, requires_dynamic_account=False, context_key=None),

    # --- SALES RETURN (Credit Note) ---
    dict(template_code="SALES_RETURN_CREDIT", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="DOCUMENT_SUBTOTAL", is_required=True, requires_dynamic_account=True,
         context_key="income_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=20, effect=DEBIT,  account_code="2311",
         amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_RETURN_CREDIT", sequence=30, effect=CREDIT, account_code=None,
         amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),
    dict(template_code="SALES_RETURN_CREDIT", sequence=40, effect=DEBIT,  account_code="1141",
         amount_source="COGS_REVERSAL", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="SALES_RETURN_CREDIT", sequence=50, effect=CREDIT, account_code="5011",
         amount_source="COGS_REVERSAL", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- RECEIPT FROM CUSTOMER ---
    dict(template_code="RECEIPT_FROM_CUSTOMER", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),
    dict(template_code="RECEIPT_FROM_CUSTOMER", sequence=20, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_RECEIVED", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),

    # --- REFUND TO CUSTOMER ---
    dict(template_code="REFUND_TO_CUSTOMER", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),
    dict(template_code="REFUND_TO_CUSTOMER", sequence=20, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),

    # --- A/R WRITE-OFF ---
    dict(template_code="AR_WRITE_OFF", sequence=10, effect=DEBIT,  account_code="5118",
         amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="AR_WRITE_OFF", sequence=20, effect=CREDIT, account_code=None,
         amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=True,
         context_key="accounts_receivable_account_id"),

    # --- PURCHASE RECEIPT (GRNI) ---
    dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=10, effect=DEBIT, account_code="1141",
         amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RECEIPT_GRNI", sequence=20, effect=CREDIT, account_code="2210",
         amount_source="INVENTORY_PURCHASE_COST", is_required=True, requires_dynamic_account=False, context_key=None),

    # --- PURCHASE INVOICE AGAINST RECEIPT ---
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=10, effect=DEBIT,  account_code="2210",
         amount_source="INVOICE_MATCHED_GRNI_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=20, effect=CREDIT, account_code=None,
         amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=30, effect=DEBIT,  account_code="2311",
         amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=40, effect=DEBIT,  account_code="5012",
         amount_source="PURCHASE_VARIANCE_DEBIT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=50, effect=CREDIT, account_code="5012",
         amount_source="PURCHASE_VARIANCE_CREDIT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=60, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_PAID", is_required=False, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=70, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_PAID", is_required=False, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=80, effect=DEBIT,  account_code="5113",
         amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_AGAINST_RECEIPT", sequence=90, effect=CREDIT, account_code="4153",
         amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- PURCHASE INVOICE (DIRECT) ---
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=10, effect=DEBIT,  account_code="1141",
         amount_source="INVOICE_STOCK_VALUE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=20, effect=DEBIT,  account_code="5014",
        amount_source="INVOICE_SERVICE_VALUE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=30, effect=CREDIT, account_code=None,
         amount_source="DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=40, effect=DEBIT,  account_code="2311",
         amount_source="TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=50, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_PAID", is_required=False, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=60, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_PAID", is_required=False, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=70, effect=DEBIT,  account_code="5113",
         amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_INVOICE_DIRECT", sequence=80, effect=CREDIT, account_code="4153",
         amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- PAYMENT TO SUPPLIER ---
    dict(template_code="PAYMENT_TO_SUPPLIER", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_PAID", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PAYMENT_TO_SUPPLIER", sequence=20, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_PAID", is_required=True, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),

    # --- REFUND FROM SUPPLIER ---
    dict(template_code="REFUND_FROM_SUPPLIER", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True,
         context_key="cash_bank_account_id"),
    dict(template_code="REFUND_FROM_SUPPLIER", sequence=20, effect=CREDIT, account_code=None,
         amount_source="AMOUNT_REFUNDED", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),

    # --- PURCHASE RETURN (after invoice) ---
    dict(template_code="PURCHASE_RETURN_AGAINST_INVOICE", sequence=10, effect=CREDIT, account_code="1141",
         amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_AGAINST_INVOICE", sequence=20, effect=DEBIT,  account_code=None,
         amount_source="RETURN_DOCUMENT_TOTAL", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="PURCHASE_RETURN_AGAINST_INVOICE", sequence=30, effect=CREDIT, account_code="2311",
         amount_source="RETURN_TAX_AMOUNT", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_AGAINST_INVOICE", sequence=40, effect=DEBIT,  account_code="5113",
         amount_source="ROUND_OFF_POSITIVE", is_required=False, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_AGAINST_INVOICE", sequence=50, effect=CREDIT, account_code="4153",
         amount_source="ROUND_OFF_NEGATIVE", is_required=False, requires_dynamic_account=False, context_key=None),

    # --- PURCHASE RETURN (before invoice / GRNI reversal) ---
    dict(template_code="PURCHASE_RETURN_AGAINST_RECEIPT", sequence=10, effect=CREDIT, account_code="1141",
         amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="PURCHASE_RETURN_AGAINST_RECEIPT", sequence=20, effect=DEBIT,  account_code="2210",
         amount_source="RETURN_STOCK_VALUE", is_required=True, requires_dynamic_account=False, context_key=None),

    # --- A/P WRITE-OFF ---
    dict(template_code="AP_WRITE_OFF", sequence=10, effect=DEBIT,  account_code=None,
         amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=True,
         context_key="accounts_payable_account_id"),
    dict(template_code="AP_WRITE_OFF", sequence=20, effect=CREDIT, account_code="4153",
         amount_source="WRITE_OFF_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),

    # --- Depreciation ---
    dict(template_code="DEPRECIATION_STANDARD", sequence=10, effect=DEBIT,  account_code="5119",
         amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),
    dict(template_code="DEPRECIATION_STANDARD", sequence=20, effect=CREDIT, account_code="1230",
         amount_source="DEPRECIATION_AMOUNT", is_required=True, requires_dynamic_account=False, context_key=None),

    # Manual Journal: no default items
]
