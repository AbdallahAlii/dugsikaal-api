
# app/application_reports/scripts/accounts_payable_detail.py
from __future__ import annotations
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext
from app.common.date_utils import parse_date_flex  # parser only

log = logging.getLogger(__name__)

# ── UI filters & columns ──────────────────────────────────────────────────────
def get_filters():
    return [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
        {"fieldname": "report_date", "label": "As On Date", "fieldtype": "Date",
         "default": date.today().isoformat(), "required": True},
        {"fieldname": "ageing_based_on", "label": "Ageing Based On", "fieldtype": "Select",
         "options": "Due Date\nPosting Date", "default": "Due Date"},
        {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier"},
        {"fieldname": "supplier_id", "label": "Supplier ID", "fieldtype": "Int"},
        {"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "branch_id", "label": "Branch ID", "fieldtype": "Int"},
        {"fieldname": "range1", "label": "Range 1 (Days)", "fieldtype": "Int", "default": 30},
        {"fieldname": "range2", "label": "Range 2 (Days)", "fieldtype": "Int", "default": 60},
        {"fieldname": "range3", "label": "Range 3 (Days)", "fieldtype": "Int", "default": 90},
        {"fieldname": "range4", "label": "Range 4 (Days)", "fieldtype": "Int", "default": 120},
    ]

def get_columns(_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return [
        {"fieldname": "posting_date",      "label": "Posting Date",     "fieldtype": "Date",    "width": 110},
        {"fieldname": "due_date",          "label": "Due Date",         "fieldtype": "Date",    "width": 110},
        {"fieldname": "branch",            "label": "Branch",           "fieldtype": "Data",    "width": 140},
        {"fieldname": "supplier",          "label": "Supplier",         "fieldtype": "Data",    "width": 140},
        {"fieldname": "payable_account",   "label": "Payable Account",  "fieldtype": "Data",    "width": 160},
        {"fieldname": "voucher_type",      "label": "Voucher Type",     "fieldtype": "Data",    "width": 140},
        {"fieldname": "voucher_no",        "label": "Voucher No",       "fieldtype": "Data",    "width": 150},
        {"fieldname": "invoiced_amount",   "label": "Invoiced Amount",  "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "paid_amount",       "label": "Paid Amount",      "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "debit_note",        "label": "Debit Note",       "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "outstanding_amount","label": "Outstanding",      "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "age_0_30",          "label": "0-30",             "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "age_31_60",         "label": "31-60",            "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "age_61_90",         "label": "61-90",            "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "age_91_120",        "label": "91-120",           "fieldtype": "Currency","align":"right","precision":2,"width":120},
        {"fieldname": "age_121_above",     "label": "121+",             "fieldtype": "Currency","align":"right","precision":2,"width":120},
    ]

# ── Local dd-mm-YYYY formatter for row fields ────────────────────────────────
_DDMMYYYY = "%d-%m-%Y"
def _fmt(d: Optional[date | datetime]) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(_DDMMYYYY)

def _pretty_voucher_type(code: Optional[str]) -> str:
    return (code or "").replace("_", " ").title()

class AccountsPayableDetailReport:
    """
    Per-invoice AP with ageing.
    • Row dates are strings (dd-mm-YYYY) — never date/datetime.
    • SQL respects Ageing Based On (Due Date vs Posting Date) when filtering.
    • Extra logging for easy tracing.
    """

    @classmethod
    def get_filters(cls):
        return get_filters()

    @classmethod
    def get_columns(cls, _filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return get_columns(_filters)

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        t0 = time.perf_counter()

        if not filters.get("company"):
            raise ValueError("Company is required.")

        company_id: int = int(filters["company"])
        as_on: date = parse_date_flex(filters.get("report_date")) or date.today()
        ageing_based_on: str = (filters.get("ageing_based_on") or "Due Date").strip()
        use_due_date = ageing_based_on.lower().startswith("due")

        r1 = int(filters.get("range1", 30))
        r2 = int(filters.get("range2", 60))
        r3 = int(filters.get("range3", 90))
        r4 = int(filters.get("range4", 120))

        supplier_name = (filters.get("supplier") or "").strip() or None
        supplier_id = filters.get("supplier_id")
        branch_name = (filters.get("branch") or "").strip() or None
        branch_id = filters.get("branch_id")

        log.info(
            "[AP-D] START company=%s as_on=%s ageing=%s use_due=%s ranges=%s/%s/%s/%s supplier=%s supplier_id=%s branch=%s branch_id=%s",
            company_id, as_on.isoformat(), ageing_based_on, use_due_date, r1, r2, r3, r4,
            supplier_name or "-", supplier_id or "-", branch_name or "-", branch_id or "-"
        )

        # Resolve PURCHASE_INVOICE doctype id (for allocations)
        pi_dt_id: Optional[int] = None
        try:
            row = session.execute(text("SELECT id FROM document_types WHERE code = 'PURCHASE_INVOICE' LIMIT 1")).first()
            if row:
                pi_dt_id = int(row[0])
        except Exception:
            log.exception("[AP-D] doctype resolve failed")

        # Base invoices up to as_on using computed base-date
        where_bits = [
            "pi.company_id = :company",
            "pi.is_return = FALSE",
            "pi.doc_status NOT IN ('DRAFT','CANCELLED')",
            "COALESCE(CASE WHEN :use_due THEN pi.due_date::date END, pi.posting_date::date) <= :as_on",
        ]
        params: Dict[str, Any] = {"company": company_id, "as_on": as_on, "use_due": bool(use_due_date)}

        if supplier_id:
            where_bits.append("pi.supplier_id = :supplier_id")
            params["supplier_id"] = int(supplier_id)
        elif supplier_name:
            where_bits.append("p.name = :supplier_name")
            params["supplier_name"] = supplier_name

        if branch_id:
            where_bits.append("pi.branch_id = :branch_id")
            params["branch_id"] = int(branch_id)
        elif branch_name:
            where_bits.append("b.name = :branch_name")
            params["branch_name"] = branch_name

        inv_sql = f"""
            SELECT
                pi.id,
                pi.code AS voucher_no,
                pi.posting_date::date AS posting_date,
                pi.due_date::date     AS due_date,
                COALESCE(a.name, '')  AS payable_account,
                p.name                AS supplier_name,
                b.name                AS branch_name,
                pi.total_amount::numeric(18,6) AS total_amount,
                pi.paid_amount::numeric(18,6)  AS paid_on_invoice
            FROM purchase_invoices pi
            LEFT JOIN accounts a ON a.id = pi.payable_account_id
            LEFT JOIN branches b ON b.id = pi.branch_id
            JOIN parties p ON p.id = pi.supplier_id
            WHERE {" AND ".join(where_bits)}
            ORDER BY p.name, pi.posting_date, pi.id
        """
        log.debug("[AP-D] SQL:\n%s\nPARAMS=%s", inv_sql, params)

        invoices = list(session.execute(text(inv_sql), params).mappings().all())
        log.info("[AP-D] fetched invoices=%d", len(invoices))

        # Allocations
        alloc_per_invoice: Dict[int, float] = {}
        if pi_dt_id:
            try:
                alloc_rows = session.execute(
                    text("""
                        SELECT
                            it.source_doc_id AS invoice_id,
                            SUM(it.allocated_amount)::numeric(18,6) AS allocated
                        FROM payment_items it
                        JOIN payment_entries pe ON pe.id = it.payment_id
                        WHERE pe.company_id = :company
                          AND pe.doc_status = 'SUBMITTED'
                          AND pe.payment_type = 'PAY'
                          AND pe.party_type  = 'SUPPLIER'
                          AND pe.posting_date <= :as_on
                          AND it.source_doctype_id = :pi_dt
                        GROUP BY it.source_doc_id
                    """),
                    {"company": company_id, "as_on": as_on, "pi_dt": pi_dt_id}
                ).mappings().all()
                alloc_per_invoice = {int(r["invoice_id"]): float(r["allocated"] or 0) for r in alloc_rows}
            except Exception:
                log.exception("[AP-D] allocation scan failed")

        # Debit notes (returns)
        try:
            dn_rows = session.execute(
                text("""
                    SELECT
                        pi.return_against_id AS invoice_id,
                        SUM(CASE WHEN pi.total_amount < 0 THEN -pi.total_amount ELSE pi.total_amount END)::numeric(18,6) AS debit_note
                    FROM purchase_invoices pi
                    WHERE pi.company_id = :company
                      AND pi.is_return = TRUE
                      AND pi.doc_status NOT IN ('DRAFT','CANCELLED')
                      AND pi.posting_date::date <= :as_on
                      AND pi.return_against_id IS NOT NULL
                    GROUP BY pi.return_against_id
                """),
                {"company": company_id, "as_on": as_on}
            ).mappings().all()
            debitnote_per_invoice = {int(r["invoice_id"]): float(r["debit_note"] or 0) for r in dn_rows}
        except Exception:
            log.exception("[AP-D] debit note scan failed")
            debitnote_per_invoice = {}

        # Compose rows (dates as strings)
        rows: List[Dict[str, Any]] = []
        for inv in invoices:
            inv_id = int(inv["id"])
            posting_date_db: Optional[date] = inv["posting_date"]
            due_date_db: Optional[date] = inv["due_date"]
            base_date = (due_date_db if (use_due_date and due_date_db) else posting_date_db)

            total = float(inv["total_amount"] or 0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0)
            alloc = float(alloc_per_invoice.get(inv_id, 0.0))
            dn = float(debitnote_per_invoice.get(inv_id, 0.0))
            paid_amount = paid_on_inv + alloc
            outstanding = max(total - paid_amount - dn, 0.0)

            b0 = b1 = b2 = b3 = b4 = 0.0
            if outstanding > 0 and base_date:
                days = (as_on - base_date).days
                if   days <= r1: b0 = outstanding
                elif days <= r2: b1 = outstanding
                elif days <= r3: b2 = outstanding
                elif days <= r4: b3 = outstanding
                else:            b4 = outstanding

            rows.append({
                "posting_date": _fmt(posting_date_db),
                "due_date": _fmt(due_date_db),
                "branch": inv["branch_name"] or "",
                "supplier": inv["supplier_name"] or "",
                "payable_account": inv["payable_account"] or "",
                "voucher_type": _pretty_voucher_type("PURCHASE_INVOICE"),
                "voucher_no": inv["voucher_no"],
                "invoiced_amount": round(total, 2),
                "paid_amount": round(paid_amount, 2),
                "debit_note": round(dn, 2),
                "outstanding_amount": round(outstanding, 2),
                "age_0_30": round(b0, 2),
                "age_31_60": round(b1, 2),
                "age_61_90": round(b2, 2),
                "age_91_120": round(b3, 2),
                "age_121_above": round(b4, 2),
            })

        if rows:
            log.debug("[AP-D] sample row=%s", {k: rows[0][k] for k in ("posting_date", "due_date", "supplier", "voucher_no")})

        exec_time = time.perf_counter() - t0
        log.info("[AP-D] DONE rows=%d exec=%.4fs", len(rows), exec_time)

        return {
            "columns": get_columns(filters),
            "data": rows,
            "filters": filters,   # router will pretty-format filter dates separately
            "summary": {
                "total_invoices": len(rows),
                "total_outstanding": round(sum(r["outstanding_amount"] for r in rows), 2)
            },
            "chart": None,
            "success": True,
            "total_count": len(rows),
            "execution_time": exec_time,
            "report_name": "Accounts Payable",
        }
