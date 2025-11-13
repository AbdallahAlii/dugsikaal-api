-- -- app/application_reports/sql/general_ledger_query.sql
-- GL shows business document as voucher; falls back to JE if no source exists.
SELECT
    gle.posting_date                                AS "posting_date",
    acc.code                                        AS "account",
    acc.name                                        AS "account_name",

    gle.debit                                       AS "debit",
    gle.credit                                      AS "credit",
    (gle.debit - gle.credit)                        AS "balance",

    -- Party info
    gle.party_type                                  AS "party_type",
    gle.party_id                                    AS "party_id",
    p.name                                          AS "party_name",

    -- Cost center & remarks
    cc.name                                         AS "cost_center",
    je.remarks                                      AS "remarks",

    -- Voucher: prefer source doc (type+code); fallback to JE (entry_type+code)
    COALESCE(dt.code, je.entry_type::text)          AS "voucher_type",
    COALESCE(doc_info.source_code, je.code)         AS "voucher_no",

    -- Branch (robust if either GLE or JE carries branch_id)
    br.name                                         AS "branch_name"

FROM general_ledger_entries gle
JOIN journal_entries      je   ON je.id  = gle.journal_entry_id
JOIN accounts             acc  ON acc.id = gle.account_id
LEFT JOIN cost_centers    cc   ON cc.id  = gle.cost_center_id
LEFT JOIN parties         p    ON p.id   = gle.party_id

LEFT JOIN LATERAL (
    SELECT
        COALESCE(gle.source_doctype_id, je.source_doctype_id) AS doctype_id,
        COALESCE(gle.source_doc_id,    je.source_doc_id)      AS doc_id
) link ON TRUE

LEFT JOIN document_types dt ON dt.id = link.doctype_id

/* Voucher code resolution – based on your actual document types */
LEFT JOIN LATERAL (
    SELECT CASE dt.code
        WHEN 'PURCHASE_RECEIPT'     THEN (SELECT pr.code  FROM purchase_receipts     pr  WHERE pr.id  = link.doc_id)
        WHEN 'PURCHASE_INVOICE'     THEN (SELECT pi.code  FROM purchase_invoices     pi  WHERE pi.id  = link.doc_id)
        WHEN 'SALES_INVOICE'        THEN (SELECT si.code  FROM sales_invoices        si  WHERE si.id  = link.doc_id)
        WHEN 'SALES_DELIVERY_NOTE'  THEN (SELECT sdn.code FROM sales_delivery_notes  sdn WHERE sdn.id = link.doc_id)
        WHEN 'STOCK_ENTRY'          THEN (SELECT se.code  FROM stock_entries         se  WHERE se.id  = link.doc_id)
        WHEN 'STOCK_RECONCILIATION' THEN (SELECT sr.code  FROM stock_reconciliations sr  WHERE sr.id  = link.doc_id)
        WHEN 'DELIVERY_NOTE'        THEN (SELECT dn.code  FROM sales_delivery_notes  dn  WHERE dn.id  = link.doc_id)
        WHEN 'PAYMENT_ENTRY'        THEN (SELECT pe.code  FROM payment_entries       pe  WHERE pe.id  = link.doc_id)
        WHEN 'EXPENSE'              THEN (SELECT ex.code  FROM expenses              ex  WHERE ex.id  = link.doc_id)
        WHEN 'LANDED_COST_VOUCHER'  THEN (SELECT lcv.code FROM landed_cost_vouchers lcv WHERE lcv.id = link.doc_id)
        ELSE NULL
    END AS source_code
) doc_info ON TRUE

-- Branch join: prefer GLE.branch_id; fallback to JE.branch_id
LEFT JOIN branches br ON br.id = COALESCE(gle.branch_id, je.branch_id)

WHERE
    gle.company_id = :company

    -- FIXED: Better date handling - if specific filters are provided, don't use default date range
    AND (
        :source_doc_id IS NOT NULL
        OR :voucher_no IS NOT NULL
        OR :source_document IS NOT NULL
        OR (
            gle.posting_date >= COALESCE(:from_date, CURRENT_DATE - INTERVAL '90 days')
            AND gle.posting_date <= COALESCE(:to_date, CURRENT_DATE)
        )
    )

    -- Filters
    AND (:account      IS NULL OR acc.code                          = :account)
    AND (:party        IS NULL OR gle.party_id                      = :party)
    AND (:cost_center  IS NULL OR cc.name                           = :cost_center)

    -- Branch filter by id only (no dependency on branch code)
    AND (:branch_id    IS NULL OR COALESCE(gle.branch_id, je.branch_id) = :branch_id)

    -- By source doc code (e.g., PR-2025-00041)
    AND (:source_doc_id   IS NULL OR gle.source_doc_id         = :source_doc_id)
    AND (:source_document IS NULL OR doc_info.source_code = :source_document)

    -- voucher_no can be either JE code OR source doc code
    AND (
        :voucher_no IS NULL
        OR je.code = :voucher_no
        OR doc_info.source_code = :voucher_no
    )

    -- Skip cancelled JEs
    AND je.doc_status <> 'CANCELLED'

ORDER BY gle.posting_date, gle.id;