/* =============================================================================
   Trial Balance (ERPNext-style, Query Report, SQLAlchemy-safe)
   - Bind style: :param (NO %(param)s)
   - No trailing semicolon (engine wraps SQL)
   - Roll-up: child accounts accumulate into parents
   - Source: general_ledger_entries + journal_entries (SUBMITTED only)
   ============================================================================ */

WITH
params AS (
  SELECT
    CAST(:company   AS bigint) AS company_id,
    CAST(:from_date AS date)   AS from_date,
    CAST(:to_date   AS date)   AS to_date,

    /* optional filters (keep in engine even if you don’t use them now) */
    CAST(:branch_id AS bigint) AS branch_id,

    COALESCE(CAST(:show_zero_values AS boolean), false) AS show_zero_values,
    COALESCE(CAST(:show_net_values  AS boolean), false) AS show_net_values
),

/* 1) Accounts tree (ERPNext style needs parent rollups) */
acct AS (
  SELECT
    a.id,
    a.parent_account_id,
    a.code,
    a.name AS account_name,
    a.root_type,
    a.report_type,
    COALESCE(a.is_group, false) AS is_group
  FROM accounts a
  JOIN params p ON p.company_id = a.company_id
),

/* A display ordering path (not required, but gives stable tree order) */
acct_tree AS (
  WITH RECURSIVE t AS (
    SELECT
      a.*,
      0 AS indent,
      LPAD(a.code, 20, '0') AS sort_path
    FROM acct a
    WHERE a.parent_account_id IS NULL

    UNION ALL

    SELECT
      c.*,
      t.indent + 1 AS indent,
      t.sort_path || '/' || LPAD(c.code, 20, '0') AS sort_path
    FROM acct c
    JOIN t ON c.parent_account_id = t.id
  )
  SELECT * FROM t
),

/* 2) Base GL rows (only submitted, not cancelled, bounded by to_date) */
gl_base AS (
  SELECT
    gle.account_id,
    gle.posting_date::date AS posting_date,
    COALESCE(gle.debit,  0)::numeric AS debit,
    COALESCE(gle.credit, 0)::numeric AS credit
  FROM general_ledger_entries gle
  JOIN journal_entries je
    ON je.id = gle.journal_entry_id
   AND je.company_id = gle.company_id
  JOIN params p
    ON p.company_id = gle.company_id
  WHERE
    COALESCE(gle.is_cancelled, false) = false
    AND UPPER(COALESCE(je.doc_status::text, '')) = 'SUBMITTED'
    AND gle.posting_date::date <= p.to_date
    AND (p.branch_id IS NULL OR gle.branch_id = p.branch_id)
),

/* 3) Sums per account (leaf-level) */
gl_sums AS (
  SELECT
    gb.account_id,

    SUM(CASE WHEN gb.posting_date <  p.from_date THEN gb.debit  ELSE 0 END) AS opening_debit,
    SUM(CASE WHEN gb.posting_date <  p.from_date THEN gb.credit ELSE 0 END) AS opening_credit,

    SUM(CASE WHEN gb.posting_date >= p.from_date AND gb.posting_date <= p.to_date THEN gb.debit  ELSE 0 END) AS debit,
    SUM(CASE WHEN gb.posting_date >= p.from_date AND gb.posting_date <= p.to_date THEN gb.credit ELSE 0 END) AS credit
  FROM gl_base gb
  JOIN params p ON TRUE
  GROUP BY gb.account_id
),

/* 4) Closure table: (ancestor -> descendant) for rollups */
acct_closure AS (
  SELECT
    t.id AS ancestor_id,
    t.id AS descendant_id
  FROM acct_tree t

  UNION ALL

  SELECT
    c.ancestor_id,
    t.id AS descendant_id
  FROM acct_closure c
  JOIN acct_tree t ON t.parent_account_id = c.descendant_id
),

/* 5) Roll up leaf sums into each ancestor */
rolled AS (
  SELECT
    c.ancestor_id AS account_id,

    COALESCE(SUM(s.opening_debit),  0) AS opening_debit,
    COALESCE(SUM(s.opening_credit), 0) AS opening_credit,
    COALESCE(SUM(s.debit),          0) AS debit,
    COALESCE(SUM(s.credit),         0) AS credit
  FROM acct_closure c
  LEFT JOIN gl_sums s ON s.account_id = c.descendant_id
  GROUP BY c.ancestor_id
),

/* 6) Compute closing + (optional) netting */
final_accounts AS (
  SELECT
    t.id,
    t.parent_account_id,
    t.code,
    t.account_name,
    t.root_type,
    t.report_type,
    t.is_group,
    t.indent,
    t.sort_path,

    r.opening_debit,
    r.opening_credit,
    r.debit,
    r.credit,

    (r.opening_debit  + r.debit)  AS closing_debit,
    (r.opening_credit + r.credit) AS closing_credit
  FROM acct_tree t
  LEFT JOIN rolled r ON r.account_id = t.id
),

final_view AS (
  SELECT
    fa.code AS account,
    fa.account_name,
    fa.parent_account_id,
    fa.indent,
    fa.is_group,
    fa.root_type,
    fa.report_type,

    /* show_net_values behaves like ERPNext: net Dr/Cr presentation */
    CASE WHEN p.show_net_values
      THEN GREATEST(fa.opening_debit - fa.opening_credit, 0)
      ELSE fa.opening_debit
    END AS opening_debit,

    CASE WHEN p.show_net_values
      THEN GREATEST(fa.opening_credit - fa.opening_debit, 0)
      ELSE fa.opening_credit
    END AS opening_credit,

    fa.debit,
    fa.credit,

    CASE WHEN p.show_net_values
      THEN GREATEST(fa.closing_debit - fa.closing_credit, 0)
      ELSE fa.closing_debit
    END AS closing_debit,

    CASE WHEN p.show_net_values
      THEN GREATEST(fa.closing_credit - fa.closing_debit, 0)
      ELSE fa.closing_credit
    END AS closing_credit,

    fa.sort_path
  FROM final_accounts fa
  JOIN params p ON TRUE
),

filtered AS (
  SELECT *
  FROM final_view v
  JOIN params p ON TRUE
  WHERE
    p.show_zero_values = true
    OR (
      COALESCE(v.opening_debit,0)  <> 0
      OR COALESCE(v.opening_credit,0) <> 0
      OR COALESCE(v.debit,0)       <> 0
      OR COALESCE(v.credit,0)      <> 0
      OR COALESCE(v.closing_debit,0)  <> 0
      OR COALESCE(v.closing_credit,0) <> 0
    )
)

SELECT
  account,
  account_name,
  parent_account_id,
  indent,
  is_group,
  root_type,
  report_type,
  opening_debit,
  opening_credit,
  debit,
  credit,
  closing_debit,
  closing_credit
FROM filtered
ORDER BY sort_path
