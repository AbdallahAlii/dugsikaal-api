"""update sales invoice item check constraints

Revision ID: 3ddfdda4812c
Revises: 780875413fa8
Create Date: 2025-11-18 20:40:24.507026

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  (kept for future edits / consistency)


# revision identifiers, used by Alembic.
revision = "3ddfdda4812c"
down_revision = "780875413fa8"
branch_labels = None
depends_on = None


def upgrade():
    """
    Align sales_invoice_items CHECK constraints with the current model:

      - Allow negative quantities for returns, but forbid zero:
            quantity <> 0
      - Keep non-negative rate:
            rate >= 0

    Also rename constraints to match the SQLAlchemy model names.
    """

    # Drop any existing constraints that clash with the new ones.
    # Using IF EXISTS makes this safe for all environments (old DB, new DB).
    constraint_names_to_drop = [
        "ck_sii_qty_pos",              # old: CHECK (quantity > 0)
        "ck_sii_rate_nonneg",          # old: CHECK (rate >= 0)
        "ck_sii_qty_non_zero",         # in case of partial previous attempts
        "ck_sii_rate_non_negative",    # in case of partial previous attempts
    ]

    for name in constraint_names_to_drop:
        op.execute(
            f"ALTER TABLE sales_invoice_items "
            f"DROP CONSTRAINT IF EXISTS {name}"
        )

    # New constraints that match the current SQLAlchemy model:

    # Rate must be non-negative
    op.create_check_constraint(
        "ck_sii_rate_non_negative",
        "sales_invoice_items",
        "rate >= 0",
    )

    # Quantity cannot be zero (positive for normal sales, negative for returns)
    op.create_check_constraint(
        "ck_sii_qty_non_zero",
        "sales_invoice_items",
        "quantity <> 0",
    )


def downgrade():
    """
    Restore the previous constraint definitions:

      - quantity > 0   (no negative, no zero)
      - rate >= 0
    """

    # Drop the new ones
    op.drop_constraint(
        "ck_sii_qty_non_zero",
        "sales_invoice_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_sii_rate_non_negative",
        "sales_invoice_items",
        type_="check",
    )

    # Recreate the old ones
    op.create_check_constraint(
        "ck_sii_rate_nonneg",
        "sales_invoice_items",
        "rate >= 0",
    )
    op.create_check_constraint(
        "ck_sii_qty_pos",
        "sales_invoice_items",
        "quantity > 0",
    )
