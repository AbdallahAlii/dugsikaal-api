# # app/application_reports/scripts/accounts_receivable.py
from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional, DefaultDict
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext
from app.application_reports.core.engine import ColumnDefinition
from app.application_reports.core.columns import ACCOUNTS_PAYABLE_COLUMNS, company_filter

# Flexible date parsing (same as AR)
try:
    from app.common.date_utils import parse_date_flex, format_date_out
except Exception:
    def parse_date_flex(v) -> Optional[date]:
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, str):
            s = v.strip()
            for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y"):
                try:
                    return datetime.strptime(s, fmt).date()
                except Exception:
                    pass
            try:
                return datetime.fromisoformat(s).date()
            except Exception:
                return None
        return None

log = logging.getLogger(__name__)

def _to_date(v) -> date:
    d = parse_date_flex(v)
    return d or date.today()


class AccountsPayableReport:
    @classmethod
    def get_filters(cls):
        return [
            company_filter(),
            {"fieldname": "report_date", "label": "As On Date", "fieldtype": "Date",
             "default": date.today().isoformat(), "required": True},
            {"fieldname": "ageing_based_on", "label": "Ageing Based On", "fieldtype": "Select",
             "options": "Due Date\nPosting Date", "default": "Due Date"},
            {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier"},
            {"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch"},
            {"fieldname": "range1", "label": "Range 1 (Days)", "fieldtype": "Int", "default": 30},
            {"fieldname": "range2", "label": "Range 2 (Days)", "fieldtype": "Int", "default": 60},
            {"fieldname": "range3", "label": "Range 3 (Days)", "fieldtype": "Int", "default": 90},
            {"fieldname": "range4", "label": "Range 4 (Days)", "fieldtype": "Int", "default": 120},
        ]

    @classmethod
    def get_columns(cls, _filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        return ACCOUNTS_PAYABLE_COLUMNS

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        self._validate(filters)

        company_id: int = int(filters["company"])
        as_on: date = _to_date(filters.get("report_date"))
        ageing_based_on: str = (filters.get("ageing_based_on") or "Due Date").strip()
        use_due_date = ageing_based_on.lower().startswith("due")

        r1 = int(filters.get("range1", 30))
        r2 = int(filters.get("range2", 60))
        r3 = int(filters.get("range3", 90))
        r4 = int(filters.get("range4", 120))

        supplier_filter_val = (filters.get("supplier") or "").strip() or None
        branch_filter_val = (filters.get("branch") or "").strip() or None

        supplier_clause = "AND p.name = :supplier_name" if supplier_filter_val else ""
        branch_join = "JOIN branches b ON b.id = pi.branch_id"
        branch_clause = "AND b.name = :branch_name" if branch_filter_val else ""

        log.info("▶ AP Summary start: company=%s as_on=%s ageing=%s ranges=%s/%s/%s/%s supplier=%s branch=%s",
                 company_id, as_on.isoformat(), ageing_based_on, r1, r2, r3, r4,
                 supplier_filter_val or "-", branch_filter_val or "-")

        # Resolve Purchase Invoice doctype id (for allocations)
        pi_dt_row = session.execute(text(
            "SELECT id FROM document_types WHERE code = 'PURCHASE_INVOICE' LIMIT 1"
        )).first()
        pi_dt_id = pi_dt_row[0] if pi_dt_row else None
        if not pi_dt_id:
            log.warning("⚠ PURCHASE_INVOICE doctype not found; allocations per invoice will show as 0.")

        # 1) Posted (non-draft, non-cancelled) PIs up to as_on
        inv_sql = f"""
            SELECT
                pi.id,
                pi.supplier_id,
                p.name AS supplier_name,
                COALESCE((CASE WHEN :use_due = TRUE THEN pi.due_date::date ELSE NULL END), pi.posting_date::date) AS base_date,
                pi.total_amount::numeric(18,6) AS total_amount,
                pi.paid_amount::numeric(18,6)  AS paid_on_invoice
            FROM purchase_invoices pi
            {branch_join}
            JOIN parties p ON p.id = pi.supplier_id
            WHERE pi.company_id = :company
              AND pi.is_return = FALSE
              AND pi.doc_status NOT IN ('DRAFT','CANCELLED')
              AND pi.posting_date::date <= :as_on
              {supplier_clause}
              {branch_clause}
        """
        inv_rows = session.execute(
            text(inv_sql),
            {
                "company": company_id,
                "as_on": as_on,
                "use_due": bool(use_due_date),
                "supplier_name": supplier_filter_val,
                "branch_name": branch_filter_val
            }
        ).mappings().all()
        invoices: List[Dict[str, Any]] = list(inv_rows)

        # 2) Allocations per invoice (PAY / SUPPLIER)  🔧 FIXED ENUM CASE
        alloc_rows = []
        if pi_dt_id:
            alloc_rows = session.execute(
                text("""
                    SELECT
                        pi.source_doc_id AS invoice_id,
                        SUM(pi.allocated_amount)::numeric(18,6) AS allocated
                    FROM payment_items pi
                    JOIN payment_entries pe ON pe.id = pi.payment_id
                    WHERE pe.company_id = :company
                      AND pe.doc_status = 'SUBMITTED'
                      AND pe.payment_type = 'PAY'
                      AND pe.party_type  = 'SUPPLIER'
                      AND pe.posting_date <= :as_on
                      AND pi.source_doctype_id = :pi_dt
                    GROUP BY pi.source_doc_id
                """),
                {"company": company_id, "as_on": as_on, "pi_dt": pi_dt_id}
            ).mappings().all()
        alloc_per_invoice = {r["invoice_id"]: float(r["allocated"] or 0) for r in alloc_rows}

        # 3) Debit Notes (returns) per invoice
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
        debitnote_per_invoice = {r["invoice_id"]: float(r["debit_note"] or 0) for r in dn_rows}

        # 4) Totals & ageing per supplier
        totals_by_supplier: DefaultDict[int, Dict[str, float]] = defaultdict(
            lambda: {"total_invoiced": 0.0, "total_paid": 0.0, "total_debit_note": 0.0, "outstanding": 0.0}
        )
        buckets_by_supplier: DefaultDict[int, Dict[str, float]] = defaultdict(
            lambda: {"range1": 0.0, "range2": 0.0, "range3": 0.0, "range4": 0.0}
        )
        name_by_supplier: Dict[int, str] = {}

        for inv in invoices:
            inv_id = inv["id"]
            sup_id = inv["supplier_id"]
            name_by_supplier[sup_id] = inv["supplier_name"]

            total = float(inv["total_amount"] or 0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0)
            alloc = float(alloc_per_invoice.get(inv_id, 0.0))
            dn = float(debitnote_per_invoice.get(inv_id, 0.0))
            outstanding = max(total - paid_on_inv - alloc - dn, 0.0)

            t = totals_by_supplier[sup_id]
            t["total_invoiced"] += total
            t["total_paid"] += (paid_on_inv + alloc)
            t["total_debit_note"] += dn
            t["outstanding"] += outstanding

            base_date = inv["base_date"]
            if outstanding > 0 and base_date:
                days = (as_on - base_date).days
                if days <= r1: buckets_by_supplier[sup_id]["range1"] += outstanding
                elif days <= r2: buckets_by_supplier[sup_id]["range2"] += outstanding
                elif days <= r3: buckets_by_supplier[sup_id]["range3"] += outstanding
                else: buckets_by_supplier[sup_id]["range4"] += outstanding

        # 5) Advances (unallocated PAY/SUPPLIER)  🔧 FIXED ENUM CASE
        adv_rows = session.execute(
            text("""
                SELECT
                    pe.party_id AS supplier_id,
                    SUM(pe.unallocated_amount)::numeric(18,6) AS advance_amount
                FROM payment_entries pe
                WHERE pe.company_id = :company
                  AND pe.doc_status = 'SUBMITTED'
                  AND pe.payment_type = 'PAY'
                  AND pe.party_type  = 'SUPPLIER'
                  AND pe.posting_date <= :as_on
                GROUP BY pe.party_id
            """),
            {"company": company_id, "as_on": as_on}
        ).mappings().all()
        advance_by_supplier = {r["supplier_id"]: float(r["advance_amount"] or 0) for r in adv_rows}

        # Names for advance-only suppliers
        need_names = [sid for sid in advance_by_supplier.keys() if sid not in name_by_supplier]
        if need_names:
            for r in session.execute(
                text("SELECT id, name FROM parties WHERE id = ANY(:ids)"),
                {"ids": need_names}
            ).mappings():
                name_by_supplier[r["id"]] = r["name"]

        # 6) Output
        rows: List[Dict[str, Any]] = []
        suppliers = set(name_by_supplier.keys()) | set(advance_by_supplier.keys())
        for sup_id in sorted(suppliers, key=lambda x: name_by_supplier.get(x, "")):
            t = totals_by_supplier.get(sup_id, {})
            b = buckets_by_supplier.get(sup_id, {"range1": 0.0, "range2": 0.0, "range3": 0.0, "range4": 0.0})
            adv = float(advance_by_supplier.get(sup_id, 0.0))

            total_invoiced = float(t.get("total_invoiced", 0.0))
            total_paid = float(t.get("total_paid", 0.0))
            total_debit_note = float(t.get("total_debit_note", 0.0))
            outstanding = float(t.get("outstanding", 0.0))

            if outstanding == 0.0 and adv == 0.0:
                continue

            sname = name_by_supplier.get(sup_id, f"Supplier {sup_id}")
            rows.append({
                "supplier": sname,
                "supplier_name": sname,
                "total_invoiced": round(total_invoiced, 2),
                "total_paid": round(total_paid, 2),
                "total_debit_note": round(total_debit_note, 2),
                "outstanding_amount": round(outstanding, 2),
                "range1": round(b.get("range1", 0.0), 2),
                "range2": round(b.get("range2", 0.0), 2),
                "range3": round(b.get("range3", 0.0), 2),
                "range4": round(b.get("range4", 0.0), 2),
                "advance_amount": round(adv, 2),
            })

        summary = self._summary(rows)
        chart = self._chart(rows, r1, r2, r3)

        return {
            "columns": self.get_columns(filters),
            "data": rows,
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

    def _validate(self, filters: Dict[str, Any]) -> None:
        if not filters.get("company"):
            raise ValueError("Company is required.")
        if not filters.get("report_date"):
            filters["report_date"] = date.today()

    def _summary(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        tot_out = sum(r["outstanding_amount"] for r in rows)
        r1 = sum(r["range1"] for r in rows)
        r2 = sum(r["range2"] for r in rows)
        r3 = sum(r["range3"] for r in rows)
        r4 = sum(r["range4"] for r in rows)
        total_ageing = (r1 + r2 + r3 + r4) or 1.0
        return {
            "total_suppliers": len(rows),
            "total_outstanding": round(tot_out, 2),
            "total_range1": round(r1, 2),
            "total_range2": round(r2, 2),
            "total_range3": round(r3, 2),
            "total_range4": round(r4, 2),
            "pct_range1": round(100 * r1 / total_ageing, 1),
            "pct_range2": round(100 * r2 / total_ageing, 1),
            "pct_range3": round(100 * r3 / total_ageing, 1),
            "pct_range4": round(100 * r4 / total_ageing, 1),
        }

    def _chart(self, rows: List[Dict[str, Any]], r1_d: int, r2_d: int, r3_d: int) -> Dict[str, Any]:
        r1 = sum(r["range1"] for r in rows)
        r2 = sum(r["range2"] for r in rows)
        r3 = sum(r["range3"] for r in rows)
        r4 = sum(r["range4"] for r in rows)
        return {
            "type": "bar",
            "title": "Accounts Payable Ageing Analysis",
            "data": {
                "labels": [f"0-{r1_d}", f"{r1_d+1}-{r2_d}", f"{r2_d+1}-{r3_d}", f"{r3_d+1}+"],
                "datasets": [{"name": "Outstanding Amount", "values": [r1, r2, r3, r4]}]
            },
            "height": 300
        }
