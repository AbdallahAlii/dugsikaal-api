
# app/application_reports/scripts/accounts_payable.py

from __future__ import annotations
from typing import Dict, Any, List, Optional, DefaultDict
from collections import defaultdict
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.security.rbac_effective import AffiliationContext

_FMT = "%d-%m-%Y"
def _fmt(d: date | datetime | None):
    if d is None: return None
    if isinstance(d, datetime): d = d.date()
    return d.strftime(_FMT)

try:
    from app.common.date_utils import parse_date_flex
except Exception:
    def parse_date_flex(v):
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

def get_filters():
    return [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "required": True},
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

def get_columns(_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    def cur(name, label, w=120): return {"fieldname": name, "label": label, "fieldtype": "Currency", "align":"right","precision":2,"width":w}
    def dat(name, label, w=160): return {"fieldname": name, "label": label, "fieldtype": "Data", "width": w}
    return [
        dat("supplier","Supplier",200),
        dat("supplier_group","Supplier Group",140),
        cur("total_invoiced","Total Invoiced"),
        cur("total_paid","Total Paid"),
        cur("total_debit_note","Debit Note"),
        cur("advance_amount","Advance"),
        cur("outstanding_amount","Outstanding"),
        cur("age_0_30","0-30",100),
        cur("age_31_60","31-60",100),
        cur("age_61_90","61-90",100),
        cur("age_91_120","91-120",100),
        cur("age_121_above","121+",100),
    ]

class AccountsPayableReport:
    @classmethod
    def get_filters(cls): return get_filters()
    @classmethod
    def get_columns(cls, f=None): return get_columns(f)

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        if not filters.get("company"):
            raise ValueError("Company is required.")

        company_id = int(filters["company"])
        as_on = parse_date_flex(filters.get("report_date")) or date.today()
        use_due = (filters.get("ageing_based_on") or "Due Date").strip().lower().startswith("due")

        r1 = int(filters.get("range1", 30))
        r2 = int(filters.get("range2", 60))
        r3 = int(filters.get("range3", 90))
        r4 = int(filters.get("range4", 120))
        supplier_name = (filters.get("supplier") or "").strip() or None
        branch_name = (filters.get("branch") or "").strip() or None

        where_bits = [
            "gle.company_id = :company",
            "gle.posting_date <= :as_on",
            "UPPER(gle.party_type::text) = 'SUPPLIER'",
            "gle.party_id IS NOT NULL"
        ]
        params: Dict[str, Any] = {"company": company_id, "as_on": as_on}
        if supplier_name:
            where_bits.append("p.name = :supplier_name"); params["supplier_name"] = supplier_name
        if branch_name:
            where_bits.append("br.name = :branch_name"); params["branch_name"] = branch_name

        sql = f"""
        WITH pi_dt AS (
          SELECT id FROM document_types WHERE code = 'PURCHASE_INVOICE' LIMIT 1
        ),
        src AS (
          SELECT
            gle.id,
            gle.party_id                             AS supplier_id,
            p.name                                   AS supplier_name,
            ''                                       AS supplier_group,
            gle.posting_date::date                   AS posting_date,
            (gle.credit - gle.debit)                 AS amt,
            COALESCE(gle.source_doctype_id, je.source_doctype_id) AS src_dt_id,
            COALESCE(gle.source_doc_id,    je.source_doc_id)      AS src_doc_id,
            dt.code                                  AS raw_voucher_type,
            je.remarks                               AS je_remarks,
            (SELECT m[1] FROM regexp_matches(COALESCE(je.remarks,''), '(PINV-[0-9]{{4}}-[0-9]{{5}})') AS m LIMIT 1) AS pinv_code_regex
          FROM general_ledger_entries gle
          JOIN journal_entries je ON je.id = gle.journal_entry_id
          LEFT JOIN document_types dt ON dt.id = COALESCE(gle.source_doctype_id, je.source_doctype_id)
          LEFT JOIN parties p ON p.id = gle.party_id
          LEFT JOIN branches br ON br.id = COALESCE(gle.branch_id, je.branch_id)
          WHERE {" AND ".join(where_bits)} AND je.doc_status::text NOT IN ('DRAFT','CANCELLED')
        ),
        resolved AS (
          SELECT
            s.*,
            pi_direct.id   AS pi_id_direct,
            pi_direct.code AS pi_code_direct,
            pi_direct.is_return AS pi_is_return_direct,
            pi_direct.due_date::date AS pi_due_direct,
            pi_src.id      AS pi_id_src,
            pi_src.code    AS pi_code_src,
            pi_src.is_return AS pi_is_return_src,
            pi_src.due_date::date AS pi_due_src,
            pi_rx.id       AS pi_id_rx,
            pi_rx.code     AS pi_code_rx,
            pi_rx.is_return AS pi_is_return_rx,
            pi_rx.due_date::date AS pi_due_rx
          FROM src s
          LEFT JOIN purchase_invoices pi_direct
            ON pi_direct.id = s.src_doc_id AND s.src_dt_id = (SELECT id FROM pi_dt)
          LEFT JOIN purchase_invoices pi_src
            ON pi_src.id = s.src_doc_id
          LEFT JOIN purchase_invoices pi_rx
            ON (s.pinv_code_regex IS NOT NULL AND pi_rx.code = s.pinv_code_regex AND pi_rx.company_id = :company)
        ),
        eff AS (
          SELECT
            r.*,
            COALESCE(r.pi_id_direct, r.pi_id_src, r.pi_id_rx)            AS eff_pi_id,
            COALESCE(r.pi_code_direct, r.pi_code_src, r.pi_code_rx)      AS eff_pi_code,
            COALESCE(r.pi_is_return_direct, r.pi_is_return_src, r.pi_is_return_rx) AS eff_pi_is_return,
            COALESCE(r.pi_due_direct, r.pi_due_src, r.pi_due_rx)         AS eff_pi_due
          FROM resolved r
        )
        SELECT
          e.supplier_id,
          e.supplier_name,
          e.supplier_group,
          e.posting_date,
          e.amt,
          CASE
            WHEN e.eff_pi_id IS NOT NULL THEN
              CASE WHEN e.eff_pi_is_return THEN 'PURCHASE_RETURN' ELSE 'PURCHASE_INVOICE' END
            ELSE UPPER(e.raw_voucher_type)
          END AS eff_voucher_type,
          e.eff_pi_due AS due_date
        FROM eff e
        ORDER BY e.supplier_name, e.posting_date, e.supplier_id, e.amt
        """

        rows = session.execute(text(sql), params).mappings().all()

        totals: DefaultDict[int, Dict[str, float]] = defaultdict(lambda: {
            "invoiced": 0.0, "paid": 0.0, "debit_note": 0.0, "out": 0.0
        })
        buckets: DefaultDict[int, Dict[str, float]] = defaultdict(lambda: {
            "b0": 0.0, "b1": 0.0, "b2": 0.0, "b3": 0.0, "b4": 0.0
        })
        names: Dict[int, Dict[str, Any]] = {}

        for r in rows:
            sid = int(r["supplier_id"] or 0)
            if not sid: continue
            names[sid] = {"supplier_name": r["supplier_name"] or f"Supplier {sid}", "supplier_group": r.get("supplier_group") or ""}
            amt = float(r["amt"] or 0.0)
            vt = (r["eff_voucher_type"] or "")

            if vt in ("PURCHASE_INVOICE","PURCHASE_RETURN"):
                if amt > 0: totals[sid]["invoiced"] += amt
                elif amt < 0: totals[sid]["debit_note"] += abs(amt)
            else:
                if amt < 0: totals[sid]["paid"] += abs(amt)

            # only invoices/returns add to outstanding
            if vt in ("PURCHASE_INVOICE","PURCHASE_RETURN") and amt > 0:
                totals[sid]["out"] += amt

                # ageing
                base_date = r.get("due_date") if (use_due and r.get("due_date")) else r["posting_date"]
                if base_date:
                    days = (as_on - base_date).days
                    if   days <= r1: buckets[sid]["b0"] += amt
                    elif days <= r2: buckets[sid]["b1"] += amt
                    elif days <= r3: buckets[sid]["b2"] += amt
                    elif days <= r4: buckets[sid]["b3"] += amt
                    else:            buckets[sid]["b4"] += amt

        # advances (unallocated)
        adv_rows = session.execute(text("""
            SELECT pe.party_id AS supplier_id, SUM(pe.unallocated_amount)::numeric(18,6) AS adv
            FROM payment_entries pe
            WHERE pe.company_id = :company
              AND pe.doc_status::text = 'SUBMITTED'
              AND pe.payment_type = 'PAY'
              AND pe.party_type  = 'SUPPLIER'
              AND pe.posting_date <= :as_on
            GROUP BY pe.party_id
        """), {"company": company_id, "as_on": as_on}).mappings().all()
        adv = {int(r["supplier_id"]): float(r["adv"] or 0.0) for r in adv_rows}

        out: List[Dict[str, Any]] = []
        for sid, t in totals.items():
            meta = names.get(sid, {"supplier_name": f"Supplier {sid}", "supplier_group": ""})
            b = buckets.get(sid, {"b0":0,"b1":0,"b2":0,"b3":0,"b4":0})
            out.append({
                "supplier": meta["supplier_name"],
                "supplier_group": meta["supplier_group"],
                "total_invoiced": round(t["invoiced"],2),
                "total_paid": round(t["paid"],2),
                "total_debit_note": round(t["debit_note"],2),
                "advance_amount": round(adv.get(sid,0.0),2),
                "outstanding_amount": round(max(t["out"],0.0),2),
                "age_0_30": round(b["b0"],2),
                "age_31_60": round(b["b1"],2),
                "age_61_90": round(b["b2"],2),
                "age_91_120": round(b["b3"],2),
                "age_121_above": round(b["b4"],2),
            })

        return {
            "columns": get_columns(filters),
            "data": out,
            "filters": filters,
            "summary": {
                "total_suppliers": len(out),
                "total_payable": round(sum(r["outstanding_amount"] for r in out), 2),
            },
            "chart": None,
        }
