"""corrted sle and Bin model

Revision ID: 974abaf5a74d
Revises: 3257089fb5fa
Create Date: 2025-09-09 20:02:53.734705
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '974abaf5a74d'
down_revision = '3257089fb5fa'
branch_labels = None
depends_on = None


def upgrade():
    # ----------------------------
    # BINS: drop generated, alter, re-add generateds
    # ----------------------------
    with op.batch_alter_table('bins', schema=None) as batch_op:
        # computed column depends on base cols → must drop first
        batch_op.drop_column('projected_qty')

    with op.batch_alter_table('bins', schema=None) as batch_op:
        batch_op.alter_column(
            'actual_qty',
            existing_type=sa.NUMERIC(12, 3),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'reserved_qty',
            existing_type=sa.NUMERIC(12, 3),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'ordered_qty',
            existing_type=sa.NUMERIC(12, 3),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'valuation_rate',
            existing_type=sa.NUMERIC(12, 2),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
        )

    with op.batch_alter_table('bins', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'projected_qty',
                sa.Numeric(18, 6),
                sa.Computed('actual_qty - reserved_qty + ordered_qty', persisted=True),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                'stock_value',
                sa.Numeric(18, 6),
                sa.Computed('actual_qty * valuation_rate', persisted=True),
                nullable=False,
            )
        )

    # ----------------------------
    # STOCK_LEDGER_ENTRIES
    # ----------------------------
    # Create the enum type BEFORE adding the column
    adjustment_enum = sa.Enum(
        'NORMAL', 'LCV', 'RECONCILIATION', 'REVERSAL', 'RETURN', 'TRANSFER',
        name='sleadjustmenttype'
    )
    bind = op.get_bind()
    adjustment_enum.create(bind, checkfirst=True)

    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('outgoing_rate', sa.Numeric(18, 6), nullable=True, comment='Cost for outgoing.'))
        # add with a default so existing rows pass NOT NULL, then drop default
        batch_op.add_column(sa.Column('stock_value_difference', sa.Numeric(20, 6), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('is_cancelled', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        batch_op.add_column(sa.Column('is_reversal', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        batch_op.add_column(sa.Column('reversed_sle_id', sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column('adjustment_type', adjustment_enum, nullable=False, server_default=sa.text("'NORMAL'")))

        batch_op.alter_column(
            'actual_qty',
            existing_type=sa.NUMERIC(10, 4),
            type_=sa.Numeric(18, 6),
            comment='Base UOM delta (+/-).',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'incoming_rate',
            existing_type=sa.NUMERIC(12, 2),
            type_=sa.Numeric(18, 6),
            comment='Cost for incoming.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'valuation_rate',
            existing_type=sa.NUMERIC(12, 2),
            type_=sa.Numeric(18, 6),
            comment='Avg (or layer) value after this row.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'qty_before_transaction',
            existing_type=sa.NUMERIC(10, 4),
            type_=sa.Numeric(18, 6),
            existing_nullable=True,
        )
        batch_op.alter_column(
            'qty_after_transaction',
            existing_type=sa.NUMERIC(10, 4),
            type_=sa.Numeric(18, 6),
            existing_nullable=True,
        )

        batch_op.create_index('ix_sle_replay_scan',
                              ['company_id', 'item_id', 'warehouse_id', 'posting_date', 'posting_time', 'id'],
                              unique=False)
        batch_op.create_index(batch_op.f('ix_stock_ledger_entries_adjustment_type'), ['adjustment_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_ledger_entries_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_ledger_entries_is_cancelled'), ['is_cancelled'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_ledger_entries_is_reversal'), ['is_reversal'], unique=False)
        batch_op.create_index(batch_op.f('ix_stock_ledger_entries_reversed_sle_id'), ['reversed_sle_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_sle_reversed_sle_id',
            'stock_ledger_entries',  # referent table
            ['reversed_sle_id'],     # local column
            ['id'],                  # remote column
            ondelete='SET NULL',
        )

    # Drop temp server defaults added to backfill existing rows
    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column('stock_value_difference', server_default=None)
        batch_op.alter_column('is_cancelled', server_default=None)
        batch_op.alter_column('is_reversal', server_default=None)
        batch_op.alter_column('adjustment_type', server_default=None)


def downgrade():
    # STOCK_LEDGER_ENTRIES revert
    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sle_reversed_sle_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_reversed_sle_id'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_is_reversal'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_is_cancelled'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_branch_id'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_adjustment_type'))
        batch_op.drop_index('ix_sle_replay_scan')

        batch_op.alter_column(
            'qty_after_transaction',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(10, 4),
            existing_nullable=True,
            comment='Quantity in the warehouse after this transaction.',
        )
        batch_op.alter_column(
            'qty_before_transaction',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(10, 4),
            existing_nullable=True,
            comment='Quantity in the warehouse before this transaction.',
        )
        batch_op.alter_column(
            'valuation_rate',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 2),
            existing_nullable=False,
            comment="Item's average valuation rate post-transaction.",
        )
        batch_op.alter_column(
            'incoming_rate',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 2),
            existing_nullable=True,
            comment='Cost of incoming stock. NULL if outgoing.',
        )
        batch_op.alter_column(
            'actual_qty',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(10, 4),
            existing_nullable=False,
            comment='Quantity in Base UOM.',
        )
        batch_op.drop_column('adjustment_type')
        batch_op.drop_column('reversed_sle_id')
        batch_op.drop_column('is_reversal')
        batch_op.drop_column('is_cancelled')
        batch_op.drop_column('stock_value_difference')
        batch_op.drop_column('outgoing_rate')

    # Drop enum type (after column removed)
    adjustment_enum = sa.Enum(
        'NORMAL', 'LCV', 'RECONCILIATION', 'REVERSAL', 'RETURN', 'TRANSFER',
        name='sleadjustmenttype'
    )
    bind = op.get_bind()
    adjustment_enum.drop(bind, checkfirst=True)

    # BINS revert: drop generateds, revert bases, re-add generated
    with op.batch_alter_table('bins', schema=None) as batch_op:
        batch_op.drop_column('stock_value')
        batch_op.drop_column('projected_qty')

    with op.batch_alter_table('bins', schema=None) as batch_op:
        batch_op.alter_column(
            'valuation_rate',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 2),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'ordered_qty',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 3),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'reserved_qty',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 3),
            existing_nullable=False,
        )
        batch_op.alter_column(
            'actual_qty',
            existing_type=sa.Numeric(18, 6),
            type_=sa.NUMERIC(12, 3),
            existing_nullable=False,
        )

    with op.batch_alter_table('bins', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'projected_qty',
                sa.NUMERIC(12, 3),
                sa.Computed('actual_qty - reserved_qty + ordered_qty', persisted=True),
                nullable=False,
            )
        )
