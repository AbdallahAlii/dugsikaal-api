"""update buying check constraints

Revision ID: 674695945af2
Revises: 3ddfdda4812c
Create Date: 2025-11-19 09:53:36.521642

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  (kept for future edits / consistency)


# revision identifiers, used by Alembic.
revision = "674695945af2"
down_revision = "3ddfdda4812c"
branch_labels = None
depends_on = None


def upgrade():
    """
    Align BUYING doctypes with the current model definitions.

    1) PurchaseInvoice (purchase_invoices):
       - Remove old non-signed rules.
       - Add:
            * ck_pin_amount_consistency
                total_amount = paid_amount + outstanding_amount
            * ck_pin_amounts_sign_by_return
                • is_return = false → totals/balances >= 0
                • is_return = true  → totals/balances <= 0
            * ck_pin_payment_consistency_signed
                • paid_amount = 0      → no MOP / cash-bank
                • is_return = false,
                  paid_amount > 0      → require MOP + cash-bank
                • is_return = true,
                  paid_amount < 0      → require MOP + cash-bank
       - New constraints are created as NOT VALID so existing rows
         will not block the migration. They will be enforced for new
         INSERT/UPDATE operations.

    2) PurchaseReceipt (purchase_receipts):
       - Add ck_pr_amount_sign_by_return:
            • is_return = false → total_amount >= 0
            • is_return = true  → total_amount <= 0
       - Also created as NOT VALID for safety with historical data.

    We DO NOT touch:
      - ck_pin_return_requires_original
      - ck_pr_return_requires_original

    because they already match the current model expressions.
    """

    # ─────────────────────────────────────────────────────────────
    # 1) PURCHASE INVOICES (purchase_invoices)
    # ─────────────────────────────────────────────────────────────

    # Drop old / conflicting constraints if they exist.
    # IF EXISTS keeps this safe on dev / CI / prod with different histories.
    pin_constraints_to_drop = [
        "ck_pin_amounts_non_negative",        # old: paid_amount >= 0 AND outstanding_amount >= 0
        "ck_pin_amount_consistency",          # will be recreated with same formula
        "ck_pin_payment_consistency",         # old payment rule without signed logic
        "ck_pin_amounts_sign_by_return",      # in case of partial earlier attempts
        "ck_pin_payment_consistency_signed",  # in case of partial earlier attempts
    ]

    for name in pin_constraints_to_drop:
        op.execute(
            f"ALTER TABLE purchase_invoices DROP CONSTRAINT IF EXISTS {name}"
        )

    # Core amount relationship (works for positive or negative)
    op.execute(
        """
        ALTER TABLE purchase_invoices
        ADD CONSTRAINT ck_pin_amount_consistency
        CHECK (
            total_amount = paid_amount + outstanding_amount
        )
        NOT VALID
        """
    )

    # Sign-by-return:
    # • Normal invoice (is_return = false): all amounts >= 0
    # • Return / debit note (is_return = true): all amounts <= 0
    op.execute(
        """
        ALTER TABLE purchase_invoices
        ADD CONSTRAINT ck_pin_amounts_sign_by_return
        CHECK (
            (
                is_return = FALSE
                AND total_amount       >= 0
                AND paid_amount        >= 0
                AND outstanding_amount >= 0
            )
            OR
            (
                is_return = TRUE
                AND total_amount       <= 0
                AND paid_amount        <= 0
                AND outstanding_amount <= 0
            )
        )
        NOT VALID
        """
    )

    # Payment consistency (signed):
    # - No payment: paid_amount = 0 → no MOP / cash-bank
    # - Normal invoice: paid_amount > 0 → require MOP + cash-bank
    # - Return: paid_amount < 0 → require MOP + cash-bank
    op.execute(
        """
        ALTER TABLE purchase_invoices
        ADD CONSTRAINT ck_pin_payment_consistency_signed
        CHECK (
            (
                paid_amount = 0
                AND mode_of_payment_id IS NULL
                AND cash_bank_account_id IS NULL
            )
            OR
            (
                is_return = FALSE
                AND paid_amount > 0
                AND mode_of_payment_id IS NOT NULL
                AND cash_bank_account_id IS NOT NULL
            )
            OR
            (
                is_return = TRUE
                AND paid_amount < 0
                AND mode_of_payment_id IS NOT NULL
                AND cash_bank_account_id IS NOT NULL
            )
        )
        NOT VALID
        """
    )

    # NOTE: we intentionally do NOT touch:
    #   ck_pin_return_requires_original
    # which already matches the model:
    #   (is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)


    # ─────────────────────────────────────────────────────────────
    # 2) PURCHASE RECEIPTS (purchase_receipts)
    # ─────────────────────────────────────────────────────────────

    # Drop old sign constraint if it exists.
    op.execute(
        "ALTER TABLE purchase_receipts "
        "DROP CONSTRAINT IF EXISTS ck_pr_amount_sign_by_return"
    )

    # ERPNext-style sign rule on header total_amount:
    # • Normal receipt: total_amount >= 0
    # • Return: total_amount <= 0
    op.execute(
        """
        ALTER TABLE purchase_receipts
        ADD CONSTRAINT ck_pr_amount_sign_by_return
        CHECK (
            (
                is_return = FALSE
                AND total_amount >= 0
            )
            OR
            (
                is_return = TRUE
                AND total_amount <= 0
            )
        )
        NOT VALID
        """
    )

    # ck_pr_return_requires_original already exists and matches the model:
    #   (is_return = true AND return_against_id IS NOT NULL) OR (is_return = false)
    # so we leave it untouched.


def downgrade():
    """
    Roll back BUYING header doctypes to the older, non-signed behavior.

    PurchaseInvoice:
      - Drop:
          * ck_pin_amount_consistency
          * ck_pin_amounts_sign_by_return
          * ck_pin_payment_consistency_signed
      - Restore:
          * ck_pin_amounts_non_negative
          * ck_pin_amount_consistency
          * ck_pin_payment_consistency

    PurchaseReceipt:
      - Drop:
          * ck_pr_amount_sign_by_return

    We keep:
      - ck_pin_return_requires_original
      - ck_pr_return_requires_original
    unchanged, as they existed before and still match the previous behavior.
    """

    # ─────────────────────────────────────────────────────────────
    # 1) PURCHASE INVOICES (purchase_invoices)
    # ─────────────────────────────────────────────────────────────

    # Drop the new signed constraints
    op.drop_constraint(
        "ck_pin_payment_consistency_signed",
        "purchase_invoices",
        type_="check",
    )
    op.drop_constraint(
        "ck_pin_amounts_sign_by_return",
        "purchase_invoices",
        type_="check",
    )
    op.drop_constraint(
        "ck_pin_amount_consistency",
        "purchase_invoices",
        type_="check",
    )

    # Restore old, simpler behavior

    # Non-negative paid & outstanding
    op.create_check_constraint(
        "ck_pin_amounts_non_negative",
        "purchase_invoices",
        "paid_amount >= 0 AND outstanding_amount >= 0",
    )

    # Simple amount consistency
    op.create_check_constraint(
        "ck_pin_amount_consistency",
        "purchase_invoices",
        "total_amount = paid_amount + outstanding_amount",
    )

    # Old payment consistency (no signed behavior)
    op.create_check_constraint(
        "ck_pin_payment_consistency",
        "purchase_invoices",
        """
        (
            paid_amount = 0
            AND mode_of_payment_id IS NULL
            AND cash_bank_account_id IS NULL
        )
        OR
        (
            paid_amount > 0
            AND mode_of_payment_id IS NOT NULL
            AND cash_bank_account_id IS NOT NULL
        )
        """,
    )

    # ck_pin_return_requires_original is left unchanged.


    # ─────────────────────────────────────────────────────────────
    # 2) PURCHASE RECEIPTS (purchase_receipts)
    # ─────────────────────────────────────────────────────────────

    # Drop the header sign-by-return constraint
    op.drop_constraint(
        "ck_pr_amount_sign_by_return",
        "purchase_receipts",
        type_="check",
    )

    # ck_pr_return_requires_original remains as before.
