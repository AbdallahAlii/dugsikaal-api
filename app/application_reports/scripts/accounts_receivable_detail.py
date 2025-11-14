# app/application_reports/scripts/accounts_receivable_detail.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)

# ---------- date helpers (use your helper if available) ----------
_FMT = "%d-%m-%Y"
try:
    from app.common.date_utils import parse_date_flex as _parse_date_flex  # type: ignore
except Exception:
    def _parse_date_flex(v):
        if isinstance(v, date) and not isinstance(v, datetime): return v
        if isinstance(v, datetime): return v.date()
        if isinstance(v, str):
            s = v.strip()
            for fmt in ("%m/%d/%Y","%d/%m/%Y","%Y/%m/%d","%Y-%m-%d","%d-%m-%Y","%m-%d-%Y"):
                try: return datetime.strptime(s, fmt).date()
                except Exception: pass
            try: return datetime.fromisoformat(s).date()
            except Exception: return None
        return None

def _fmt(d: date | datetime | None) -> Optional[str]:
    if d is None: return None
    if isinstance(d, datetime): d = d.date()
    return d.strftime(_FMT)

def _to_date(v) -> date:
    d = _parse_date_flex(v)
    return d or date.today()

# ---------- UI schema ----------
def _currency(field, label, width=120):
    return {"fieldname": field, "label": label, "fieldtype": "Currency", "width": width, "align": "right", "precision": 2}
def _data(field, label, width=150):
    return {"fieldname": field, "label": label, "fieldtype": "Data", "width": width}
def _datecol(field, label, width=110):
    return {"fieldname": field, "label": label, "fieldtype": "Date", "width": width}

def get_filters():
    return [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
        {"fieldname": "report_date", "label": "As On Date", "fieldtype": "Date", "default": date.today().isoformat(), "required": True},
        {"fieldname": "ageing_based_on", "label": "Ageing Based On", "fieldtype": "Select",
         "options": "Due Date\nPosting Date", "default": "Due Date"},
        {"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer"},
        {"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
        {"fieldname": "range1", "label": "Range 1 (Days)", "fieldtype": "Int", "default": 30},
        {"fieldname": "range2", "label": "Range 2 (Days)", "fieldtype": "Int", "default": 60},
        {"fieldname": "range3", "label": "Range 3 (Days)", "fieldtype": "Int", "default": 90},
        {"fieldname": "range4", "label": "Range 4 (Days)", "fieldtype": "Int", "default": 120},
    ]

def get_columns(_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return [
        _datecol("posting_date","Posting Date"),
        _datecol("due_date","Due Date"),
        _data("branch","Branch",140),
        _data("customer","Customer",160),
        _data("receivable_account","Receivable Account",170),
        _data("cost_center","Cost Center",150),
        _data("voucher_type","Voucher Type",130),
        _data("voucher_no","Voucher No",150),
        _currency("invoiced_amount","Invoiced Amount"),
        _currency("paid_amount","Paid Amount"),
        _currency("credit_note","Credit Note"),
        _currency("advance_amount","Advance"),
        _currency("outstanding_amount","Outstanding"),
        _currency("age_0_30","0-30",100),
        _currency("age_31_60","31-60",100),
        _currency("age_61_90","61-90",100),
        _currency("age_91_120","91-120",100),
        _currency("age_121_above","121+",100),
        _data("remarks","Remarks",220),
    ]


class AccountsReceivableDetailReport:
    @classmethod
    def get_filters(cls): return get_filters()
    @classmethod
    def get_columns(cls, f=None): return get_columns(f)

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        if not filters.get("company"):
            raise ValueError("Company is required.")

        company_id: int = int(filters["company"])
        as_on: date = _to_date(filters.get("report_date"))
        use_due: bool = (filters.get("ageing_based_on") or "Due Date").strip().lower().startswith("due")

        r1 = int(filters.get("range1", 30))
        r2 = int(filters.get("range2", 60))
        r3 = int(filters.get("range3", 90))
        r4 = int(filters.get("range4", 120))

        customer_name = (filters.get("customer") or "").strip() or None
        branch_name = (filters.get("branch") or "").strip() or None

        # Doctype id for SI (allocations)
        si_dt_row = session.execute(text("SELECT id FROM document_types WHERE code = 'SALES_INVOICE' LIMIT 1")).first()
        si_dt_id = si_dt_row[0] if si_dt_row else None

        inv_where = [
            "si.company_id = :company",
            "si.is_return = FALSE",
            "si.doc_status NOT IN ('DRAFT','CANCELLED')",
            "si.posting_date::date <= :as_on"
        ]
        params = {"company": company_id, "as_on": as_on, "use_due": bool(use_due)}
        if customer_name:
            inv_where.append("p.name = :customer_name"); params["customer_name"] = customer_name
        if branch_name:
            inv_where.append("br.name = :branch_name"); params["branch_name"] = branch_name

        # Pick a representative cost center (first item CC) per invoice for display
        inv_sql = f"""
            SELECT
                si.id,
                si.code AS voucher_no,
                si.posting_date::date AS posting_date,
                p.name  AS customer,
                br.name AS branch,
                acc.code AS receivable_account,
                (SELECT cc.name
                   FROM sales_invoice_items sii
                   LEFT JOIN cost_centers cc ON cc.id = sii.cost_center_id
                  WHERE sii.invoice_id = si.id
                  ORDER BY sii.id ASC
                  LIMIT 1) AS cost_center,
                COALESCE((CASE WHEN :use_due = TRUE THEN si.due_date::date ELSE NULL END), si.posting_date::date) AS base_date,
                si.due_date::date AS due_date,
                si.total_amount::numeric(18,6) AS total_amount,
                si.paid_amount::numeric(18,6)  AS paid_on_invoice,
                COALESCE(si.remarks,'') AS remarks
            FROM sales_invoices si
            JOIN parties  p   ON p.id  = si.customer_id
            JOIN branches br  ON br.id = si.branch_id
            JOIN accounts acc ON acc.id = si.debit_to_account_id
            WHERE {" AND ".join(inv_where)}
            ORDER BY p.name, si.posting_date, si.code
        """
        inv_rows = session.execute(text(inv_sql), params).mappings().all()
        inv_ids = [r["id"] for r in inv_rows]

        # Allocations per invoice
        alloc_per_invoice: Dict[int, float] = {}
        if si_dt_id:
            a_rows = session.execute(text("""
                SELECT
                    pi.source_doc_id AS invoice_id,
                    SUM(pi.allocated_amount)::numeric(18,6) AS allocated
                FROM payment_items pi
                JOIN payment_entries pe ON pe.id = pi.payment_id
                WHERE pe.company_id = :company
                  AND pe.doc_status = 'SUBMITTED'
                  AND pe.payment_type = 'RECEIVE'
                  AND pe.party_type  = 'CUSTOMER'
                  AND pe.posting_date <= :as_on
                  AND pi.source_doctype_id = :si_dt
                GROUP BY pi.source_doc_id
            """), {"company": company_id, "as_on": as_on, "si_dt": si_dt_id}).mappings().all()
            alloc_per_invoice = {r["invoice_id"]: float(r["allocated"] or 0.0) for r in a_rows}

        # Credit notes per invoice
        credit_per_invoice: Dict[int, float] = {}
        if inv_ids:
            c_rows = session.execute(text("""
                SELECT
                    si.return_against_id AS invoice_id,
                    SUM(CASE WHEN si.total_amount < 0 THEN -si.total_amount ELSE si.total_amount END)::numeric(18,6) AS credit
                FROM sales_invoices si
                WHERE si.company_id = :company
                  AND si.is_return = TRUE
                  AND si.doc_status NOT IN ('DRAFT','CANCELLED')
                  AND si.posting_date::date <= :as_on
                  AND si.return_against_id IS NOT NULL
                GROUP BY si.return_against_id
            """), {"company": company_id, "as_on": as_on}).mappings().all()
            credit_per_invoice = {r["invoice_id"]: float(r["credit"] or 0.0) for r in c_rows}

        # Build detail rows (only invoices with outstanding > 0)
        rows: List[Dict[str, Any]] = []
        for inv in inv_rows:
            iid = inv["id"]
            total = float(inv["total_amount"] or 0.0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0.0)
            alloc = float(alloc_per_invoice.get(iid, 0.0))
            credit = float(credit_per_invoice.get(iid, 0.0))
            outstanding = max(total - paid_on_inv - alloc - credit, 0.0)

            if outstanding <= 0:
                continue

            base_date = inv["base_date"]
            b0 = b1 = b2 = b3 = b4 = 0.0
            if base_date:
                days = (as_on - base_date).days
                if   days <= r1: b0 = outstanding
                elif days <= r2: b1 = outstanding
                elif days <= r3: b2 = outstanding
                elif days <= r4: b3 = outstanding
                else:            b4 = outstanding

            rows.append({
                "posting_date": _fmt(inv["posting_date"]),
                "due_date": _fmt(inv["due_date"] if use_due else None),
                "branch": inv.get("branch") or "",
                "customer": inv.get("customer") or "",
                "receivable_account": inv.get("receivable_account") or "",
                "cost_center": inv.get("cost_center") or "",
                "voucher_type": "SALES INVOICE",
                "voucher_no": inv.get("voucher_no"),
                "invoiced_amount": round(total, 2),
                "paid_amount": round(paid_on_inv + alloc, 2),
                "credit_note": round(credit, 2),
                "advance_amount": 0.0,  # header-level advances are not per-invoice; shown in summary report
                "outstanding_amount": round(outstanding, 2),
                "age_0_30": round(b0, 2),
                "age_31_60": round(b1, 2),
                "age_61_90": round(b2, 2),
                "age_91_120": round(b3, 2),
                "age_121_above": round(b4, 2),
                "remarks": (inv.get("remarks") or "")[:500],
            })

        return {
            "columns": get_columns(filters),
            "data": rows,
            "filters": filters,
            "summary": {
                "total_invoices": len(rows),
                "total_outstanding": round(sum(r["outstanding_amount"] for r in rows), 2)
            },
            "chart": None
        }
