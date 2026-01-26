/* -----------------------------------------------------------------------------
 Stock Ledger (engine compatible)
 - Named binds use ":name"
 - Avoids "::type" casts (uses CAST)
 - Avoids ":" inside time formats (uses HH24MISS, opening time 000000)
 - Voucher-first if :voucher_no is provided, else date range + opening rows
------------------------------------------------------------------------------*/

WITH
params AS (
  SELECT
    CAST(:company AS bigint) AS company_id,

    NULLIF(CAST(:voucher_no AS text), '') AS voucher_no,

    CAST(:branch_id    AS bigint) AS branch_id,
    CAST(:item_id      AS bigint) AS item_id,
    CAST(:warehouse_id AS bigint) AS warehouse_id,

    NULLIF(CAST(:item_name AS text), '') AS item_name,
    NULLIF(CAST(:warehouse AS text), '') AS warehouse_name,

    COALESCE(CAST(:to_date AS date), CURRENT_DATE) AS to_date_eff,
    COALESCE(
      CAST(:from_date AS date),
      CAST((COALESCE(CAST(:to_date AS date), CURRENT_DATE) - INTERVAL '30 days') AS date)
    ) AS from_date_eff
),

/* 1) Scope SLE (cheap filters only; no date filter here so opening works) */
sle_scope AS (
  SELECT
    sle.id,
    sle.company_id,
    sle.branch_id,
    sle.item_id,
    sle.warehouse_id,

    sle.base_uom_id,
    sle.transaction_uom_id,
    sle.transaction_quantity,

    sle.posting_date,
    sle.posting_time,

    sle.actual_qty,
    sle.incoming_rate,
    sle.outgoing_rate,
    sle.valuation_rate,
    sle.stock_value_difference,
    sle.qty_after_transaction AS balance_qty,

    sle.doc_type_id,
    sle.doc_id,
    sle.stock_entry_id
  FROM stock_ledger_entries sle
  JOIN params p ON p.company_id = sle.company_id
  WHERE
    sle.is_cancelled = FALSE
    AND (p.branch_id    IS NULL OR sle.branch_id    = p.branch_id)
    AND (p.item_id      IS NULL OR sle.item_id      = p.item_id)
    AND (p.warehouse_id IS NULL OR sle.warehouse_id = p.warehouse_id)
),

/* 2) Enrich with master data + doctype */
sle_enriched AS (
  SELECT
    s.*,
    it.name AS item_name,
    wh.name AS warehouse_name,
    uom_base.name AS stock_uom_name,
    uom_trx.name  AS transaction_uom_name,
    br.name AS branch_name,
    dt.code  AS doctype_code,
    dt.label AS doctype_label
  FROM sle_scope s
  JOIN items it ON it.id = s.item_id
  JOIN warehouses wh ON wh.id = s.warehouse_id
  JOIN units_of_measure uom_base ON uom_base.id = s.base_uom_id
  LEFT JOIN units_of_measure uom_trx ON uom_trx.id = s.transaction_uom_id
  LEFT JOIN branches br ON br.id = s.branch_id
  LEFT JOIN document_types dt ON dt.id = s.doc_type_id
  JOIN params p ON TRUE
  WHERE
    (p.item_name IS NULL OR it.name = p.item_name)
    AND (p.warehouse_name IS NULL OR wh.name = p.warehouse_name)
),

/* 3) Voucher code mapping (join-based) */
sle_with_voucher AS (
  SELECT
    e.*,
    COALESCE(
      pr.code,
      sdn.code,
      se.code,
      sr.code,
      lcv.code,
      si.code,
      pin.code,
      se_fallback.code
    ) AS voucher_code
  FROM sle_enriched e

  LEFT JOIN purchase_receipts pr
    ON e.doctype_code = 'PURCHASE_RECEIPT' AND pr.id = e.doc_id

  LEFT JOIN sales_delivery_notes sdn
    ON e.doctype_code IN ('SALES_DELIVERY_NOTE', 'DELIVERY_NOTE') AND sdn.id = e.doc_id

  LEFT JOIN stock_entries se
    ON e.doctype_code = 'STOCK_ENTRY' AND se.id = e.doc_id

  LEFT JOIN stock_reconciliations sr
    ON e.doctype_code = 'STOCK_RECONCILIATION' AND sr.id = e.doc_id

  LEFT JOIN landed_cost_vouchers lcv
    ON e.doctype_code = 'LANDED_COST_VOUCHER' AND lcv.id = e.doc_id

  LEFT JOIN sales_invoices si
    ON e.doctype_code = 'SALES_INVOICE' AND si.id = e.doc_id

  LEFT JOIN purchase_invoices pin
    ON e.doctype_code = 'PURCHASE_INVOICE' AND pin.id = e.doc_id

  LEFT JOIN stock_entries se_fallback
    ON se_fallback.id = e.stock_entry_id
),

/* 4) Running balance value per item+warehouse */
sle_running AS (
  SELECT
    s.*,
    SUM(s.stock_value_difference) OVER (
      PARTITION BY s.company_id, s.item_id, s.warehouse_id
      ORDER BY s.posting_date, s.posting_time, s.id
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS balance_value
  FROM sle_with_voucher s
),

/* 5) Opening snapshot (latest row before from_date) */
opening_snapshot AS (
  SELECT DISTINCT ON (r.company_id, r.item_id, r.warehouse_id)
    r.company_id,
    r.branch_id,
    r.item_id,
    r.warehouse_id,
    r.item_name,
    r.warehouse_name,
    r.branch_name,
    r.stock_uom_name,
    r.balance_qty    AS opening_balance_qty,
    r.valuation_rate AS opening_valuation_rate,
    r.balance_value  AS opening_balance_value
  FROM sle_running r
  JOIN params p ON TRUE
  WHERE
    p.voucher_no IS NULL
    AND r.posting_date < p.from_date_eff
  ORDER BY
    r.company_id, r.item_id, r.warehouse_id,
    r.posting_date DESC, r.posting_time DESC, r.id DESC
),

/* 6) Transactions: voucher-first OR date range */
tx_rows AS (
  SELECT r.*
  FROM sle_running r
  JOIN params p ON TRUE
  WHERE
    (
      p.voucher_no IS NOT NULL
      AND r.voucher_code = p.voucher_no
    )
    OR
    (
      p.voucher_no IS NULL
      AND r.posting_date >= p.from_date_eff
      AND r.posting_date <= p.to_date_eff
    )
),

/* 7) Final rows */
final_rows AS (
  SELECT
    p.from_date_eff              AS posting_date,
    '000000'                     AS posting_time,

    o.item_name                  AS item_name,
    o.warehouse_name             AS warehouse,

    o.stock_uom_name             AS stock_uom,
    CAST(NULL AS text)           AS transaction_uom,
    CAST(NULL AS numeric)        AS transaction_qty,

    CAST(0 AS numeric)           AS in_qty,
    CAST(0 AS numeric)           AS out_qty,
    o.opening_balance_qty        AS balance_qty,

    CAST(NULL AS numeric)        AS incoming_rate,
    CAST(NULL AS numeric)        AS outgoing_rate,
    o.opening_valuation_rate     AS valuation_rate,

    CAST(0 AS numeric)           AS stock_value_difference,
    o.opening_balance_value      AS balance_value,

    'Opening'                    AS voucher_type,
    CAST('' AS text)             AS voucher_no,

    COALESCE(o.branch_name, '')  AS branch,
    CAST('' AS text)             AS remarks,

    0                            AS sort_rank,
    CAST(0 AS bigint)            AS sort_id
  FROM opening_snapshot o
  JOIN params p ON p.voucher_no IS NULL

  UNION ALL

  SELECT
    t.posting_date                                AS posting_date,
    to_char(t.posting_time, 'HH24MISS')           AS posting_time,

    t.item_name                                   AS item_name,
    t.warehouse_name                              AS warehouse,

    t.stock_uom_name                              AS stock_uom,
    t.transaction_uom_name                        AS transaction_uom,
    t.transaction_quantity                        AS transaction_qty,

    CASE WHEN t.actual_qty > 0 THEN t.actual_qty ELSE 0 END      AS in_qty,
    CASE WHEN t.actual_qty < 0 THEN ABS(t.actual_qty) ELSE 0 END AS out_qty,
    t.balance_qty                                 AS balance_qty,

    t.incoming_rate                               AS incoming_rate,
    t.outgoing_rate                               AS outgoing_rate,
    t.valuation_rate                              AS valuation_rate,

    t.stock_value_difference                      AS stock_value_difference,
    t.balance_value                               AS balance_value,

    COALESCE(t.doctype_label, 'Stock')            AS voucher_type,
    COALESCE(t.voucher_code, '')                  AS voucher_no,

    COALESCE(t.branch_name, '')                   AS branch,
    CAST('' AS text)                              AS remarks,

    1                                             AS sort_rank,
    t.id                                          AS sort_id
  FROM tx_rows t
)

SELECT
  to_char(f.posting_date, 'DD-MM-YYYY') AS posting_date,
  f.posting_time                        AS posting_time,

  f.item_name                           AS item_name,
  f.warehouse                           AS warehouse,

  f.stock_uom                           AS stock_uom,
  f.transaction_uom                     AS transaction_uom,
  f.transaction_qty                     AS transaction_qty,

  f.in_qty                              AS in_qty,
  f.out_qty                             AS out_qty,
  f.balance_qty                         AS balance_qty,

  f.incoming_rate                       AS incoming_rate,
  f.outgoing_rate                       AS outgoing_rate,
  f.valuation_rate                      AS valuation_rate,

  f.stock_value_difference              AS stock_value_difference,
  f.balance_value                       AS balance_value,

  f.voucher_type                        AS voucher_type,
  f.voucher_no                          AS voucher_no,

  f.branch                              AS branch,
  f.remarks                             AS remarks

FROM final_rows f
ORDER BY
  f.posting_date,
  f.sort_rank,
  f.posting_time,
  f.sort_id
