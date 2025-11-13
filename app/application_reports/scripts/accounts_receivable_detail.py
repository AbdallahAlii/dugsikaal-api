#
# # app/application_reports/scripts/accounts_receivable_detail.py

from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
from datetime import date, datetime

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext
from app.application_reports.core.engine import ColumnDefinition
from app.application_reports.core.columns import company_filter

# ✅ use your helper (adjust path if needed)
try:
    from app.common.date_utils import parse_date_flex, format_date_out  # your helper module
except Exception:
    # Fallbacks (kept tiny; same behaviour as your helper)
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

    def format_date_out(d: date | datetime | None) -> Optional[str]:
        if d is None:
            return None
        if isinstance(d, datetime):
            d = d.date()
        return d.strftime(DISPLAY_FMT)

log = logging.getLogger(__name__)


def _to_date(v) -> date:
    """Use flexible parser; default to today if not provided."""
    d = parse_date_flex(v)
    return d or date.today()


def _detail_columns() -> List[ColumnDefinition]:
    def currency(field, label, width=120):
        return {"fieldname": field, "label": label, "fieldtype": "Currency", "width": width, "align": "right", "precision": 2}
    def data(field, label, width=140):
        return {"fieldname": field, "label": label, "fieldtype": "Data", "width": width}
    def datecol(field, label, width=110):
        return {"fieldname": field, "label": label, "fieldtype": "Date", "width": width}

    return [
        datecol("posting_date", "Posting Date"),
        data("customer", "Customer"),
        data("receivable_account", "Receivable Account", 160),
        data("voucher_type", "Voucher Type", 120),
        data("voucher_no", "Voucher No", 150),
        currency("invoiced_amount", "Invoiced Amount"),
        currency("paid_amount", "Paid Amount"),
        currency("credit_note", "Credit Note"),
        currency("outstanding_amount", "Outstanding"),
        currency("age_0_30", "0-30"),
        currency("age_31_60", "31-60"),
        currency("age_61_90", "61-90"),
        currency("age_91_120", "91-120"),
        currency("age_121_above", "121+"),
    ]


class AccountsReceivableDetailReport:
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
        return _detail_columns()

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        if not filters.get("company"):
            raise ValueError("Company is required.")

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

        log.info("▶ AR Detail start: company=%s as_on=%s ageing=%s customer=%s",
                 company_id, as_on.isoformat(), ageing_based_on, customer_filter_val or "-")

        # Doctype id for SI (allocations)
        si_dt_row = session.execute(text(
            "SELECT id FROM document_types WHERE code = 'SALES_INVOICE' LIMIT 1"
        )).first()
        si_dt_id = si_dt_row[0] if si_dt_row else None
        if not si_dt_id:
            log.warning("⚠ SALES_INVOICE doctype not found; allocations per invoice will show as 0.")

        # 1) Base invoice rows (posted, non-returns)
        inv_rows = session.execute(
            text(f"""
                SELECT
                    si.id,
                    si.code AS voucher_no,
                    si.posting_date::date AS posting_date,
                    p.name AS customer,
                    acc.code AS receivable_account,
                    COALESCE((CASE WHEN :use_due = TRUE THEN si.due_date::date ELSE NULL END), si.posting_date::date) AS base_date,
                    si.total_amount::numeric(18,6) AS total_amount,
                    si.paid_amount::numeric(18,6)  AS paid_on_invoice
                FROM sales_invoices si
                JOIN parties  p   ON p.id  = si.customer_id
                JOIN accounts acc ON acc.id = si.debit_to_account_id
                WHERE si.company_id = :company
                  AND si.is_return = FALSE
                  AND si.doc_status NOT IN ('DRAFT','CANCELLED')
                  AND si.posting_date::date <= :as_on
                  {customer_clause}
                ORDER BY p.name, si.posting_date, si.code
            """),
            {"company": company_id, "as_on": as_on, "use_due": bool(use_due_date), "customer_name": customer_filter_val}
        ).mappings().all()
        inv_ids = [r["id"] for r in inv_rows]
        log.debug("• detail invoices: count=%d total=%0.2f",
                  len(inv_rows), sum(float(r["total_amount"] or 0) for r in inv_rows))

        # 2) Allocations per invoice
        alloc_per_invoice: Dict[int, float] = {}
        if si_dt_id:
            rows = session.execute(
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
            alloc_per_invoice = {r["invoice_id"]: float(r["allocated"] or 0) for r in rows}
        log.debug("• detail allocations: invoices=%d sum=%0.2f",
                  len(alloc_per_invoice), sum(alloc_per_invoice.values()))

        # 3) Credit notes per invoice (returns). Count as positive credits.
        credit_per_invoice: Dict[int, float] = {}
        if inv_ids:
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
        log.debug("• detail credits: invoices=%d sum=%0.2f",
                  len(credit_per_invoice), sum(credit_per_invoice.values()))

        # 4) Rows (only invoices with outstanding > 0)
        out_rows: List[Dict[str, Any]] = []
        for inv in inv_rows:
            inv_id = inv["id"]
            total = float(inv["total_amount"] or 0)
            paid_on_inv = float(inv["paid_on_invoice"] or 0)
            alloc = float(alloc_per_invoice.get(inv_id, 0.0))
            credit = float(credit_per_invoice.get(inv_id, 0.0))
            outstanding = max(total - paid_on_inv - alloc - credit, 0.0)

            b0 = b1 = b2 = b3 = b4 = 0.0
            base_date = inv["base_date"]
            if outstanding > 0 and base_date is not None:
                days = (as_on - base_date).days
                if   days <= r1: b0 = outstanding
                elif days <= r2: b1 = outstanding
                elif days <= r3: b2 = outstanding
                elif days <= r4: b3 = outstanding
                else:            b4 = outstanding

            if outstanding > 0:
                out_rows.append({
                    # ✅ ERP-style date format
                    "posting_date": format_date_out(inv["posting_date"]),
                    "customer": inv["customer"],
                    "receivable_account": inv["receivable_account"],
                    "voucher_type": "SALES_INVOICE",
                    "voucher_no": inv["voucher_no"],
                    "invoiced_amount": round(total, 2),
                    "paid_amount": round(paid_on_inv + alloc, 2),
                    "credit_note": round(credit, 2),
                    "outstanding_amount": round(outstanding, 2),
                    "age_0_30": round(b0, 2),
                    "age_31_60": round(b1, 2),
                    "age_61_90": round(b2, 2),
                    "age_91_120": round(b3, 2),
                    "age_121_above": round(b4, 2),
                })

        log.info("✔ AR Detail done: invoices_with_outstanding=%d total_outstanding=%0.2f",
                 len(out_rows), sum(r["outstanding_amount"] for r in out_rows))

        return {
            "columns": self.get_columns(filters),
            "data": out_rows,
            "filters": filters,
            "summary": {
                "total_invoices": len(out_rows),
                "total_outstanding": round(sum(r["outstanding_amount"] for r in out_rows), 2)
            }
        }
