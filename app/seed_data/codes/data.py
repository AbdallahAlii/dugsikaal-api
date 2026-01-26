# seed_data/codes/data.py
from __future__ import annotations
from typing import List, Dict

# NOTE:
# - scope: "GLOBAL" | "COMPANY" | "BRANCH"
# - reset_policy: "NEVER" | "YEARLY" | "MONTHLY"
# - pattern tokens: {PREFIX}, {YYYY}, {MM}, {SEQ}
#
# Guideline used here:
#   • Any document that may appear in company-wide reports/audits MUST be unique per company → scope="COMPANY"
#   • Use scope="BRANCH" only if pattern includes branch identifier (not used in this setup)
#   • Keep GLOBAL only for true system-wide series

CODE_TYPES: List[Dict] = [
    # =========================================================================
    # General System
    # =========================================================================
    dict(
        name="Username",
        prefix="USERNAME",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=4,
    ),
    dict(
        name="Data Import",
        prefix="DIMP",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="GLOBAL",  # system-wide
        reset_policy="YEARLY",
        padding=4,
    ),

    # =========================================================================
    # Accounting / Shareholders
    # =========================================================================
    dict(
        name="Shareholder",
        prefix="ACC-SH",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=4,
    ),

    # =========================================================================
    # HR / Masters (company-wide uniqueness)
    # =========================================================================
    dict(name="Employee",   prefix="HR-EMP", pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=5),
    dict(name="Supplier",   prefix="SUP",    pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=4),
    dict(name="Customer",   prefix="CUST",   pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=4),
    dict(name="Warehouse",  prefix="WH",     pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=3),

    # =========================================================================
    # Purchasing (COMPANY scope to avoid duplicates across branches)
    # =========================================================================
    dict(name="Purchase RFQ",     prefix="PRFQ", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Purchase Order",   prefix="PO",   pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Purchase Receipt", prefix="PR",   pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Purchase Invoice", prefix="PINV", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Purchase Return",  prefix="PRET", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),

    # =========================================================================
    # Sales (COMPANY scope to avoid duplicates across branches)
    # =========================================================================
    dict(name="Sales RFQ",           prefix="SRFQ", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Sales Order",         prefix="SO",   pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Sales Invoice",       prefix="SINV", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Sales Return",        prefix="SRET", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Sales Delivery Note", prefix="SDN",  pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),

    # =========================================================================
    # Finance / Expense (COMPANY scope to avoid duplicates across branches)
    # =========================================================================
    dict(name="Payment", prefix="PAY", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Expense", prefix="EXP", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),

    # =========================================================================
    # Accounting / Closing (already COMPANY)
    # =========================================================================
    dict(
        name="Period Closing Voucher",
        prefix="PCV",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),

    # =========================================================================
    # Stock / Inventory
    # IMPORTANT: company-wide uniqueness is best for audit trails & stock valuation
    # =========================================================================
    dict(name="Journal Entry",         prefix="JE",  pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Landed Cost Voucher",   prefix="LCV", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Stock Entry",           prefix="SE",  pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Stock Reconciliation",  prefix="SRE", pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),
    dict(name="Stock Transfer",        prefix="ST",  pattern="{PREFIX}-{YYYY}-{SEQ}", scope="COMPANY", reset_policy="YEARLY", padding=5),

    # These are not “documents” users search by in audit the same way, but uniqueness still helps
    dict(
        name="Bin",
        prefix="BIN",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=6,
    ),
    dict(
        name="Stock Ledger",
        prefix="SL",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=7,
    ),

    # ─────────────────────────────────────────
    # Education masters
    # ─────────────────────────────────────────
    # Student: you requested YEAR to know registration year.
    # Best practice: keep it COMPANY scope so codes are unique across all branches.
    dict(
        name="Student",
        prefix="STU",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. STU-2025-00001
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Guardian",
        prefix="GDN",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=5,
    ),
    dict(
        name="Instructor",
        prefix="INS",
        pattern="{PREFIX}-{SEQ}",
        scope="COMPANY",
        reset_policy="NEVER",
        padding=5,
    ),
    dict(
        name="Student Group",
        prefix="EDU-GRP",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. EDU-GRP-2025-00012
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),

    dict(name="Program", prefix="EDU-PRG", pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=5),
    dict(name="Course", prefix="EDU-CRS", pattern="{PREFIX}-{SEQ}", scope="COMPANY", reset_policy="NEVER", padding=5),

    # ─────────────────────────────────────────
    # Education attendance / operations
    # ─────────────────────────────────────────
    dict(
        name="Student Attendance",
        prefix="EDU-ATT",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. EDU-ATT-2025-00001
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),

    # ─────────────────────────────────────────
    # Enrollments (requested)
    # Format NOT like EDU-ENR-2025-00135 → use EDU-ENR/2025/00135
    # COMPANY scope keeps enrollment codes unique across branches.
    # ─────────────────────────────────────────
    dict(
        name="Program Enrollment",
        prefix="ENR",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. ENR-2025-00075
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Course Enrollment",
        prefix="CE",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. CE-2026-01091
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),

    # ─────────────────────────────────────────
    # Fees
    # ─────────────────────────────────────────
    dict(
        name="Fee Structure",
        prefix="EDU-FST",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. EDU-FST-2025-00050
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Fee Schedule",
        prefix="EDU-FSH",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. EDU-FSH-2025-00050
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Fees",
        prefix="EDU-FEE",
        pattern="{PREFIX}-{YYYY}-{SEQ}",  # e.g. EDU-FEE-2025-00012
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),

    # ─────────────────────────────────────────
    # Exams / Assessment (only if these doctypes have code fields)
    # ─────────────────────────────────────────
    dict(
        name="Assessment Event",
        prefix="EDU-EXM",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Assessment Mark",
        prefix="EDU-MRK",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Student Annual Result",
        prefix="EDU-RES",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
    dict(
        name="Grade Recalc Job",
        prefix="EDU-GRJ",
        pattern="{PREFIX}-{YYYY}-{SEQ}",
        scope="COMPANY",
        reset_policy="YEARLY",
        padding=5,
    ),
]
