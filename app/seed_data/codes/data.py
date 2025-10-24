# seed_data/codes/data.py
from __future__ import annotations
from typing import List, Dict

# NOTE:
# - scope: "GLOBAL" | "COMPANY" | "BRANCH"
# - reset_policy: "NEVER" | "YEARLY" | "MONTHLY"
# - pattern tokens: {PREFIX}, {YYYY}, {MM}, {SEQ}

CODE_TYPES: List[Dict] = [
    # General System
    dict(name="Username", prefix="USERNAME", pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER",
         padding=4),

    # HR / Masters
    dict(name="Employee",           prefix="HR-EMP", pattern="{PREFIX}-{SEQ}",           scope="COMPANY", reset_policy="NEVER",  padding=5),
    dict(name="Supplier",           prefix="SUP",    pattern="{PREFIX}-{SEQ}",           scope="COMPANY",  reset_policy="NEVER",  padding=4),
    dict(name="Customer",           prefix="CUST",   pattern="{PREFIX}-{SEQ}",           scope="COMPANY",  reset_policy="NEVER",  padding=4),
    dict(name="Warehouse",          prefix="WH",     pattern="{PREFIX}-{SEQ}",           scope="COMPANY",  reset_policy="NEVER",  padding=3),

    # Purchasing (branch-scoped, yearly)
    dict(name="Purchase RFQ",       prefix="PRFQ",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Purchase Order",     prefix="PO",     pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Purchase Receipt",   prefix="PR",     pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Purchase Invoice",   prefix="PINV",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Purchase Return",    prefix="PRET",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),

    # Sales (branch-scoped, yearly)
    dict(name="Sales RFQ",          prefix="SRFQ",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Sales Order",        prefix="SO",     pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Sales Invoice",      prefix="SINV",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Sales Return",       prefix="SRET",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Sales Delivery Note",prefix="SDN",  pattern="{PREFIX}-{YYYY}-{SEQ}", scope="BRANCH", reset_policy="YEARLY", padding=5),
    # Finance / Expense (branch-scoped, yearly)
    dict(name="Payment",            prefix="PAY",    pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Expense",            prefix="EXP",    pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),

    # Stock / Inventory (branch-scoped)
    dict(name="Journal Entry", prefix="JE", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="BRANCH", reset_policy="YEARLY",
         padding=5),

    dict(
        name="Bin",
        prefix="BIN",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=6
    ),

    dict(name="Landed Cost Voucher",prefix="LCV",    pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Stock Ledger",       prefix="SL",     pattern="{PREFIX}-{SEQ}",           scope="BRANCH",  reset_policy="NEVER",  padding=7),
    dict(name="Stock Entry",        prefix="SE",     pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Stock Reconciliation",prefix="MAT-RECO",   pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
    dict(name="Stock Transfer",     prefix="ST",     pattern="{PREFIX}-{YYYY}-{SEQ}",    scope="BRANCH",  reset_policy="YEARLY", padding=5),
]
