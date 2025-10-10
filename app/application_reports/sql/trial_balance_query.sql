-- app/common/reports/sql/trial_balance_query.sql
-- Trial Balance Report Query
SELECT
    acc.code as "account",
    acc.name as "account_name",
    COALESCE(SUM(CASE WHEN gle.posting_date < :from_date THEN gle.debit ELSE 0 END), 0) as "opening_debit",
    COALESCE(SUM(CASE WHEN gle.posting_date < :from_date THEN gle.credit ELSE 0 END), 0) as "opening_credit",
    COALESCE(SUM(CASE WHEN gle.posting_date >= :from_date AND gle.posting_date <= :to_date THEN gle.debit ELSE 0 END), 0) as "debit",
    COALESCE(SUM(CASE WHEN gle.posting_date >= :from_date AND gle.posting_date <= :to_date THEN gle.credit ELSE 0 END), 0) as "credit",
    COALESCE(SUM(CASE WHEN gle.posting_date <= :to_date THEN gle.debit ELSE 0 END), 0) as "closing_debit",
    COALESCE(SUM(CASE WHEN gle.posting_date <= :to_date THEN gle.credit ELSE 0 END), 0) as "closing_credit"
FROM accounts acc
LEFT JOIN general_ledger_entries gle ON acc.id = gle.account_id
WHERE acc.company_id = :company
    AND acc.status = 'SUBMITTED'
    AND (gle.is_cancelled = false OR gle.is_cancelled IS NULL)
GROUP BY acc.id, acc.code, acc.name
HAVING (
    COALESCE(SUM(CASE WHEN gle.posting_date < :from_date THEN gle.debit ELSE 0 END), 0) != 0
    OR COALESCE(SUM(CASE WHEN gle.posting_date < :from_date THEN gle.credit ELSE 0 END), 0) != 0
    OR COALESCE(SUM(CASE WHEN gle.posting_date >= :from_date AND gle.posting_date <= :to_date THEN gle.debit ELSE 0 END), 0) != 0
    OR COALESCE(SUM(CASE WHEN gle.posting_date >= :from_date AND gle.posting_date <= :to_date THEN gle.credit ELSE 0 END), 0) != 0
)
ORDER BY acc.code