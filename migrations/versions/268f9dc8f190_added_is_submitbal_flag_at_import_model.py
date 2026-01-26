"""added is submitbal flag at import model

Revision ID: 268f9dc8f190
Revises: c4abd6895bda
Create Date: 2025-11-30 08:35:25.369307

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '268f9dc8f190'
down_revision = 'c4abd6895bda'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add the column as nullable first
    op.add_column(
        'data_imports',
        sa.Column('submit_after_import', sa.Boolean(), nullable=True)
    )

    # 2) Backfill existing rows to False (so we don't violate NOT NULL)
    op.execute(
        "UPDATE data_imports SET submit_after_import = FALSE "
        "WHERE submit_after_import IS NULL"
    )

    # 3) Now enforce NOT NULL
    op.alter_column(
        'data_imports',
        'submit_after_import',
        existing_type=sa.Boolean(),
        nullable=False,
    )


def downgrade():
    op.drop_column('data_imports', 'submit_after_import')
