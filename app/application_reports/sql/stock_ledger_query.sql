--/* -----------------------------------------------------------------------------
-- Stock Ledger (ERP-style, Frappe-like)
-- - Voucher-first: if :voucher_no is passed, ignore date window
-- - Otherwise date window (default: last 30 days)
-- - Returns:
--   posting_date (DD-MM-YYYY), posting_time (HH24:MI:SS),
--   item_name, warehouse, stock_uom, transaction_uom, transaction_qty,
--   in_qty, out_qty, balance_qty,
--   incoming_rate, outgoing_rate, valuation_rate,
--   stock_value_difference, running_stock_value,
--   voucher_type (human), voucher_no, branch, remarks
--------------------------------------------------------------------------------*/
--
--WITH base AS (
--  SELECT
--    sle.id,
--    sle.company_id,
--    sle.item_id,
--    sle.warehouse_id,
--    sle.branch_id,
--    sle.base_uom_id,
--    sle.transaction_uom_id,
--    sle.transaction_quantity,
--    sle.posting_date::date                    AS posting_date,
--    sle.posting_time                          AS posting_time,
--    sle.actual_qty::numeric(18,6)             AS actual_qty,
--    sle.incoming_rate::numeric(18,6)          AS incoming_rate,
--    sle.outgoing_rate::numeric(18,6)          AS outgoing_rate,
--    sle.valuation_rate::numeric(18,6)         AS valuation_rate,
--    sle.stock_value_difference::numeric(20,6) AS stock_value_difference,
--    sle.qty_after_transaction::numeric(18,6)  AS balance_qty,
--    sle.doc_type_id,
--    sle.doc_id,
--    sle.stock_entry_id,
--    sle.is_cancelled,
--    sle.is_reversal
--  FROM stock_ledger_entries sle
--  WHERE sle.company_id = :company
--    AND sle.is_cancelled = FALSE
--    AND (
--      (:voucher_no IS NOT NULL)
--      OR (
--        sle.posting_date >= COALESCE(:from_date, CURRENT_DATE - INTERVAL '30 days')
--        AND sle.posting_date <= COALESCE(:to_date,   CURRENT_DATE)
--      )
--    )
--),
--
--look AS (
--  SELECT
--    b.*,
--    it.name               AS item_name,
--    wh.name               AS warehouse_name,
--    uom_base.name         AS stock_uom_name,
--    uom_trx.name          AS transaction_uom_name,
--    br.name               AS branch_name,
--    dt.code               AS doctype_code,
--    dt.label              AS doctype_label
--  FROM base b
--  JOIN items it                    ON it.id  = b.item_id
--  JOIN warehouses wh               ON wh.id  = b.warehouse_id
--  JOIN units_of_measure uom_base   ON uom_base.id = b.base_uom_id
--  LEFT JOIN units_of_measure uom_trx ON uom_trx.id = b.transaction_uom_id
--  LEFT JOIN branches br            ON br.id  = b.branch_id
--  LEFT JOIN document_types dt      ON dt.id  = b.doc_type_id
--),
--
--/* Resolve voucher code from (doctype, doc_id), with fallback via stock_entry_id */
--voucher AS (
--  SELECT
--    l.id AS sle_id,
--    COALESCE(
--      CASE l.doctype_code
--        WHEN 'PURCHASE_RECEIPT'      THEN (SELECT pr.code  FROM purchase_receipts      pr  WHERE pr.id  = l.doc_id)
--        WHEN 'SALES_DELIVERY_NOTE'   THEN (SELECT sdn.code FROM sales_delivery_notes   sdn WHERE sdn.id = l.doc_id)
--        WHEN 'DELIVERY_NOTE'         THEN (SELECT dn.code  FROM sales_delivery_notes   dn  WHERE dn.id  = l.doc_id) -- alias kept if present
--        WHEN 'STOCK_ENTRY'           THEN (SELECT se.code  FROM stock_entries          se  WHERE se.id  = l.doc_id)
--        WHEN 'STOCK_RECONCILIATION'  THEN (SELECT sr.code  FROM stock_reconciliations  sr  WHERE sr.id  = l.doc_id)
--        WHEN 'LANDED_COST_VOUCHER'   THEN (SELECT lcv.code FROM landed_cost_vouchers   lcv WHERE lcv.id = l.doc_id)
--        WHEN 'SALES_INVOICE'         THEN (SELECT si.code  FROM sales_invoices         si  WHERE si.id  = l.doc_id)       -- ✅ added
--        WHEN 'PURCHASE_INVOICE'      THEN (SELECT pin.code FROM purchase_invoices      pin WHERE pin.id = l.doc_id)       -- ✅ added
--        ELSE NULL
--      END,
--      /* Fallback: if (doc_type_id, doc_id) isn’t set but stock_entry_id is */
--      (SELECT se2.code FROM stock_entries se2 WHERE se2.id = l.stock_entry_id)
--    ) AS voucher_code
--  FROM look l
--),
--
--/* Running stock value after each row (“Value after Transaction”) */
--value_running AS (
--  SELECT
--    l.id AS sle_id,
--    SUM(l.stock_value_difference) OVER (
--      PARTITION BY l.company_id, l.item_id, l.warehouse_id
--      ORDER BY l.posting_date, l.posting_time, l.id
--      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
--    )::numeric(20,6) AS running_stock_value
--  FROM look l
--)
--
--SELECT
--  to_char(l.posting_date, 'DD-MM-YYYY') AS "posting_date",
--  to_char(l.posting_time, 'HH24:MI:SS') AS "posting_time",
--
--  l.item_name                           AS "item_name",
--  l.warehouse_name                      AS "warehouse",
--
--  l.stock_uom_name                      AS "stock_uom",
--  l.transaction_uom_name                AS "transaction_uom",
--  l.transaction_quantity                AS "transaction_qty",
--
--  CASE WHEN l.actual_qty > 0 THEN l.actual_qty ELSE 0 END      AS "in_qty",
--  CASE WHEN l.actual_qty < 0 THEN ABS(l.actual_qty) ELSE 0 END AS "out_qty",
--  l.balance_qty                                                   AS "balance_qty",
--
--  l.incoming_rate                        AS "incoming_rate",
--  l.outgoing_rate                        AS "outgoing_rate",
--  l.valuation_rate                       AS "valuation_rate",
--
--  l.stock_value_difference               AS "stock_value_difference",
--  vr.running_stock_value                 AS "running_stock_value",
--
--  COALESCE(l.doctype_label, 'Stock Entry') AS "voucher_type",
--  v.voucher_code                           AS "voucher_no",
--
--  COALESCE(l.branch_name, '')              AS "branch",
--  ''::text                                 AS "remarks"
--FROM look l
--LEFT JOIN voucher v         ON v.sle_id  = l.id
--LEFT JOIN value_running vr  ON vr.sle_id = l.id
--WHERE
--  (:voucher_no IS NULL OR v.voucher_code = :voucher_no)
--  AND (:item_name  IS NULL OR l.item_name      = :item_name)
--  AND (:warehouse  IS NULL OR l.warehouse_name = :warehouse)
--  AND (:branch_id  IS NULL OR l.branch_id      = :branch_id)
--ORDER BY l.posting_date, l.posting_time, l.id
/* -----------------------------------------------------------------------------
 Stock Ledger (ERP-style, Frappe-like)
 - Voucher-first: if :voucher_no is passed, ignore date window
 - Otherwise: date window (default last 30 days)
 - NO fallbacks for transaction UOM/Qty: if null in SLE, stays null.
------------------------------------------------------------------------------*/

WITH base AS (
  SELECT
    sle.id,
    sle.company_id,
    sle.item_id,
    sle.warehouse_id,
    sle.branch_id,
    sle.base_uom_id,
    sle.transaction_uom_id,           -- keep as-is
    sle.transaction_quantity,         -- keep as-is
    sle.posting_date::date            AS posting_date,
    sle.posting_time                  AS posting_time,
    sle.actual_qty::numeric(18,6)     AS actual_qty,
    sle.incoming_rate::numeric(18,6)  AS incoming_rate,
    sle.outgoing_rate::numeric(18,6)  AS outgoing_rate,
    sle.valuation_rate::numeric(18,6) AS valuation_rate,
    sle.stock_value_difference::numeric(20,6) AS stock_value_difference,
    sle.qty_after_transaction::numeric(18,6)  AS balance_qty,
    sle.doc_type_id,
    sle.doc_id,
    sle.stock_entry_id,
    sle.is_cancelled,
    sle.is_reversal
  FROM stock_ledger_entries sle
  WHERE sle.company_id = :company
    AND sle.is_cancelled = FALSE
    AND (
      (:voucher_no IS NOT NULL)
      OR (
        sle.posting_date >= COALESCE(:from_date, CURRENT_DATE - INTERVAL '30 days')
        AND sle.posting_date <= COALESCE(:to_date,   CURRENT_DATE)
      )
    )
),

look AS (
  SELECT
    b.*,
    it.name                 AS item_name,
    wh.name                 AS warehouse_name,
    uom_base.name           AS stock_uom_name,
    uom_trx.name            AS transaction_uom_name,  -- LEFT JOIN keeps NULLs intact
    br.name                 AS branch_name,
    dt.code                 AS doctype_code,
    dt.label                AS doctype_label
  FROM base b
  JOIN items it                     ON it.id  = b.item_id
  JOIN warehouses wh                ON wh.id  = b.warehouse_id
  JOIN units_of_measure uom_base    ON uom_base.id = b.base_uom_id
  LEFT JOIN units_of_measure uom_trx ON uom_trx.id = b.transaction_uom_id
  LEFT JOIN branches br             ON br.id  = b.branch_id
  LEFT JOIN document_types dt       ON dt.id  = b.doc_type_id
),

voucher AS (
  SELECT
    l.id AS sle_id,
    COALESCE(
      CASE l.doctype_code
        WHEN 'PURCHASE_RECEIPT'      THEN (SELECT pr.code  FROM purchase_receipts      pr  WHERE pr.id  = l.doc_id)
        WHEN 'SALES_DELIVERY_NOTE'   THEN (SELECT sdn.code FROM sales_delivery_notes   sdn WHERE sdn.id = l.doc_id)
        WHEN 'DELIVERY_NOTE'         THEN (SELECT dn.code  FROM sales_delivery_notes   dn  WHERE dn.id  = l.doc_id)
        WHEN 'STOCK_ENTRY'           THEN (SELECT se.code  FROM stock_entries          se  WHERE se.id  = l.doc_id)
        WHEN 'STOCK_RECONCILIATION'  THEN (SELECT sr.code  FROM stock_reconciliations  sr  WHERE sr.id  = l.doc_id)
        WHEN 'LANDED_COST_VOUCHER'   THEN (SELECT lcv.code FROM landed_cost_vouchers   lcv WHERE lcv.id = l.doc_id)
        WHEN 'SALES_INVOICE'         THEN (SELECT si.code  FROM sales_invoices         si  WHERE si.id  = l.doc_id)
        WHEN 'PURCHASE_INVOICE'      THEN (SELECT pin.code FROM purchase_invoices      pin WHERE pin.id = l.doc_id)
        ELSE NULL
      END,
      (SELECT se2.code FROM stock_entries se2 WHERE se2.id = l.stock_entry_id)
    ) AS voucher_code
  FROM look l
),

value_running AS (
  SELECT
    l.id AS sle_id,
    SUM(l.stock_value_difference) OVER (
      PARTITION BY l.company_id, l.item_id, l.warehouse_id
      ORDER BY l.posting_date, l.posting_time, l.id
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )::numeric(20,6) AS running_stock_value
  FROM look l
)

SELECT
  to_char(l.posting_date, 'DD-MM-YYYY') AS "posting_date",
  to_char(l.posting_time, 'HH24:MI:SS') AS "posting_time",

  l.item_name            AS "item_name",
  l.warehouse_name       AS "warehouse",

  l.stock_uom_name       AS "stock_uom",
  l.transaction_uom_name AS "transaction_uom",     -- stays NULL if not present in SLE
  l.transaction_quantity AS "transaction_qty",     -- stays NULL if not present in SLE

  CASE WHEN l.actual_qty > 0 THEN l.actual_qty ELSE 0 END      AS "in_qty",
  CASE WHEN l.actual_qty < 0 THEN ABS(l.actual_qty) ELSE 0 END AS "out_qty",
  l.balance_qty                                              AS "balance_qty",

  l.incoming_rate        AS "incoming_rate",
  l.outgoing_rate        AS "outgoing_rate",
  l.valuation_rate       AS "valuation_rate",

  l.stock_value_difference AS "stock_value_difference",
  vr.running_stock_value   AS "running_stock_value",

  COALESCE(l.doctype_label, 'Stock Entry') AS "voucher_type",
  v.voucher_code                           AS "voucher_no",

  COALESCE(l.branch_name, '') AS "branch",
  ''::text                    AS "remarks"
FROM look l
LEFT JOIN voucher v        ON v.sle_id  = l.id
LEFT JOIN value_running vr ON vr.sle_id = l.id
WHERE
  (:voucher_no IS NULL OR v.voucher_code = :voucher_no)
  AND (:item_name  IS NULL OR l.item_name      = :item_name)
  AND (:warehouse  IS NULL OR l.warehouse_name = :warehouse)
  AND (:branch_id  IS NULL OR l.branch_id      = :branch_id)
ORDER BY l.posting_date, l.posting_time, l.id
