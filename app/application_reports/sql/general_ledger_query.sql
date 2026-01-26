/* =============================================================================
   General Ledger (ERPNext-style)
   - Always filters by company (multi-tenant safe)
   - Wide defaults handled in Python (recommended patch below)
   - Voucher resolution supports JE.code OR Source Doc code (Sales/Purchase/Payment/etc)
   - Running balance = opening + cumulative (debit - credit) per account
   - Optional: hide opening entries but still include them in opening balance
   ============================================================================ */

WITH params AS (
  SELECT
    :company::bigint                                          AS company_id,
    COALESCE(:from_date::date, CURRENT_DATE - INTERVAL '365 days')::date AS from_date,
    COALESCE(:to_date::date,   CURRENT_DATE)::date            AS to_date,
    NULLIF(BTRIM(:voucher_no::text), '')                      AS voucher_no,

    :account_id::bigint                                       AS account_id,
    :party_id::bigint                                         AS party_id,
    NULLIF(BTRIM(:party_type::text), '')                      AS party_type,
    :cost_center_id::bigint                                   AS cost_center_id,
    :branch_id::bigint                                        AS branch_id,

    COALESCE(:show_opening_entries::boolean, false)           AS show_opening_entries,
    COALESCE(:include_opening_row::boolean, true)             AS include_opening_row
),

base AS (
  SELECT
    gle.id,
    gle.company_id,
    gle.branch_id,
    gle.posting_date::date AS posting_date,
    gle.account_id,
    acc.code               AS account_code,
    acc.name               AS account_name,

    gle.debit::numeric(18,6)  AS debit,
    gle.credit::numeric(18,6) AS credit,
    (gle.debit - gle.credit)::numeric(18,6) AS net_amount,

    gle.party_type,
    gle.party_id,
    pty.name               AS party_name,

    gle.cost_center_id,
    cc.name                AS cost_center_name,

    gle.journal_entry_id,
    je.code                AS journal_entry_code,
    je.remarks             AS remarks,
    je.entry_type          AS je_entry_type,
    UPPER(COALESCE(je.doc_status::text, '')) AS je_doc_status,

    COALESCE(gle.source_doctype_id, je.source_doctype_id) AS source_doctype_id,
    COALESCE(gle.source_doc_id,     je.source_doc_id)     AS source_doc_id,

    dt.code  AS source_doctype_code,
    dt.label AS source_doctype_label,

    -- Resolve voucher code from source docs (fast: FK on id)
    COALESCE(
      si.code,
      pi.code,
      pe.code,
      ex.code,
      pr.code,
      sdn.code,
      je.code
    ) AS voucher_code,

    -- Detect "opening" entry (treat JE.entry_type=OPENING as opening)
    (UPPER(COALESCE(je.entry_type::text, '')) = 'OPENING') AS is_opening
  FROM general_ledger_entries gle
  JOIN journal_entries je
    ON je.id = gle.journal_entry_id
   AND je.company_id = gle.company_id
  JOIN accounts acc
    ON acc.id = gle.account_id
  LEFT JOIN document_types dt
    ON dt.id = COALESCE(gle.source_doctype_id, je.source_doctype_id)

  -- source docs (only one will match due to dt.code condition)
  LEFT JOIN sales_invoices si
    ON dt.code = 'SALES_INVOICE' AND si.id = COALESCE(gle.source_doc_id, je.source_doc_id)
  LEFT JOIN purchase_invoices pi
    ON dt.code = 'PURCHASE_INVOICE' AND pi.id = COALESCE(gle.source_doc_id, je.source_doc_id)
  LEFT JOIN payment_entries pe
    ON dt.code = 'PAYMENT_ENTRY' AND pe.id = COALESCE(gle.source_doc_id, je.source_doc_id)
  LEFT JOIN expenses ex
    ON dt.code = 'EXPENSE' AND ex.id = COALESCE(gle.source_doc_id, je.source_doc_id)
  LEFT JOIN purchase_receipts pr
    ON dt.code = 'PURCHASE_RECEIPT' AND pr.id = COALESCE(gle.source_doc_id, je.source_doc_id)
  LEFT JOIN sales_delivery_notes sdn
    ON dt.code = 'SALES_DELIVERY_NOTE' AND sdn.id = COALESCE(gle.source_doc_id, je.source_doc_id)

  LEFT JOIN parties pty
    ON pty.id = gle.party_id
  LEFT JOIN cost_centers cc
    ON cc.id = gle.cost_center_id
  -- branches table join is optional; keep if you have it
  -- LEFT JOIN branches br ON br.id = gle.branch_id

  CROSS JOIN params p
  WHERE gle.company_id = p.company_id
    AND UPPER(COALESCE(je.doc_status::text, '')) = 'SUBMITTED'
    -- keep report bounded by to_date (ERP-style)
    AND gle.posting_date::date <= p.to_date

    -- optional dimension filters
    AND (p.account_id IS NULL OR gle.account_id = p.account_id)
    AND (p.party_id IS NULL OR gle.party_id = p.party_id)
    AND (p.party_type IS NULL OR UPPER(COALESCE(gle.party_type::text,'')) = UPPER(p.party_type))
    AND (p.cost_center_id IS NULL OR gle.cost_center_id = p.cost_center_id)
    AND (p.branch_id IS NULL OR gle.branch_id = p.branch_id)

    -- voucher filter: match JE.code OR resolved voucher_code
    AND (
      p.voucher_no IS NULL
      OR UPPER(je.code) = UPPER(p.voucher_no)
      OR UPPER(COALESCE(
            si.code, pi.code, pe.code, ex.code, pr.code, sdn.code, je.code
          )) = UPPER(p.voucher_no)
    )
),

opening_by_account AS (
  -- Opening balance should include:
  -- 1) everything before from_date
  -- 2) plus "opening entries" (JE.entry_type=OPENING) if user chooses to hide them
  SELECT
    b.account_id,
    SUM(b.net_amount)::numeric(18,6) AS opening_amount
  FROM base b
  CROSS JOIN params p
  WHERE
    b.posting_date < p.from_date
    OR (b.is_opening = true AND p.show_opening_entries = false)
  GROUP BY b.account_id
),

display_rows AS (
  SELECT b.*
  FROM base b
  CROSS JOIN params p
  WHERE
    -- If voucher_no is provided, show all rows for that voucher regardless of from_date.
    -- Otherwise show only date-range.
    (
      p.voucher_no IS NOT NULL
      OR (b.posting_date BETWEEN p.from_date AND p.to_date)
    )
    -- Hide opening entries if requested (but they still affect opening_by_account)
    AND (p.show_opening_entries = true OR b.is_opening = false)
),

against_accounts AS (
  SELECT
    dr.journal_entry_id,
    ARRAY_AGG(DISTINCT dr.account_code) AS all_codes
  FROM display_rows dr
  GROUP BY dr.journal_entry_id
),

final_rows AS (
  SELECT
    dr.posting_date,
    dr.account_code,
    dr.account_name,
    dr.debit,
    dr.credit,

    COALESCE(oba.opening_amount, 0)
    + SUM(dr.net_amount) OVER (
        PARTITION BY dr.account_id
        ORDER BY dr.posting_date, dr.id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ) AS running_balance,

    COALESCE(dr.source_doctype_label, 'Journal Entry') AS voucher_type,
    dr.voucher_code AS voucher_no,

    CASE
      WHEN array_length(array_remove(aa.all_codes, dr.account_code), 1) > 3 THEN 'Multiple'
      ELSE array_to_string(array_remove(aa.all_codes, dr.account_code), ', ')
    END AS against_account,

    dr.party_type,
    dr.party_id,
    dr.party_name,
    dr.cost_center_name AS cost_center,
    dr.branch_id        AS branch_id,
    dr.remarks,

    'ROW'::text AS row_type
  FROM display_rows dr
  LEFT JOIN opening_by_account oba ON oba.account_id = dr.account_id
  LEFT JOIN against_accounts aa    ON aa.journal_entry_id = dr.journal_entry_id
)

-- Optional: emit a physical Opening row ONLY when a single account is filtered
SELECT *
FROM final_rows

UNION ALL

SELECT
  p.from_date AS posting_date,
  acc.code    AS account_code,
  acc.name    AS account_name,
  0::numeric(18,6) AS debit,
  0::numeric(18,6) AS credit,
  COALESCE(oba.opening_amount, 0)::numeric(18,6) AS running_balance,
  'Opening'::text AS voucher_type,
  'Opening'::text AS voucher_no,
  ''::text        AS against_account,
  NULL::text      AS party_type,
  NULL::bigint    AS party_id,
  NULL::text      AS party_name,
  NULL::text      AS cost_center,
  NULL::bigint    AS branch_id,
  NULL::text      AS remarks,
  'OPENING'::text AS row_type
FROM params p
JOIN accounts acc ON acc.id = p.account_id
LEFT JOIN opening_by_account oba ON oba.account_id = p.account_id
WHERE p.include_opening_row = true
  AND p.account_id IS NOT NULL

ORDER BY posting_date, row_type DESC, account_code, voucher_no, account_name;
