"""updated model of data import

Revision ID: c4abd6895bda
Revises: 84ac9a54bd37
Create Date: 2025-11-26 21:36:04.616782

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'c4abd6895bda'
down_revision = '84ac9a54bd37'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add the column as NULLABLE so Postgres accepts existing rows
    op.add_column(
        'data_imports',
        sa.Column('code', sa.String(length=100), nullable=True)
    )

    # 2) Backfill existing rows with a generated code
    # You can change the format if you like, but this is deterministic & safe.
    # Uses created_at and id from BaseModel.
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE data_imports
        SET code = CONCAT(
            'DIMP-',
            COALESCE(EXTRACT(YEAR FROM created_at)::text, '0000'),
            '-',
            LPAD(id::text, 4, '0')
        )
        WHERE code IS NULL
    """))

    # 3) Now enforce NOT NULL once all rows have a value
    op.alter_column(
        'data_imports',
        'code',
        existing_type=sa.String(length=100),
        nullable=False
    )

    # 4) Create index on code for fast lookup
    op.create_index(
        'ix_data_imports_code',
        'data_imports',
        ['code'],
        unique=False
    )


def downgrade():
    # Reverse operations in a safe order
    op.drop_index('ix_data_imports_code', table_name='data_imports')
    op.drop_column('data_imports', 'code')
