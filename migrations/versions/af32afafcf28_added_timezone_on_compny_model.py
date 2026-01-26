"""Added timezone on compny model)

Revision ID: af32afafcf28
Revises: 76821fd05507
Create Date: 2025-10-18 11:24:07.895321

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "af32afafcf28"
down_revision = "76821fd05507"
branch_labels = None
depends_on = None


def upgrade():
    # --- 1) Add timezone column to companies ---
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "timezone",
                sa.String(length=50),
                nullable=True,
                comment="IANA Timezone string (e.g., 'America/New_York') for company operations",
            )
        )

    # --- 2) Ensure enum types exist (NO ALTER TYPE / ADD VALUE here) ---
    # This avoids the Postgres 16 "unsafe use of new value" error.
    op.execute(
        """
    DO $$
    BEGIN
        -- Ensure docstatusenum exists
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'docstatusenum') THEN
            CREATE TYPE docstatusenum AS ENUM (
                'DRAFT',
                'SUBMITTED',
                'CANCELLED',
                'UNPAID',
                'PARTIALLY_PAID',
                'PAID',
                'OVERDUE',
                'RETURNED'
            );
        END IF;

        -- Ensure paymenttypeenum exists
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'paymenttypeenum') THEN
            CREATE TYPE paymenttypeenum AS ENUM (
                'PAY',
                'RECEIVE',
                'INTERNAL_TRANSFER'
            );
        END IF;

        -- Ensure partytypeenum exists
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'partytypeenum') THEN
            CREATE TYPE partytypeenum AS ENUM (
                'CUSTOMER',
                'SUPPLIER',
                'EMPLOYEE',
                'SHAREHOLDER',
                'OTHER'
            );
        END IF;
    END $$;
    """
    )

    # --- 3) Convert expenses.doc_status to docstatusenum ---
    op.execute(
        """
    ALTER TABLE expenses 
    ALTER COLUMN doc_status TYPE docstatusenum 
    USING CASE 
        WHEN doc_status = 'DRAFT'          THEN 'DRAFT'::docstatusenum
        WHEN doc_status = 'SUBMITTED'      THEN 'SUBMITTED'::docstatusenum
        WHEN doc_status = 'CANCELLED'      THEN 'CANCELLED'::docstatusenum
        WHEN doc_status = 'UNPAID'         THEN 'UNPAID'::docstatusenum
        WHEN doc_status = 'PARTIALLY_PAID' THEN 'PARTIALLY_PAID'::docstatusenum
        WHEN doc_status = 'PAID'           THEN 'PAID'::docstatusenum
        WHEN doc_status = 'OVERDUE'        THEN 'OVERDUE'::docstatusenum
        WHEN doc_status = 'RETURNED'       THEN 'RETURNED'::docstatusenum
        ELSE 'DRAFT'::docstatusenum
    END;
    """
    )

    # --- 4) Convert payment_entries.doc_status to docstatusenum ---
    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN doc_status TYPE docstatusenum 
    USING CASE 
        WHEN doc_status = 'DRAFT'          THEN 'DRAFT'::docstatusenum
        WHEN doc_status = 'SUBMITTED'      THEN 'SUBMITTED'::docstatusenum
        WHEN doc_status = 'CANCELLED'      THEN 'CANCELLED'::docstatusenum
        WHEN doc_status = 'UNPAID'         THEN 'UNPAID'::docstatusenum
        WHEN doc_status = 'PARTIALLY_PAID' THEN 'PARTIALLY_PAID'::docstatusenum
        WHEN doc_status = 'PAID'           THEN 'PAID'::docstatusenum
        WHEN doc_status = 'OVERDUE'        THEN 'OVERDUE'::docstatusenum
        WHEN doc_status = 'RETURNED'       THEN 'RETURNED'::docstatusenum
        ELSE 'DRAFT'::docstatusenum
    END;
    """
    )

    # --- 5) Convert payment_entries.payment_type to paymenttypeenum ---
    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN payment_type TYPE paymenttypeenum 
    USING CASE 
        WHEN payment_type = 'PAY'              THEN 'PAY'::paymenttypeenum
        WHEN payment_type = 'RECEIVE'          THEN 'RECEIVE'::paymenttypeenum
        WHEN payment_type = 'INTERNAL_TRANSFER' THEN 'INTERNAL_TRANSFER'::paymenttypeenum
        ELSE 'PAY'::paymenttypeenum
    END;
    """
    )

    # --- 6) Convert payment_entries.party_type to partytypeenum ---
    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN party_type TYPE partytypeenum 
    USING CASE 
        WHEN party_type = 'CUSTOMER'    THEN 'CUSTOMER'::partytypeenum
        WHEN party_type = 'SUPPLIER'    THEN 'SUPPLIER'::partytypeenum
        WHEN party_type = 'EMPLOYEE'    THEN 'EMPLOYEE'::partytypeenum
        WHEN party_type = 'SHAREHOLDER' THEN 'SHAREHOLDER'::partytypeenum
        WHEN party_type = 'OTHER'       THEN 'OTHER'::partytypeenum
        ELSE NULL
    END;
    """
    )


def downgrade():
    # Convert enum columns back to VARCHAR
    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN party_type TYPE VARCHAR(20) 
    USING party_type::text;
    """
    )

    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN payment_type TYPE VARCHAR(20) 
    USING payment_type::text;
    """
    )

    op.execute(
        """
    ALTER TABLE payment_entries 
    ALTER COLUMN doc_status TYPE VARCHAR(50) 
    USING doc_status::text;
    """
    )

    op.execute(
        """
    ALTER TABLE expenses 
    ALTER COLUMN doc_status TYPE VARCHAR(50) 
    USING doc_status::text;
    """
    )

    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.drop_column("timezone")

    # We intentionally do NOT drop enum types in downgrade.
