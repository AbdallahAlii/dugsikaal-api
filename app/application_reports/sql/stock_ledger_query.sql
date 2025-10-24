-- app/application_reports/sql/stock_ledger_query.sql
-- Frappe-style stock ledger (by names), voucher-aware, Postgres-safe

SELECT
    sle.posting_date                         AS "posting_date",
    sle.posting_time                         AS "posting_time",

    it.name                                  AS "item_name",
    wh.name                                  AS "warehouse",

    uom_base.name                            AS "stock_uom",
    uom_trx.name                             AS "transaction_uom_name",
    sle.transaction_quantity                 AS "transaction_quantity",

    CASE WHEN sle.actual_qty > 0 THEN sle.actual_qty ELSE 0 END         AS "in_qty",
    CASE WHEN sle.actual_qty < 0 THEN ABS(sle.actual_qty) ELSE 0 END    AS "out_qty",
    sle.qty_after_transaction                AS "balance_qty",
    sle.incoming_rate                        AS "incoming_rate",
    sle.valuation_rate                       AS "valuation_rate",
    sle.stock_value_difference               AS "stock_value",

    /* Voucher shown to user (business doc), fallback to Stock Entry if needed */
    COALESCE(dt.code, 'STOCK_ENTRY')         AS "voucher_type",
    src.code                                  AS "voucher_no"

FROM stock_ledger_entries sle
JOIN items               it       ON it.id        = sle.item_id
JOIN warehouses          wh       ON wh.id        = sle.warehouse_id
JOIN units_of_measure    uom_base ON uom_base.id  = sle.base_uom_id
LEFT JOIN units_of_measure uom_trx ON uom_trx.id  = sle.transaction_uom_id
LEFT JOIN document_types  dt       ON dt.id       = sle.doc_type_id

/* Resolve voucher code from (doc_type_id, doc_id) OR from sle.stock_entry_id */
LEFT JOIN LATERAL (
    SELECT COALESCE(
        CASE dt.code
            WHEN 'PURCHASE_RECEIPT' THEN (SELECT pr.code  FROM purchase_receipts pr WHERE pr.id = sle.doc_id)
            WHEN 'PURCHASE_INVOICE' THEN (SELECT pi.code  FROM purchase_invoices pi WHERE pi.id = sle.doc_id)
            WHEN 'SALES_INVOICE'    THEN (SELECT si.code  FROM sales_invoices   si WHERE si.id = sle.doc_id)
            WHEN 'STOCK_ENTRY'      THEN (SELECT se.code  FROM stock_entries    se WHERE se.id = sle.doc_id)
            WHEN 'PURCHASE_RETURN'  THEN (SELECT prt.code FROM purchase_receipts prt WHERE prt.id = sle.doc_id)
            WHEN 'SALES_RETURN'     THEN (SELECT srt.code FROM sales_invoices   srt WHERE srt.id = sle.doc_id)
            ELSE NULL
        END,
        /* Fallback if doc_type_id is NULL but stock_entry_id is set */
        (SELECT se2.code FROM stock_entries se2 WHERE se2.id = sle.stock_entry_id)
    ) AS code
) src ON TRUE

WHERE
    sle.company_id = :company
    /* If voucher_no is provided, do NOT constrain by date window */
    AND (
        :voucher_no IS NOT NULL
        OR (
            sle.posting_date >= COALESCE(:from_date, CURRENT_DATE - INTERVAL '30 days')
            AND sle.posting_date <= COALESCE(:to_date,   CURRENT_DATE)
        )
    )
    AND sle.is_cancelled = FALSE

    /* Filters (by names, since you don't store codes) */
    AND (:voucher_no IS NULL OR src.code = :voucher_no)
    AND (:item_name  IS NULL OR it.name  = :item_name)
    AND (:warehouse  IS NULL OR wh.name  = :warehouse)

ORDER BY sle.posting_date, sle.posting_time, sle.id;
