-- -- /* Item Stock Ledger (history) for single Item + Warehouse, hybrid-fast */
--
-- /* Item Stock Ledger (history) for single Item + Warehouse, hybrid-fast */
--
-- WITH resolved AS (
--   SELECT
--     CAST(:company AS BIGINT) AS company_id,
--     COALESCE(
--       CAST(:item_id AS BIGINT),
--       (SELECT i.id
--          FROM items i
--         WHERE i.company_id = CAST(:company AS BIGINT)
--           AND (i.sku = :item OR i.name = :item)
--         LIMIT 1)
--     ) AS item_id,
--     COALESCE(
--       CAST(:warehouse_id AS BIGINT),
--       (SELECT w.id
--          FROM warehouses w
--         WHERE w.company_id = CAST(:company AS BIGINT)
--           AND (w.code = :warehouse OR w.name = :warehouse)
--         LIMIT 1)
--     ) AS warehouse_id,
--     CAST(:branch_id AS BIGINT) AS branch_id,
--     COALESCE(CAST(:include_cancelled AS BOOLEAN), FALSE) AS include_cancelled,
--     COALESCE(CAST(:from_date AS DATE), date_trunc('month', CURRENT_DATE)::date) AS from_date,
--     COALESCE(CAST(:to_date   AS DATE), CURRENT_DATE) AS to_date,
--     NULLIF(CAST(:voucher_no AS TEXT), '') AS voucher_no,
--     CAST(NULLIF(:limit, 0) AS INT)  AS lim,
--     COALESCE(CAST(:offset AS INT), 0) AS off
-- )
-- SELECT
--   b.posting_date,
--   to_char(b.posting_time, 'HH24:MI:SS') AS posting_time,
--
--   it.name        AS item_name,
--   ig.name        AS item_group,
--   wh.name        AS warehouse,
--
--   uom_base.name  AS stock_uom,
--   uom_trx.name   AS transaction_uom_name,
--   b.transaction_quantity,
--
--   CASE WHEN b.actual_qty > 0 THEN b.actual_qty ELSE 0 END                              AS in_qty,
--   CASE WHEN b.stock_value_difference > 0 THEN b.stock_value_difference ELSE 0 END      AS in_value,
--
--   CASE WHEN b.actual_qty < 0 THEN ABS(b.actual_qty) ELSE 0 END                         AS out_qty,
--   CASE WHEN b.stock_value_difference < 0 THEN ABS(b.stock_value_difference) ELSE 0 END AS out_value,
--
--   b.qty_after_transaction AS balance_qty,
--   b.incoming_rate,
--   b.valuation_rate,
--   (b.valuation_rate * b.qty_after_transaction) AS balance_value,
--
--   COALESCE(dt.code, 'STOCK_ENTRY') AS voucher_type,
--   v.code AS voucher_no
-- FROM resolved r
-- JOIN stock_ledger_entries b
--   ON  b.company_id   = r.company_id
--   AND b.item_id      = r.item_id
--   AND b.warehouse_id = r.warehouse_id
--   AND (r.branch_id IS NULL OR b.branch_id = r.branch_id)
--   AND (r.include_cancelled OR b.is_cancelled = FALSE)
--   AND (
--         r.voucher_no IS NOT NULL
--      OR (b.posting_date >= r.from_date AND b.posting_date <= r.to_date)
--   )
-- JOIN items it              ON it.id = b.item_id
-- JOIN item_groups ig        ON ig.id = it.item_group_id
-- JOIN warehouses wh         ON wh.id = b.warehouse_id
-- LEFT JOIN units_of_measure uom_base ON uom_base.id = b.base_uom_id
-- LEFT JOIN units_of_measure uom_trx  ON uom_trx.id  = b.transaction_uom_id
-- LEFT JOIN document_types dt         ON dt.id       = b.doc_type_id
--
-- /* voucher code resolution – only base doctypes you actually have */
-- LEFT JOIN LATERAL (
--   SELECT COALESCE(
--     CASE dt.code
--       WHEN 'PURCHASE_RECEIPT'     THEN (SELECT pr.code  FROM purchase_receipts     pr  WHERE pr.id  = b.doc_id)
--       WHEN 'PURCHASE_INVOICE'     THEN (SELECT pi.code  FROM purchase_invoices     pi  WHERE pi.id  = b.doc_id)
--       WHEN 'SALES_INVOICE'        THEN (SELECT si.code  FROM sales_invoices        si  WHERE si.id  = b.doc_id)
--       WHEN 'SALES_DELIVERY_NOTE'  THEN (SELECT sdn.code FROM sales_delivery_notes  sdn WHERE sdn.id = b.doc_id)
--       WHEN 'STOCK_ENTRY'          THEN (SELECT se.code  FROM stock_entries         se  WHERE se.id  = b.doc_id)
--       WHEN 'STOCK_RECONCILIATION' THEN (SELECT sr.code  FROM stock_reconciliations sr  WHERE sr.id  = b.doc_id)
--       ELSE NULL
--     END,
--     /* secondary fallback */
--     (SELECT se2.code FROM stock_entries se2 WHERE se2.id = b.stock_entry_id)
--   ) AS code
-- ) v ON TRUE
--
-- WHERE (r.voucher_no IS NULL OR v.code = r.voucher_no)
-- ORDER BY b.posting_date, b.posting_time, b.id
-- LIMIT COALESCE((SELECT lim FROM resolved), 1000)
-- OFFSET (SELECT off FROM resolved);
/* Item Stock Ledger (item required, warehouse optional).
   - If :warehouse not given, list all movements for the item across all warehouses.
*/

WITH resolved AS (
  SELECT
    CAST(:company AS BIGINT) AS company_id,
    COALESCE(
      CAST(:item_id AS BIGINT),
      (SELECT i.id
         FROM items i
        WHERE i.company_id = CAST(:company AS BIGINT)
          AND (i.sku = :item OR i.name = :item)
        LIMIT 1)
    ) AS item_id,
    /* warehouse is optional */
    COALESCE(
      CAST(:warehouse_id AS BIGINT),
      (SELECT w.id
         FROM warehouses w
        WHERE w.company_id = CAST(:company AS BIGINT)
          AND (w.code = :warehouse OR w.name = :warehouse)
        LIMIT 1)
    ) AS warehouse_id,
    CAST(:branch_id AS BIGINT) AS branch_id,
    COALESCE(CAST(:include_cancelled AS BOOLEAN), FALSE) AS include_cancelled,
    COALESCE(CAST(:from_date AS DATE), date_trunc('month', CURRENT_DATE)::date) AS from_date,
    COALESCE(CAST(:to_date   AS DATE), CURRENT_DATE) AS to_date,
    NULLIF(CAST(:voucher_no AS TEXT), '') AS voucher_no,
    CAST(NULLIF(:limit, 0) AS INT)  AS lim,
    COALESCE(CAST(:offset AS INT), 0) AS off
)
SELECT
  b.posting_date,
  to_char(b.posting_time, 'HH24:MI:SS') AS posting_time,

  it.name        AS item_name,
  ig.name        AS item_group,
  wh.name        AS warehouse,

  uom_base.name  AS stock_uom,
  uom_trx.name   AS transaction_uom_name,
  b.transaction_quantity,

  CASE WHEN b.actual_qty > 0 THEN b.actual_qty ELSE 0 END                              AS in_qty,
  CASE WHEN b.stock_value_difference > 0 THEN b.stock_value_difference ELSE 0 END      AS in_value,

  CASE WHEN b.actual_qty < 0 THEN ABS(b.actual_qty) ELSE 0 END                         AS out_qty,
  CASE WHEN b.stock_value_difference < 0 THEN ABS(b.stock_value_difference) ELSE 0 END AS out_value,

  b.qty_after_transaction AS balance_qty,
  b.incoming_rate,
  b.valuation_rate,
  (b.valuation_rate * b.qty_after_transaction) AS balance_value,

  COALESCE(dt.code, 'STOCK_ENTRY') AS voucher_type,
  v.code AS voucher_no
FROM resolved r
JOIN stock_ledger_entries b
  ON  b.company_id = r.company_id
  AND b.item_id    = r.item_id
  AND (r.warehouse_id IS NULL OR b.warehouse_id = r.warehouse_id)   -- warehouse optional
  AND (r.branch_id IS NULL OR b.branch_id = r.branch_id)
  AND (r.include_cancelled OR b.is_cancelled = FALSE)
  AND (
        r.voucher_no IS NOT NULL
     OR (b.posting_date >= r.from_date AND b.posting_date <= r.to_date)
  )
JOIN items it              ON it.id = b.item_id
JOIN item_groups ig        ON ig.id = it.item_group_id
JOIN warehouses wh         ON wh.id = b.warehouse_id
LEFT JOIN units_of_measure uom_base ON uom_base.id = b.base_uom_id
LEFT JOIN units_of_measure uom_trx  ON uom_trx.id  = b.transaction_uom_id
LEFT JOIN document_types dt         ON dt.id       = b.doc_type_id

/* voucher code resolution – only base doctypes you actually have */
LEFT JOIN LATERAL (
  SELECT COALESCE(
    CASE dt.code
      WHEN 'PURCHASE_RECEIPT'     THEN (SELECT pr.code  FROM purchase_receipts     pr  WHERE pr.id  = b.doc_id)
      WHEN 'PURCHASE_INVOICE'     THEN (SELECT pi.code  FROM purchase_invoices     pi  WHERE pi.id  = b.doc_id)
      WHEN 'SALES_INVOICE'        THEN (SELECT si.code  FROM sales_invoices        si  WHERE si.id  = b.doc_id)
      WHEN 'SALES_DELIVERY_NOTE'  THEN (SELECT sdn.code FROM sales_delivery_notes  sdn WHERE sdn.id = b.doc_id)
      WHEN 'STOCK_ENTRY'          THEN (SELECT se.code  FROM stock_entries         se  WHERE se.id  = b.doc_id)
      WHEN 'STOCK_RECONCILIATION' THEN (SELECT sr.code  FROM stock_reconciliations sr  WHERE sr.id  = b.doc_id)
      ELSE NULL
    END,
    /* secondary fallback */
    (SELECT se2.code FROM stock_entries se2 WHERE se2.id = b.stock_entry_id)
  ) AS code
) v ON TRUE

WHERE (r.voucher_no IS NULL OR v.code = r.voucher_no)
ORDER BY b.posting_date, b.posting_time, b.id
LIMIT COALESCE((SELECT lim FROM resolved), 1000)
OFFSET (SELECT off FROM resolved);
