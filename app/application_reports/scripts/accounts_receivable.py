# app/application_reports/scripts/accounts_receivable.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional, DefaultDict
from collections import defaultdict
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

def _to_date(v) -> date:
    d = _parse_date_flex(v)
    return d or date.today()

# ---------- UI schema ----------
def _currency(name: str, label: str, w: int = 120):
    return {"fieldname": name, "label": label, "fieldtype": "Currency", "align": "right", "precision": 2, "width": w}

def _data(name: str, label: str, w: int = 160):
    return {"fieldname": name, "label": label, "fieldtype": "Data", "width": w}

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
        _data("customer", "Customer", 220),
        _data("customer_group", "Customer Group", 140),   # keep for parity; fill "" if N/A
        _currency("total_invoiced", "Total Invoiced"),
        _currency("total_paid", "Total Paid"),
        _currency("total_credit_note", "Credit Notes"),
        _currency("advance_amount", "Advance"),
        _currency("outstanding_amount", "Outstanding"),
        _currency("age_0_30", "0-30", 100),
        _currency("age_31_60", "31-60", 100),
        _currency("age_61_90", "61-90", 100),
        _currency("age_91_120", "91-120", 100),
        _currency("age_121_above", "121+", 100),
    ]


class AccountsReceivableReport:
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

        # Resolve Sales Invoice doctype for allocations
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

        inv_sql = f"""
            SELECT
                si.id,
                si.customer_id,
                p.name AS customer_name,
                ''     AS customer_group,
                COALESCE((CASE WHEN :use_due = TRUE THEN si.due_date::date ELSE NULL END), si.posting_date::date) AS base_date,
                si.total_amount::numeric(18,6) AS total_amount,
                si.paid_amount::numeric(18,6)  AS paid_on_invoice
            FROM sales_invoices si
            JOIN parties  p  ON p.id  = si.customer_id
            JOIN branches br ON br.id = si.branch_id
            WHERE {" AND ".join(inv_where)}
        """
        inv_rows = session.execute(text(inv_sql), params).mappings().all()

        # Allocations per invoice (RECEIVE/CUSTOMER) via payment_items → SALES_INVOICE
        alloc_per_invoice: Dict[int, float] = {}
        if si_dt_id:
            alloc_rows = session.execute(text("""
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
            alloc_per_invoice = {r["invoice_id"]: float(r["allocated"] or 0.0) for r in alloc_rows}

        # Credit notes per invoice (returns)
        cn_rows = session.execute(text("""
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
        credit_per_invoice = {r["invoice_id"]: float(r["credit"] or 0.0) for r in cn_rows}

        totals: DefaultDict[int, Dict[str, float]] = defaultdict(lambda: {
            "invoiced": 0.0, "paid": 0.0, "credit": 0.0, "out": 0.0
        })
        buckets: DefaultDict[int, Dict[str, float]] = defaultdict(lambda: {
            "b0": 0.0, "b1": 0.0, "b2": 0.0, "b3": 0.0, "b4": 0.0
        })
        names: Dict[int, Dict[str, Any]] = {}

        for inv in inv_rows:
            iid = int(inv["id"])
            cid = int(inv["customer_id"])
            names[cid] = {"customer_name": inv["customer_name"], "customer_group": inv.get("customer_group") or ""}

            total = float(inv["total_amount"] or 0.0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0.0)
            alloc = float(alloc_per_invoice.get(iid, 0.0))
            credit = float(credit_per_invoice.get(iid, 0.0))
            outstanding = max(total - paid_on_inv - alloc - credit, 0.0)

            t = totals[cid]
            t["invoiced"] += total
            t["paid"] += (paid_on_inv + alloc)
            t["credit"] += credit
            t["out"] += outstanding

            base_date = inv["base_date"]
            if outstanding > 0 and base_date:
                days = (as_on - base_date).days
                if   days <= r1: buckets[cid]["b0"] += outstanding
                elif days <= r2: buckets[cid]["b1"] += outstanding
                elif days <= r3: buckets[cid]["b2"] += outstanding
                elif days <= r4: buckets[cid]["b3"] += outstanding
                else:            buckets[cid]["b4"] += outstanding

        # Advances: unallocated RECEIVE/CUSTOMER
        adv_rows = session.execute(text("""
            SELECT
                pe.party_id AS customer_id,
                SUM(pe.unallocated_amount)::numeric(18,6) AS adv
            FROM payment_entries pe
            WHERE pe.company_id = :company
              AND pe.doc_status = 'SUBMITTED'
              AND pe.payment_type = 'RECEIVE'
              AND pe.party_type  = 'CUSTOMER'
              AND pe.posting_date <= :as_on
            GROUP BY pe.party_id
        """), {"company": company_id, "as_on": as_on}).mappings().all()
        advances = {int(r["customer_id"]): float(r["adv"] or 0.0) for r in adv_rows}

        # Make sure names exist for advance-only customers
        missing_names = [cid for cid in advances.keys() if cid not in names]
        if missing_names:
            nm_rows = session.execute(text("SELECT id, name FROM parties WHERE id = ANY(:ids)"),
                                      {"ids": missing_names}).mappings().all()
            for r in nm_rows:
                names[int(r["id"])] = {"customer_name": r["name"], "customer_group": ""}

        out: List[Dict[str, Any]] = []
        customers = set(names.keys()) | set(advances.keys())
        for cid in sorted(customers, key=lambda i: names[i]["customer_name"]):
            meta = names[cid]
            t = totals.get(cid, {"invoiced":0,"paid":0,"credit":0,"out":0})
            b = buckets.get(cid, {"b0":0,"b1":0,"b2":0,"b3":0,"b4":0})
            adv = advances.get(cid, 0.0)

            # Skip totally cleared with no advance
            if t["out"] == 0 and adv == 0:
                continue

            out.append({
                "customer": meta["customer_name"],
                "customer_group": meta["customer_group"],
                "total_invoiced": round(t["invoiced"], 2),
                "total_paid": round(t["paid"], 2),
                "total_credit_note": round(t["credit"], 2),
                "advance_amount": round(adv, 2),
                "outstanding_amount": round(t["out"], 2),
                "age_0_30": round(b["b0"], 2),
                "age_31_60": round(b["b1"], 2),
                "age_61_90": round(b["b2"], 2),
                "age_91_120": round(b["b3"], 2),
                "age_121_above": round(b["b4"], 2),
            })

        summary = {
            "total_customers": len(out),
            "total_outstanding": round(sum(r["outstanding_amount"] for r in out), 2),
            "total_advance": round(sum(r["advance_amount"] for r in out), 2),
        }
        chart = {
            "type": "bar",
            "title": "AR Ageing",
            "data": {
                "labels": [f"0-{r1}", f"{r1+1}-{r2}", f"{r2+1}-{r3}", f"{r3+1}+"],
                "datasets": [{
                    "name": "Outstanding",
                    "values": [
                        sum(r["age_0_30"] for r in out),
                        sum(r["age_31_60"] for r in out),
                        sum(r["age_61_90"] for r in out),
                        sum(r["age_91_120"] for r in out) + sum(r["age_121_above"] for r in out)  # combine tail if you like
                    ]
                }]
            },
            "height": 300
        }

        return {
            "columns": get_columns(filters),
            "data": out,
            "filters": filters,
            "summary": summary,
            "chart": chart,
            "ageing_ranges": {
                "range1": f"0-{r1} Days",
                "range2": f"{r1 + 1}-{r2} Days",
                "range3": f"{r2 + 1}-{r3} Days",
                "range4": f"{r3 + 1}+ Days"
            }
        }
