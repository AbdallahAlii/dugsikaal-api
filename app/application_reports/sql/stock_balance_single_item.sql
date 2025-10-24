-- /* Stock Balance for a single (Item + Warehouse), hybrid-fast
--    NOTE: keep :name bind params; SQLAlchemy will adapt them for psycopg2.
-- */
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
--     COALESCE(CAST(:to_date   AS DATE), CURRENT_DATE) AS to_date
-- ),
-- meta AS (
--   SELECT
--     it.name  AS item_name,
--     ig.name  AS item_group,
--     wh.name  AS warehouse,
--     uom.name AS stock_uom
--   FROM resolved r
--   JOIN items it        ON it.id = r.item_id
--   JOIN item_groups ig  ON ig.id = it.item_group_id
--   JOIN warehouses wh   ON wh.id = r.warehouse_id
--   LEFT JOIN units_of_measure uom ON uom.id = it.base_uom_id
-- ),
-- agg AS (
--   SELECT
--     COALESCE(SUM(CASE WHEN sle.posting_date <  r.from_date THEN sle.actual_qty ELSE 0 END), 0) AS opening_qty,
--     COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.actual_qty > 0 THEN sle.actual_qty ELSE 0 END), 0) AS in_qty,
--     COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.actual_qty < 0 THEN ABS(sle.actual_qty) ELSE 0 END), 0) AS out_qty,
--
--     COALESCE(SUM(CASE WHEN sle.posting_date <  r.from_date THEN sle.stock_value_difference ELSE 0 END), 0) AS opening_value,
--     COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.stock_value_difference > 0 THEN sle.stock_value_difference ELSE 0 END), 0) AS in_value,
--     COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.stock_value_difference < 0 THEN ABS(sle.stock_value_difference) ELSE 0 END), 0) AS out_value
--   FROM resolved r
--   LEFT JOIN stock_ledger_entries sle
--     ON  sle.company_id   = r.company_id
--     AND sle.item_id      = r.item_id
--     AND sle.warehouse_id = r.warehouse_id
--     AND (r.branch_id IS NULL OR sle.branch_id = r.branch_id)  -- r.branch_id is BIGINT now
--     AND (r.include_cancelled OR sle.is_cancelled = FALSE)
--     AND sle.posting_date <= r.to_date
-- ),
-- last_rate AS (
--   SELECT sle.valuation_rate
--   FROM stock_ledger_entries sle
--   JOIN resolved r ON TRUE
--   WHERE sle.company_id   = r.company_id
--     AND sle.item_id      = r.item_id
--     AND sle.warehouse_id = r.warehouse_id
--     AND (r.branch_id IS NULL OR sle.branch_id = r.branch_id)
--     AND (r.include_cancelled OR sle.is_cancelled = FALSE)
--     AND sle.posting_date <= r.to_date
--   ORDER BY sle.posting_date DESC, sle.posting_time DESC, sle.id DESC
--   LIMIT 1
-- )
-- SELECT
--   m.item_name,
--   m.item_group,
--   m.warehouse,
--   m.stock_uom,
--
--   a.opening_qty,
--   a.opening_value,
--
--   a.in_qty,
--   a.in_value,
--   a.out_qty,
--   a.out_value,
--
--   (a.opening_qty + a.in_qty - a.out_qty) AS balance_qty,
--   COALESCE(lr.valuation_rate, 0)          AS valuation_rate,
--   (a.opening_qty + a.in_qty - a.out_qty) * COALESCE(lr.valuation_rate, 0) AS balance_value
-- FROM meta m
-- CROSS JOIN agg a
-- LEFT JOIN last_rate lr ON TRUE;
/* Stock Balance for an Item (warehouse optional, ERP-style).
   - If :warehouse / :warehouse_id is NULL, show a row per warehouse that has activity for the item.
   - If warehouse provided, return a single row for that warehouse.
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
    COALESCE(CAST(:to_date   AS DATE), CURRENT_DATE) AS to_date
),
meta AS (
  SELECT
    it.id     AS item_id,
    it.name   AS item_name,
    ig.name   AS item_group,
    uom.name  AS stock_uom
  FROM resolved r
  JOIN items it       ON it.id = r.item_id
  JOIN item_groups ig ON ig.id = it.item_group_id
  LEFT JOIN units_of_measure uom ON uom.id = it.base_uom_id
),
/* Warehouses to include: specific one if provided, else all that have SLE for this item */
wh_dim AS (
  SELECT w.id, w.name
  FROM resolved r
  JOIN warehouses w
    ON w.company_id = r.company_id
  WHERE
    (r.warehouse_id IS NULL OR w.id = r.warehouse_id)
    AND EXISTS (
      SELECT 1
      FROM stock_ledger_entries sle
      WHERE sle.company_id   = r.company_id
        AND sle.item_id      = r.item_id
        AND sle.warehouse_id = w.id
        AND (r.branch_id IS NULL OR sle.branch_id = r.branch_id)
        AND (r.include_cancelled OR sle.is_cancelled = FALSE)
    )
),
agg AS (
  SELECT
    wh.id AS warehouse_id,
    COALESCE(SUM(CASE WHEN sle.posting_date <  r.from_date THEN sle.actual_qty ELSE 0 END), 0) AS opening_qty,
    COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.actual_qty > 0 THEN sle.actual_qty ELSE 0 END), 0) AS in_qty,
    COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.actual_qty < 0 THEN ABS(sle.actual_qty) ELSE 0 END), 0) AS out_qty,

    COALESCE(SUM(CASE WHEN sle.posting_date <  r.from_date THEN sle.stock_value_difference ELSE 0 END), 0) AS opening_value,
    COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.stock_value_difference > 0 THEN sle.stock_value_difference ELSE 0 END), 0) AS in_value,
    COALESCE(SUM(CASE WHEN sle.posting_date >= r.from_date AND sle.posting_date <= r.to_date AND sle.stock_value_difference < 0 THEN ABS(sle.stock_value_difference) ELSE 0 END), 0) AS out_value
  FROM resolved r
  JOIN wh_dim wh ON TRUE
  LEFT JOIN stock_ledger_entries sle
    ON  sle.company_id   = r.company_id
    AND sle.item_id      = r.item_id
    AND sle.warehouse_id = wh.id
    AND (r.branch_id IS NULL OR sle.branch_id = r.branch_id)
    AND (r.include_cancelled OR sle.is_cancelled = FALSE)
    AND sle.posting_date <= r.to_date
  GROUP BY wh.id
),
last_rate AS (
  SELECT
    wh.id AS warehouse_id,
    (
      SELECT sle.valuation_rate
      FROM stock_ledger_entries sle
      JOIN resolved r2 ON TRUE
      WHERE sle.company_id   = r2.company_id
        AND sle.item_id      = r2.item_id
        AND sle.warehouse_id = wh.id
        AND (r2.branch_id IS NULL OR sle.branch_id = r2.branch_id)
        AND (r2.include_cancelled OR sle.is_cancelled = FALSE)
        AND sle.posting_date <= r2.to_date
      ORDER BY sle.posting_date DESC, sle.posting_time DESC, sle.id DESC
      LIMIT 1
    ) AS valuation_rate
  FROM wh_dim wh
)
SELECT
  m.item_name,
  m.item_group,
  w.name AS warehouse,
  m.stock_uom,

  a.opening_qty,
  a.opening_value,
  a.in_qty,
  a.in_value,
  a.out_qty,
  a.out_value,

  (a.opening_qty + a.in_qty - a.out_qty) AS balance_qty,
  COALESCE(lr.valuation_rate, 0)         AS valuation_rate,
  (a.opening_qty + a.in_qty - a.out_qty) * COALESCE(lr.valuation_rate, 0) AS balance_value
FROM meta m
JOIN agg a      ON TRUE
JOIN wh_dim w   ON w.id = a.warehouse_id
LEFT JOIN last_rate lr ON lr.warehouse_id = a.warehouse_id
ORDER BY w.name;
