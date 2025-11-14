
# app/application_reports/scripts/accounts_payable_detail.py

from __future__ import annotations
import time
from typing import Dict, Any, List, Optional
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.security.rbac_effective import AffiliationContext

_FMT = "%d-%m-%Y"
def _fmt(d: date | datetime | None) -> Optional[str]:
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
    def dat(name, label, w=150): return {"fieldname": name, "label": label, "fieldtype": "Data", "width": w}
    def dte(name, label, w=110): return {"fieldname": name, "label": label, "fieldtype": "Date", "width": w}
    return [
        dte("posting_date","Posting Date"),
        dte("due_date","Due Date"),
        dat("branch","Branch",140),
        dat("supplier","Supplier",160),
        dat("supplier_group","Supplier Group",140),
        dat("payable_account","Payable Account",160),
        dat("voucher_type","Voucher Type",140),
        dat("voucher_no","Voucher No",150),
        cur("invoiced_amount","Invoiced Amount"),
        cur("paid_amount","Paid Amount"),
        cur("debit_note","Debit Note"),
        cur("advance_amount","Advance"),
        cur("outstanding_amount","Outstanding"),
        cur("age_0_30","0-30",100),
        cur("age_31_60","31-60",100),
        cur("age_61_90","61-90",100),
        cur("age_91_120","91-120",100),
        cur("age_121_above","121+",100),
        dat("remarks","Remarks",220),
    ]

class AccountsPayableDetailReport:
    @classmethod
    def get_filters(cls): return get_filters()
    @classmethod
    def get_columns(cls, f=None): return get_columns(f)

    def execute(self, filters: Dict[str, Any], session: Session, _context: AffiliationContext) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if not filters.get("company"):
            raise ValueError("Company is required.")

        company_id = int(filters["company"])
        as_on = parse_date_flex(filters.get("report_date")) or date.today()
        ageing_based_on = (filters.get("ageing_based_on") or "Due Date").strip()
        use_due = ageing_based_on.lower().startswith("due")

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

        # Effective PI resolution: direct -> JE source -> regex code in JE remarks
        sql = f"""
        WITH pi_dt AS (
          SELECT id FROM document_types WHERE code = 'PURCHASE_INVOICE' LIMIT 1
        ),
        src AS (
          SELECT
            gle.id,
            gle.posting_date::date                         AS posting_date,
            (gle.credit - gle.debit)                       AS amt,
            COALESCE(gle.branch_id, je.branch_id)          AS branch_id,
            br.name                                        AS branch_name,
            gle.party_id                                   AS supplier_id,
            p.name                                         AS supplier_name,
            ''                                             AS supplier_group,
            je.id                                          AS je_id,
            je.code                                        AS je_code,
            je.remarks                                     AS je_remarks,
            COALESCE(gle.source_doctype_id, je.source_doctype_id) AS src_dt_id,
            COALESCE(gle.source_doc_id,    je.source_doc_id)      AS src_doc_id,
            (SELECT m[1] FROM regexp_matches(COALESCE(je.remarks,''), '(PINV-[0-9]{{4}}-[0-9]{{5}})') AS m LIMIT 1) AS pinv_code_regex,
            dt.code                                        AS raw_voucher_type,
            acc.name                                       AS payable_account
          FROM general_ledger_entries gle
          JOIN journal_entries je   ON je.id  = gle.journal_entry_id
          LEFT JOIN document_types dt ON dt.id = COALESCE(gle.source_doctype_id, je.source_doctype_id)
          LEFT JOIN parties p        ON p.id   = gle.party_id
          LEFT JOIN branches br      ON br.id  = COALESCE(gle.branch_id, je.branch_id)
          LEFT JOIN accounts acc     ON acc.id = gle.account_id
          WHERE {" AND ".join(where_bits)} AND je.doc_status::text NOT IN ('DRAFT','CANCELLED')
        ),
        resolved AS (
          SELECT
            s.*,
            -- try: direct PI via src_doc_id + src_dt_id
            pi_direct.id   AS pi_id_direct,
            pi_direct.code AS pi_code_direct,
            pi_direct.is_return AS pi_is_return_direct,
            pi_direct.due_date::date AS pi_due_direct,
            pi_direct.remarks AS pi_remarks_direct,
            -- try: JE source link references a PI
            CASE WHEN s.src_dt_id = (SELECT id FROM pi_dt) THEN pi_src.id END   AS pi_id_src,
            CASE WHEN s.src_dt_id = (SELECT id FROM pi_dt) THEN pi_src.code END AS pi_code_src,
            CASE WHEN s.src_dt_id = (SELECT id FROM pi_dt) THEN pi_src.is_return END AS pi_is_return_src,
            CASE WHEN s.src_dt_id = (SELECT id FROM pi_dt) THEN pi_src.due_date::date END AS pi_due_src,
            CASE WHEN s.src_dt_id = (SELECT id FROM pi_dt) THEN pi_src.remarks END AS pi_remarks_src,
            -- try: regex PINV-* inside JE remarks
            pi_rx.id      AS pi_id_rx,
            pi_rx.code    AS pi_code_rx,
            pi_rx.is_return AS pi_is_return_rx,
            pi_rx.due_date::date AS pi_due_rx,
            pi_rx.remarks AS pi_remarks_rx
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
            -- choose the effective PI in priority order
            COALESCE(r.pi_id_direct, r.pi_id_src, r.pi_id_rx)            AS eff_pi_id,
            COALESCE(r.pi_code_direct, r.pi_code_src, r.pi_code_rx)      AS eff_pi_code,
            COALESCE(r.pi_is_return_direct, r.pi_is_return_src, r.pi_is_return_rx) AS eff_pi_is_return,
            COALESCE(r.pi_due_direct, r.pi_due_src, r.pi_due_rx)         AS eff_pi_due,
            COALESCE(r.pi_remarks_direct, r.pi_remarks_src, r.pi_remarks_rx) AS eff_pi_remarks
          FROM resolved r
        )
        SELECT
          e.id,
          e.posting_date,
          e.amt,
          e.branch_name,
          e.payable_account,
          e.supplier_id,
          e.supplier_name,
          e.supplier_group,
          e.raw_voucher_type,
          e.je_code,
          e.je_remarks,
          e.eff_pi_code,
          e.eff_pi_is_return,
          e.eff_pi_due,
          e.eff_pi_remarks
        FROM eff e
        ORDER BY e.supplier_name, e.posting_date, e.id
        """

        rows = session.execute(text(sql), params).mappings().all()

        out: List[Dict[str, Any]] = []
        total_out = 0.0

        for r in rows:
            if r["supplier_id"] is None:
                continue

            amt = float(r["amt"] or 0.0)
            posting_date = r["posting_date"]
            pi_code = r.get("eff_pi_code")
            pi_is_return = bool(r.get("eff_pi_is_return")) if r.get("eff_pi_is_return") is not None else False
            due_date = r.get("eff_pi_due")
            remarks = (r.get("eff_pi_remarks") or r.get("je_remarks") or "")[:500]

            if pi_code:
                vt = "PURCHASE_RETURN" if pi_is_return else "PURCHASE_INVOICE"
                vno = pi_code                        # <-- always PINV-* when a PI exists
            else:
                vt = (r.get("raw_voucher_type") or "").upper()
                vno = r.get("je_code")

            # split amounts by semantic type
            invoiced = debit_note = paid = 0.0
            if vt in ("PURCHASE_INVOICE", "PURCHASE_RETURN"):
                if amt > 0: invoiced = amt
                elif amt < 0: debit_note = abs(amt)
            else:
                if amt < 0: paid = abs(amt)

            # only invoice/return contributes outstanding
            outstanding = invoiced  # never add positive from non-invoice lines
            total_out += outstanding

            base_date = (due_date if (use_due and due_date) else posting_date)
            b0 = b1 = b2 = b3 = b4 = 0.0
            if outstanding > 0 and base_date:
                days = (as_on - base_date).days
                if   days <= r1: b0 = outstanding
                elif days <= r2: b1 = outstanding
                elif days <= r3: b2 = outstanding
                elif days <= r4: b3 = outstanding
                else:            b4 = outstanding

            out.append({
                "posting_date": _fmt(posting_date),
                "due_date": _fmt(due_date if pi_code else None),
                "branch": r.get("branch_name") or "",
                "supplier": r.get("supplier_name") or "",
                "supplier_group": r.get("supplier_group") or "",
                "payable_account": r.get("payable_account") or "",
                "voucher_type": vt.replace("_"," ").title(),
                "voucher_no": vno,
                "invoiced_amount": round(invoiced, 2),
                "paid_amount": round(paid, 2),
                "debit_note": round(debit_note, 2),
                "advance_amount": 0.0,  # per-line detail: advances are summarized elsewhere if needed
                "outstanding_amount": round(outstanding, 2),
                "age_0_30": round(b0, 2),
                "age_31_60": round(b1, 2),
                "age_61_90": round(b2, 2),
                "age_91_120": round(b3, 2),
                "age_121_above": round(b4, 2),
                "remarks": remarks,
            })

        exec_time = time.perf_counter() - t0
        return {
            "columns": get_columns(filters),
            "data": out,
            "filters": filters,
            "summary": {
                "total_rows": len(out),
                "total_outstanding": round(total_out, 2),
            },
            "chart": None,
            "success": True,
            "total_count": len(out),
            "execution_time": exec_time,
            "report_name": "Accounts Payable",
        }
