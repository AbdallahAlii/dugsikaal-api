"""update sales invoice check constraints

Revision ID: 780875413fa8
Revises: 73c65bc4dff3
Create Date: 2025-11-18 19:48:22.185785

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  (kept for future edits / consistency)


# revision identifiers, used by Alembic.
revision = "780875413fa8"
down_revision = "73c65bc4dff3"
branch_labels = None
depends_on = None


def upgrade():
    """
    Update CHECK constraints on sales_invoices to match the current
    SalesInvoice model logic for:
      - amount consistency
      - sign-by-return behavior
      - payment consistency
      - VAT consistency

    Constraints are created as NOT VALID so existing historical data
    will not break the migration. They will be enforced for all new
    INSERT/UPDATE operations.
    """

    # ---- 1) Drop any old constraints (if they exist) -----------------------
    # Safe for all environments (dev/prod/CI) because of IF EXISTS.
    constraint_names_to_drop = [
        "ck_sin_amount_consistency",
        "ck_sin_amounts_sign_by_return",
        "ck_sin_payment_consistency",
        "ck_sin_payment_consistency_signed",
        "ck_sin_vat_consistency",
        "ck_sin_vat_consistency_signed",
    ]

    for name in constraint_names_to_drop:
        op.execute(f"ALTER TABLE sales_invoices DROP CONSTRAINT IF EXISTS {name}")

    # ---- 2) Re-create constraints with the NEW logic (NOT VALID) ----------

    # Core amount relationship (works for positive or negative):
    # total_amount = paid_amount + outstanding_amount
    op.execute(
        """
        ALTER TABLE sales_invoices
        ADD CONSTRAINT ck_sin_amount_consistency
        CHECK (
            total_amount = paid_amount + outstanding_amount
        )
        NOT VALID
        """
    )

    # Sign-by-return (ERPNext-style):
    # - Normal invoices: totals and balances are >= 0
    # - Returns (credit notes): totals and balances are <= 0
    op.execute(
        """
        ALTER TABLE sales_invoices
        ADD CONSTRAINT ck_sin_amounts_sign_by_return
        CHECK (
            (
                is_return = FALSE
                AND total_amount >= 0
                AND paid_amount  >= 0
                AND outstanding_amount >= 0
            )
            OR
            (
                is_return = TRUE
                AND total_amount <= 0
                AND paid_amount  <= 0
                AND outstanding_amount <= 0
            )
        )
        NOT VALID
        """
    )

    # Payment consistency (supports refunds with negative paid_amount):
    # - No payment: paid_amount = 0 → no MOP / cash-bank
    # - Normal invoice: paid_amount > 0 → require MOP + cash-bank
    # - Return: paid_amount < 0 (refund) → require MOP + cash-bank
    op.execute(
        """
        ALTER TABLE sales_invoices
        ADD CONSTRAINT ck_sin_payment_consistency_signed
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

    # VAT consistency: any non-zero VAT (positive or negative) needs account + rate
    op.execute(
        """
        ALTER TABLE sales_invoices
        ADD CONSTRAINT ck_sin_vat_consistency_signed
        CHECK (
            (
                vat_amount = 0
                AND vat_account_id IS NULL
                AND vat_rate IS NULL
            )
            OR
            (
                vat_amount <> 0
                AND vat_account_id IS NOT NULL
                AND vat_rate IS NOT NULL
            )
        )
        NOT VALID
        """
    )


def downgrade():
    """
    Roll back to a state with no sales_invoices check constraints created
    by this migration. This keeps downgrade simple and safe.
    """

    op.drop_constraint(
        "ck_sin_vat_consistency_signed",
        "sales_invoices",
        type_="check",
    )
    op.drop_constraint(
        "ck_sin_payment_consistency_signed",
        "sales_invoices",
        type_="check",
    )
    op.drop_constraint(
        "ck_sin_amounts_sign_by_return",
        "sales_invoices",
        type_="check",
    )
    op.drop_constraint(
        "ck_sin_amount_consistency",
        "sales_invoices",
        type_="check",
    )
