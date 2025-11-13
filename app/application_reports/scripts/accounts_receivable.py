#
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
from app.application_reports.core.columns import ACCOUNTS_RECEIVABLE_COLUMNS, company_filter

# ✅ use your helper (adjust path if needed)
try:
    from app.common.date_utils import parse_date_flex, format_date_out  # format_date_out not used here, but ok to import
except Exception:
    # Fallbacks (kept tiny; consistent with detail file)
    DISPLAY_FMT = "%m/%d/%Y"

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
    """Use flexible parser; default to today if not provided."""
    d = parse_date_flex(v)
    return d or date.today()


class AccountsReceivableReport:
    @classmethod
    def get_filters(cls):
        return [
            company_filter(),
            {"fieldname": "report_date", "label": "As On Date", "fieldtype": "Date",
             "default": date.today().isoformat(), "required": True},
            {"fieldname": "ageing_based_on", "label": "Ageing Based On", "fieldtype": "Select",
             "options": "Due Date\nPosting Date", "default": "Due Date"},
            {"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer"},
            {"fieldname": "range1", "label": "Range 1 (Days)", "fieldtype": "Int", "default": 30},
            {"fieldname": "range2", "label": "Range 2 (Days)", "fieldtype": "Int", "default": 60},
            {"fieldname": "range3", "label": "Range 3 (Days)", "fieldtype": "Int", "default": 90},
            {"fieldname": "range4", "label": "Range 4 (Days)", "fieldtype": "Int", "default": 120},
        ]

    @classmethod
    def get_columns(cls, _filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        return ACCOUNTS_RECEIVABLE_COLUMNS

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

        customer_filter_val = (filters.get("customer") or "").strip() or None
        customer_clause = "AND p.name = :customer_name" if customer_filter_val else ""

        log.info("▶ AR Summary start: company=%s as_on=%s ageing=%s ranges=%s/%s/%s/%s customer=%s",
                 company_id, as_on.isoformat(), ageing_based_on, r1, r2, r3, r4, customer_filter_val or "-")

        # Resolve Sales Invoice doctype id (for allocations)
        si_dt_row = session.execute(text(
            "SELECT id FROM document_types WHERE code = 'SALES_INVOICE' LIMIT 1"
        )).first()
        si_dt_id = si_dt_row[0] if si_dt_row else None
        if not si_dt_id:
            log.warning("⚠ SALES_INVOICE doctype not found; allocations per invoice will show as 0.")

        # 1) Pull posted (non-draft, non-cancelled) invoices up to as_on
        inv_sql = f"""
            SELECT
                si.id,
                si.customer_id,
                p.name AS customer_name,
                COALESCE((CASE WHEN :use_due = TRUE THEN si.due_date::date ELSE NULL END), si.posting_date::date) AS base_date,
                si.total_amount::numeric(18,6) AS total_amount,
                si.paid_amount::numeric(18,6)  AS paid_on_invoice
            FROM sales_invoices si
            JOIN parties p ON p.id = si.customer_id
            WHERE si.company_id = :company
              AND si.is_return = FALSE
              AND si.doc_status NOT IN ('DRAFT','CANCELLED')
              AND si.posting_date::date <= :as_on
              {customer_clause}
        """
        inv_rows = session.execute(
            text(inv_sql),
            {"company": company_id, "as_on": as_on, "use_due": bool(use_due_date), "customer_name": customer_filter_val}
        ).mappings().all()
        invoices: List[Dict[str, Any]] = list(inv_rows)
        log.debug("• invoices: count=%d total=%0.2f",
                  len(invoices), sum(float(r["total_amount"] or 0) for r in invoices))

        # 2) Allocations per invoice (RECEIVE / CUSTOMER)
        alloc_per_invoice: Dict[int, float] = {}
        if si_dt_id:
            alloc_rows = session.execute(
                text("""
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
                """),
                {"company": company_id, "as_on": as_on, "si_dt": si_dt_id}
            ).mappings().all()
            alloc_per_invoice = {r["invoice_id"]: float(r["allocated"] or 0) for r in alloc_rows}
        log.debug("• allocations: invoices=%d sum=%0.2f",
                  len(alloc_per_invoice), sum(alloc_per_invoice.values()))

        # 3) Credit notes per invoice (returns). Count as positive credit regardless of sign.
        cn_rows = session.execute(
            text("""
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
            """),
            {"company": company_id, "as_on": as_on}
        ).mappings().all()
        credit_per_invoice = {r["invoice_id"]: float(r["credit"] or 0) for r in cn_rows}
        log.debug("• credits: invoices=%d sum=%0.2f",
                  len(credit_per_invoice), sum(credit_per_invoice.values()))

        # 4) Build per-customer totals directly from invoices (invoice-driven; no G/L dependency)
        totals_by_customer: DefaultDict[int, Dict[str, float]] = defaultdict(
            lambda: {"total_invoiced": 0.0, "total_paid": 0.0, "total_credit": 0.0, "outstanding": 0.0}
        )
        buckets_by_customer: DefaultDict[int, Dict[str, float]] = defaultdict(
            lambda: {"range1": 0.0, "range2": 0.0, "range3": 0.0, "range4": 0.0}
        )
        name_by_customer: Dict[int, str] = {}

        for inv in invoices:
            inv_id = inv["id"]
            cust_id = inv["customer_id"]
            name_by_customer[cust_id] = inv["customer_name"]

            total = float(inv["total_amount"] or 0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0)
            alloc = float(alloc_per_invoice.get(inv_id, 0.0))
            cred = float(credit_per_invoice.get(inv_id, 0.0))
            outstanding = max(total - paid_on_inv - alloc - cred, 0.0)

            t = totals_by_customer[cust_id]
            t["total_invoiced"] += total
            t["total_paid"] += (paid_on_inv + alloc)
            t["total_credit"] += cred
            t["outstanding"] += outstanding

            base_date = inv["base_date"]
            if outstanding > 0 and base_date:
                days = (as_on - base_date).days
                if days <= r1:
                    buckets_by_customer[cust_id]["range1"] += outstanding
                elif days <= r2:
                    buckets_by_customer[cust_id]["range2"] += outstanding
                elif days <= r3:
                    buckets_by_customer[cust_id]["range3"] += outstanding
                else:
                    buckets_by_customer[cust_id]["range4"] += outstanding

        # 5) Advances (unallocated RECEIVE/CUSTOMER)
        adv_rows = session.execute(
            text("""
                SELECT
                    pe.party_id AS customer_id,
                    SUM(pe.unallocated_amount)::numeric(18,6) AS advance_amount
                FROM payment_entries pe
                WHERE pe.company_id = :company
                  AND pe.doc_status = 'SUBMITTED'
                  AND pe.payment_type = 'RECEIVE'
                  AND pe.party_type  = 'CUSTOMER'
                  AND pe.posting_date <= :as_on
                GROUP BY pe.party_id
            """),
            {"company": company_id, "as_on": as_on}
        ).mappings().all()
        advance_by_customer = {r["customer_id"]: float(r["advance_amount"] or 0) for r in adv_rows}
        log.debug("• advances: customers=%d sum=%0.2f",
                  len(advance_by_customer), sum(advance_by_customer.values()))

        # Ensure names for advance-only customers
        need_names = [cid for cid in advance_by_customer.keys() if cid not in name_by_customer]
        if need_names:
            name_rows = session.execute(
                text("SELECT id, name FROM parties WHERE id = ANY(:ids)"),
                {"ids": need_names}
            ).mappings().all()
            for r in name_rows:
                name_by_customer[r["id"]] = r["name"]

        # 6) Output rows (ERP-style: show customers with outstanding > 0 OR advance > 0)
        rows: List[Dict[str, Any]] = []
        customers = set(name_by_customer.keys()) | set(advance_by_customer.keys())
        for cust_id in sorted(customers, key=lambda x: name_by_customer.get(x, "")):
            t = totals_by_customer.get(cust_id, {})
            b = buckets_by_customer.get(cust_id, {"range1": 0.0, "range2": 0.0, "range3": 0.0, "range4": 0.0})
            adv = float(advance_by_customer.get(cust_id, 0.0))

            total_invoiced = float(t.get("total_invoiced", 0.0))
            total_paid = float(t.get("total_paid", 0.0))
            total_credit = float(t.get("total_credit", 0.0))
            outstanding = float(t.get("outstanding", 0.0))

            if outstanding == 0.0 and adv == 0.0:
                # skip fully settled customers with no advances (classic AR Summary behaviour)
                continue

            cname = name_by_customer.get(cust_id, f"Customer {cust_id}")
            rows.append({
                "customer": cname,
                "customer_name": cname,
                "total_invoiced": round(total_invoiced, 2),
                "total_paid": round(total_paid, 2),
                "total_credit_note": round(total_credit, 2),
                "outstanding_amount": round(outstanding, 2),
                "range1": round(b.get("range1", 0.0), 2),
                "range2": round(b.get("range2", 0.0), 2),
                "range3": round(b.get("range3", 0.0), 2),
                "range4": round(b.get("range4", 0.0), 2),
                "advance_amount": round(adv, 2),
            })

        log.info("✔ AR Summary done: rows=%d total_outstanding=%0.2f",
                 len(rows), sum(r["outstanding_amount"] for r in rows))

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
            "total_customers": len(rows),
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
            "title": "Accounts Receivable Ageing Analysis",
            "data": {
                "labels": [f"0-{r1_d}", f"{r1_d+1}-{r2_d}", f"{r2_d+1}-{r3_d}", f"{r3_d+1}+"],
                "datasets": [{"name": "Outstanding Amount", "values": [r1, r2, r3, r4]}]
            },
            "height": 300
        }
