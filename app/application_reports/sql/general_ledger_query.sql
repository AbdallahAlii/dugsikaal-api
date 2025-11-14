/* -----------------------------------------------------------------------------
 General Ledger (ERP-style, Frappe-like)
 - Works for all entries (customers, suppliers, banks, stock, etc.)
 - Voucher-first mode: if :voucher_no is passed, ignores date window
 - Otherwise uses date window with safe defaults (last 90 days)
 - Returns:
     posting_date (DD-MM-YYYY), account/code+name, debit, credit, running_balance,
     voucher_type (human), voucher_no, against_account,
     party_type (Title-case), party_id/name, cost_center, branch, remarks
------------------------------------------------------------------------------*/

WITH
-- 1) Resolve the base rows either by voucher_no or by date window
base AS (
  SELECT
    gle.id,
    gle.company_id,
    gle.posting_date::date                                 AS posting_date,
    gle.debit::numeric(18,6)                               AS debit,
    gle.credit::numeric(18,6)                              AS credit,
    (gle.debit - gle.credit)                               AS amount,
    gle.account_id,
    gle.journal_entry_id,
    gle.party_type,
    gle.party_id,
    gle.cost_center_id,
    COALESCE(gle.branch_id, je.branch_id)                  AS branch_id,
    COALESCE(gle.source_doctype_id, je.source_doctype_id)  AS src_doctype_id,
    COALESCE(gle.source_doc_id,    je.source_doc_id)       AS src_doc_id,
    je.entry_type::text                                    AS je_type,
    je.code                                                AS je_code,
    je.remarks                                             AS je_remarks
  FROM general_ledger_entries gle
  JOIN journal_entries je ON je.id = gle.journal_entry_id
  WHERE gle.company_id = :company
    AND je.doc_status <> 'CANCELLED'
    AND (
      -- Voucher-first: when voucher_no is provided, ignore dates entirely
      (:voucher_no IS NOT NULL AND (
         je.code = :voucher_no
         OR EXISTS (
            SELECT 1
            FROM document_types dtx
            WHERE dtx.id = COALESCE(gle.source_doctype_id, je.source_doctype_id)
              AND (
                (dtx.code = 'PURCHASE_INVOICE'     AND EXISTS (SELECT 1 FROM purchase_invoices      x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'SALES_INVOICE'        AND EXISTS (SELECT 1 FROM sales_invoices         x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'PURCHASE_RECEIPT'     AND EXISTS (SELECT 1 FROM purchase_receipts      x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'SALES_DELIVERY_NOTE'  AND EXISTS (SELECT 1 FROM sales_delivery_notes   x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'STOCK_ENTRY'          AND EXISTS (SELECT 1 FROM stock_entries          x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'STOCK_RECONCILIATION' AND EXISTS (SELECT 1 FROM stock_reconciliations  x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'PAYMENT_ENTRY'        AND EXISTS (SELECT 1 FROM payment_entries        x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'EXPENSE'              AND EXISTS (SELECT 1 FROM expenses               x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no)) OR
                (dtx.code = 'LANDED_COST_VOUCHER'  AND EXISTS (SELECT 1 FROM landed_cost_vouchers   x WHERE x.id = COALESCE(gle.source_doc_id, je.source_doc_id) AND x.code = :voucher_no))
              )
         )
      ))
      -- Date-window path (no voucher_no)
      OR (:voucher_no IS NULL AND
         gle.posting_date >= COALESCE(:from_date, CURRENT_DATE - INTERVAL '90 days') AND
         gle.posting_date <= COALESCE(:to_date,   CURRENT_DATE)
      )
    )
    -- Additional filters (Frappe-style)
    AND (:account      IS NULL OR EXISTS (SELECT 1 FROM accounts a0 WHERE a0.id = gle.account_id AND a0.code = :account))
    AND (:party_type   IS NULL OR UPPER(gle.party_type::text) = UPPER(:party_type))
    AND (:party        IS NULL OR gle.party_id = :party)
    AND (:cost_center  IS NULL OR gle.cost_center_id IN (SELECT id FROM cost_centers WHERE name = :cost_center))
    AND (:branch_id    IS NULL OR COALESCE(gle.branch_id, je.branch_id) = :branch_id)
),

-- 2) Lookups & voucher resolution (prefer source doc; else JE)
look AS (
  SELECT
    b.*,
    acc.code  AS account_code,
    acc.name  AS account_name,
    p.name    AS party_name,
    cc.name   AS cost_center_name,
    br.name   AS branch_name,
    dt.code   AS src_doctype_code,
    dt.label  AS src_doctype_label,

    -- Voucher code (source first, else JE code)
    COALESCE(
      CASE dt.code
        WHEN 'PURCHASE_RECEIPT'     THEN (SELECT pr.code  FROM purchase_receipts     pr  WHERE pr.id = b.src_doc_id)
        WHEN 'PURCHASE_INVOICE'     THEN (SELECT pi.code  FROM purchase_invoices     pi  WHERE pi.id = b.src_doc_id)
        WHEN 'SALES_INVOICE'        THEN (SELECT si.code  FROM sales_invoices        si  WHERE si.id = b.src_doc_id)
        WHEN 'SALES_DELIVERY_NOTE'  THEN (SELECT sdn.code FROM sales_delivery_notes  sdn WHERE sdn.id = b.src_doc_id)
        WHEN 'STOCK_ENTRY'          THEN (SELECT se.code  FROM stock_entries         se  WHERE se.id = b.src_doc_id)
        WHEN 'STOCK_RECONCILIATION' THEN (SELECT sr.code  FROM stock_reconciliations sr  WHERE sr.id = b.src_doc_id)
        WHEN 'PAYMENT_ENTRY'        THEN (SELECT pe.code  FROM payment_entries       pe  WHERE pe.id = b.src_doc_id)
        WHEN 'EXPENSE'              THEN (SELECT ex.code  FROM expenses              ex  WHERE ex.id = b.src_doc_id)
        WHEN 'LANDED_COST_VOUCHER'  THEN (SELECT lcv.code FROM landed_cost_vouchers  lcv WHERE lcv.id = b.src_doc_id)
        ELSE NULL
      END,
      b.je_code
    ) AS voucher_code,

    -- Human voucher type:
    -- 1) source document label if present
    -- 2) otherwise prettified JE entry type (EXPENSE_CLAIM -> "Expense Claim")
    COALESCE(dt.label, replace(initcap(lower(b.je_type)), '_', ' ')) AS voucher_type_human

  FROM base b
  JOIN accounts      acc ON acc.id = b.account_id
  LEFT JOIN parties  p   ON p.id   = b.party_id
  LEFT JOIN cost_centers cc ON cc.id = b.cost_center_id
  LEFT JOIN branches br ON br.id = b.branch_id
  LEFT JOIN document_types dt ON dt.id = b.src_doctype_id
),

-- 3) Against account(s) within the same voucher/JE
against AS (
  SELECT
    l.id AS gle_id,
    (
      SELECT string_agg(DISTINCT a2.code, ', ' ORDER BY a2.code)
      FROM general_ledger_entries g2
      JOIN accounts a2 ON a2.id = g2.account_id
      WHERE g2.journal_entry_id = l.journal_entry_id
        AND g2.id <> l.id
    ) AS against_account
  FROM look l
),

-- 4) Opening totals for the chosen window (optional, not unioned here)
opening AS (
  SELECT
    SUM(CASE WHEN b.posting_date < COALESCE(:from_date, CURRENT_DATE - INTERVAL '90 days') THEN b.debit  ELSE 0 END)::numeric(18,6) AS opening_debit,
    SUM(CASE WHEN b.posting_date < COALESCE(:from_date, CURRENT_DATE - INTERVAL '90 days') THEN b.credit ELSE 0 END)::numeric(18,6) AS opening_credit
  FROM base b
),

-- 5) Period totals (useful for UI)
period_totals AS (
  SELECT
    SUM(b.debit)::numeric(18,6)  AS period_debit,
    SUM(b.credit)::numeric(18,6) AS period_credit
  FROM base b
)

SELECT
  -- Date formatted like your Payables (DD-MM-YYYY)
  to_char(l.posting_date, 'DD-MM-YYYY')            AS "posting_date",

  l.account_code                                   AS "account",
  l.account_name                                   AS "account_name",

  l.debit                                          AS "debit",
  l.credit                                         AS "credit",

  -- Running balance per account (classic ERP view)
  SUM(l.amount) OVER (
    PARTITION BY l.account_id
    ORDER BY l.posting_date, l.id
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  )::numeric(18,6)                                 AS "running_balance",

  l.voucher_type_human                             AS "voucher_type",
  l.voucher_code                                   AS "voucher_no",

  ag.against_account                               AS "against_account",

  -- Party type prettified: 'CUSTOMER' -> 'Customer', etc.
  initcap(lower(l.party_type::text))               AS "party_type",
  l.party_id                                       AS "party_id",
  l.party_name                                     AS "party_name",

  COALESCE(l.cost_center_name, '')                 AS "cost_center",
  COALESCE(l.branch_name, '')                      AS "branch_name",

  l.je_remarks                                     AS "remarks"
FROM look l
LEFT JOIN against ag ON ag.gle_id = l.id
ORDER BY l.posting_date, l.id
