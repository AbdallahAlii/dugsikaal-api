"""Add system and company navigation visibility tables

Revision ID: 7652dd6c642b
Revises: 974abaf5a74d
Create Date: 2025-09-15 10:45:03.545462
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ---------- ENUM declarations ----------
# Already exist elsewhere:
status_enum = postgresql.ENUM('Active', 'Inactive', name='statusenum', create_type=False)
docstatus_enum = postgresql.ENUM(
    'DRAFT', 'SUBMITTED', 'CANCELLED', 'UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'RETURNED',
    name='docstatusenum', create_type=False
)

# Introduced / ensured by this migration:
navlink_enum = postgresql.ENUM('LIST', 'FORM_NEW', 'REPORT', 'PAGE', 'EXTERNAL',
                               name='navlinktypeenum', create_type=False)

lcv_alloc_method_enum = postgresql.ENUM('QUANTITY', 'VALUE', 'EQUAL', 'MANUAL',
                                        name='lcvallocationmethodenum', create_type=False)

lcv_charge_type_enum = postgresql.ENUM('FREIGHT', 'INSURANCE', 'DUTY', 'HANDLING', 'OTHER',
                                       name='lcvchargetypeenum', create_type=False)

stock_source_doctype_enum = postgresql.ENUM('PURCHASE_RECEIPT', 'PURCHASE_INVOICE',
                                            name='stocksourcedoctypeenum', create_type=False)

# revision identifiers, used by Alembic.
revision = '7652dd6c642b'
down_revision = '974abaf5a74d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Ensure needed enums exist (safe to call repeatedly)
    navlink_enum.create(bind, checkfirst=True)
    lcv_alloc_method_enum.create(bind, checkfirst=True)
    lcv_charge_type_enum.create(bind, checkfirst=True)
    stock_source_doctype_enum.create(bind, checkfirst=True)

    # --- workspaces
    op.create_table(
        'workspaces',
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('status', status_enum, nullable=False),
        sa.Column('feature_flag', sa.String(length=64), nullable=True),
        sa.Column('domain_key', sa.String(length=64), nullable=True),
        sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_workspace_slug')
    )
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspaces_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_domain_key'), ['domain_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_feature_flag'), ['feature_flag'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('ix_ws_order', ['order_index'], unique=False)
        batch_op.create_index('ix_ws_status', ['status'], unique=False)

    # --- workspace_sections
    op.create_table(
        'workspace_sections',
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workspace_sections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspace_sections_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_sections_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_sections_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('ix_ws_section_ws', ['workspace_id'], unique=False)

    # --- workspace_links
    op.create_table(
        'workspace_links',
        sa.Column('workspace_id', sa.BigInteger(), nullable=True),
        sa.Column('section_id', sa.BigInteger(), nullable=True),
        sa.Column('label', sa.String(length=160), nullable=False),
        sa.Column('link_type', navlink_enum, nullable=False),
        sa.Column('route_path', sa.String(length=255), nullable=False),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('doctype_id', sa.BigInteger(), nullable=True),
        sa.Column('required_action_id', sa.BigInteger(), nullable=True),
        sa.Column('required_permission_str', sa.String(length=180), nullable=True),
        sa.Column('keywords', sa.String(length=255), nullable=True),
        sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("(link_type <> 'EXTERNAL' AND route_path NOT LIKE 'http%%') OR (link_type = 'EXTERNAL' AND route_path LIKE 'http%%')", name='ck_wslink_route_matches_type'),
        sa.CheckConstraint('((workspace_id IS NOT NULL) <> (section_id IS NOT NULL))', name='ck_wslink_xor_anchor'),
        sa.CheckConstraint('((doctype_id IS NOT NULL AND required_action_id IS NOT NULL) OR (required_permission_str IS NOT NULL) OR (doctype_id IS NULL AND required_action_id IS NULL AND required_permission_str IS NULL))', name='ck_wslink_perm_binding'),
        sa.ForeignKeyConstraint(['doctype_id'], ['doc_types.id']),
        sa.ForeignKeyConstraint(['required_action_id'], ['actions.id']),
        sa.ForeignKeyConstraint(['section_id'], ['workspace_sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workspace_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspace_links_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_links_doctype_id'), ['doctype_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_links_required_action_id'), ['required_action_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_links_required_permission_str'), ['required_permission_str'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspace_links_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('ix_wslink_action', ['required_action_id'], unique=False)
        batch_op.create_index('ix_wslink_doctype', ['doctype_id'], unique=False)
        batch_op.create_index('ix_wslink_dt_act', ['doctype_id', 'required_action_id'], unique=False)
        batch_op.create_index('ix_wslink_section', ['section_id'], unique=False)
        batch_op.create_index('ix_wslink_type', ['link_type'], unique=False)
        batch_op.create_index('ix_wslink_workspace', ['workspace_id'], unique=False)

    # --- company_nav_visibility
    op.create_table(
        'company_nav_visibility',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('branch_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('workspace_id', sa.BigInteger(), nullable=True),
        sa.Column('link_id', sa.BigInteger(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))', name='ck_cmpvis_xor_target'),
        sa.CheckConstraint('company_id IS NOT NULL', name='ck_cmpvis_company_required'),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['link_id'], ['workspace_links.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('company_nav_visibility', schema=None) as batch_op:
        batch_op.create_index('ix_cmpvis_branch', ['branch_id'], unique=False)
        batch_op.create_index('ix_cmpvis_company', ['company_id'], unique=False)
        batch_op.create_index('ix_cmpvis_user', ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_link_id'), ['link_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_company_nav_visibility_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('uq_cmpvis_branch_link', ['company_id', 'branch_id', 'link_id'], unique=True, postgresql_where=sa.text('workspace_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL'))
        batch_op.create_index('uq_cmpvis_branch_workspace', ['company_id', 'branch_id', 'workspace_id'], unique=True, postgresql_where=sa.text('link_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL'))
        batch_op.create_index('uq_cmpvis_co_link', ['company_id', 'link_id'], unique=True, postgresql_where=sa.text('workspace_id IS NULL AND branch_id IS NULL AND user_id IS NULL'))
        batch_op.create_index('uq_cmpvis_co_workspace', ['company_id', 'workspace_id'], unique=True, postgresql_where=sa.text('link_id IS NULL AND branch_id IS NULL AND user_id IS NULL'))
        batch_op.create_index('uq_cmpvis_user_link', ['company_id', 'user_id', 'link_id'], unique=True, postgresql_where=sa.text('workspace_id IS NULL AND user_id IS NOT NULL'))
        batch_op.create_index('uq_cmpvis_user_workspace', ['company_id', 'user_id', 'workspace_id'], unique=True, postgresql_where=sa.text('link_id IS NULL AND user_id IS NOT NULL'))

    # --- landed_cost_vouchers
    op.create_table(
        'landed_cost_vouchers',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('branch_id', sa.BigInteger(), nullable=False),
        sa.Column('created_by_id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('posting_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('doc_status', docstatus_enum, nullable=False),
        sa.Column('allocation_method', lcv_alloc_method_enum, nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('charges_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('allocated_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'branch_id', 'code', name='uq_lcv_branch_code')
    )
    with op.batch_alter_table('landed_cost_vouchers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_allocation_method'), ['allocation_method'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_branch_id'), ['branch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_code'), ['code'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_created_by_id'), ['created_by_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_doc_status'), ['doc_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_posting_date'), ['posting_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_landed_cost_vouchers_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('ix_lcv_company_alloc_method', ['company_id', 'allocation_method'], unique=False)
        batch_op.create_index('ix_lcv_company_branch_status', ['company_id', 'branch_id', 'doc_status'], unique=False)
        batch_op.create_index('ix_lcv_company_posting_date', ['company_id', 'posting_date'], unique=False)

    # --- system_nav_visibility
    op.create_table(
        'system_nav_visibility',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=True),
        sa.Column('link_id', sa.BigInteger(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))', name='ck_sysvis_xor_target'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['link_id'], ['workspace_links.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('system_nav_visibility', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_system_nav_visibility_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_system_nav_visibility_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_system_nav_visibility_link_id'), ['link_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_system_nav_visibility_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_system_nav_visibility_workspace_id'), ['workspace_id'], unique=False)
        batch_op.create_index('ix_sysvis_company', ['company_id'], unique=False)
        batch_op.create_index('uq_sysvis_company_link', ['company_id', 'link_id'], unique=True, postgresql_where=sa.text('workspace_id IS NULL'))
        batch_op.create_index('uq_sysvis_company_workspace', ['company_id', 'workspace_id'], unique=True, postgresql_where=sa.text('link_id IS NULL'))

    # --- lcv_allocations
    op.create_table(
        'lcv_allocations',
        sa.Column('lcv_id', sa.BigInteger(), nullable=False),
        sa.Column('doc_type', stock_source_doctype_enum, nullable=False),
        sa.Column('document_item_id', sa.BigInteger(), nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=True),
        sa.Column('uom_id', sa.BigInteger(), nullable=True),
        sa.Column('basis_qty', sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column('basis_amount', sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column('allocated_amount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('allocated_amount >= 0', name='ck_lcvalc_alloc_nonneg'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id']),
        sa.ForeignKeyConstraint(['lcv_id'], ['landed_cost_vouchers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uom_id'], ['units_of_measure.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lcv_id', 'doc_type', 'document_item_id', name='uq_lcvalc_unique')
    )
    with op.batch_alter_table('lcv_allocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lcv_allocations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_doc_type'), ['doc_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_document_item_id'), ['document_item_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_item_id'), ['item_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_lcv_id'), ['lcv_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_uom_id'), ['uom_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_allocations_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('ix_lcvalc_type_item', ['doc_type', 'document_item_id'], unique=False)

    # --- lcv_charges
    op.create_table(
        'lcv_charges',
        sa.Column('lcv_id', sa.BigInteger(), nullable=False),
        sa.Column('charge_type', lcv_charge_type_enum, nullable=False),
        sa.Column('description', sa.String(length=140), nullable=True),
        sa.Column('amount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('expense_account_id', sa.BigInteger(), nullable=True),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_lcvcharge_amount_pos'),
        sa.ForeignKeyConstraint(['expense_account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['lcv_id'], ['landed_cost_vouchers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('lcv_charges', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lcv_charges_charge_type'), ['charge_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_charges_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_charges_expense_account_id'), ['expense_account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_charges_lcv_id'), ['lcv_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_lcv_charges_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('ix_lcvcharge_account', ['expense_account_id'], unique=False)

    # --- stock_entries tweaks
    with op.batch_alter_table('stock_entries', schema=None) as batch_op:
        batch_op.create_index('idx_se_branch_posting', ['branch_id', 'posting_date'], unique=False)
        batch_op.create_index('idx_se_company_posting', ['company_id', 'posting_date'], unique=False)
        batch_op.drop_constraint(batch_op.f('stock_entries_company_id_fkey'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('stock_entries_branch_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'companies', ['company_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key(None, 'branches', ['branch_id'], ['id'], ondelete='RESTRICT')

    # --- stock_entry_items changes (REORDERED to satisfy Postgres rule)
    with op.batch_alter_table('stock_entry_items', schema=None) as batch_op:
        # 1) add rate with a temporary default so NOT NULL passes for existing rows
        batch_op.add_column(sa.Column('rate', sa.Numeric(precision=18, scale=6), nullable=False, server_default='0'))

        # 2) widen quantity BEFORE creating any generated column that references it
        batch_op.alter_column('quantity',
                              existing_type=sa.NUMERIC(precision=10, scale=4),
                              type_=sa.Numeric(precision=18, scale=6),
                              existing_nullable=False)

        # 3) now it’s safe to add the generated column
        batch_op.add_column(sa.Column('amount',
                                      sa.Numeric(precision=18, scale=6),
                                      sa.Computed('quantity * rate', persisted=True),
                                      nullable=False))

        # 4) drop the temporary server default on rate
        batch_op.alter_column('rate', server_default=None)

        # indexes & FK tweaks
        batch_op.create_index('idx_sei_entry_item', ['stock_entry_id', 'item_id'], unique=False)
        batch_op.create_index('idx_sei_item_source_wh', ['item_id', 'source_warehouse_id'], unique=False)
        batch_op.create_index('idx_sei_item_target_wh', ['item_id', 'target_warehouse_id'], unique=False)
        batch_op.create_index('idx_sei_src_tgt', ['source_warehouse_id', 'target_warehouse_id'], unique=False)
        batch_op.drop_constraint(batch_op.f('stock_entry_items_uom_id_fkey'), type_='foreignkey')
        batch_op.create_foreign_key(None, 'units_of_measure', ['uom_id'], ['id'], ondelete='RESTRICT')

    # --- stock_ledger_entries metadata tweaks
    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column('doc_row_id',
                              existing_type=sa.BIGINT(),
                              comment=None,
                              existing_comment='Links to a specific line item on the source document.',
                              existing_nullable=True)
        batch_op.alter_column('qty_before_transaction',
                              existing_type=sa.NUMERIC(precision=18, scale=6),
                              comment=None,
                              existing_comment='Quantity in the warehouse before this transaction.',
                              existing_nullable=True)
        batch_op.alter_column('qty_after_transaction',
                              existing_type=sa.NUMERIC(precision=18, scale=6),
                              comment=None,
                              existing_comment='Quantity in the warehouse after this transaction.',
                              existing_nullable=True)


def downgrade():
    # stock_ledger_entries
    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column('qty_after_transaction',
                              existing_type=sa.NUMERIC(precision=18, scale=6),
                              comment='Quantity in the warehouse after this transaction.',
                              existing_nullable=True)
        batch_op.alter_column('qty_before_transaction',
                              existing_type=sa.NUMERIC(precision=18, scale=6),
                              comment='Quantity in the warehouse before this transaction.',
                              existing_nullable=True)
        batch_op.alter_column('doc_row_id',
                              existing_type=sa.BIGINT(),
                              comment='Links to a specific line item on the source document.',
                              existing_nullable=True)

    # stock_entry_items (reverse order: drop generated column BEFORE narrowing quantity)
    with op.batch_alter_table('stock_entry_items', schema=None) as batch_op:
        # indexes & FK revert
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('stock_entry_items_uom_id_fkey'), 'units_of_measure', ['uom_id'], ['id'])
        batch_op.drop_index('idx_sei_src_tgt')
        batch_op.drop_index('idx_sei_item_target_wh')
        batch_op.drop_index('idx_sei_item_source_wh')
        batch_op.drop_index('idx_sei_entry_item')

        # MUST drop generated 'amount' first or Postgres will block type change
        batch_op.drop_column('amount')

        # now we can narrow quantity again
        batch_op.alter_column('quantity',
                              existing_type=sa.Numeric(precision=18, scale=6),
                              type_=sa.NUMERIC(precision=10, scale=4),
                              existing_nullable=False)

        # finally drop rate
        batch_op.drop_column('rate')

    # stock_entries
    with op.batch_alter_table('stock_entries', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(batch_op.f('stock_entries_branch_id_fkey'), 'branches', ['branch_id'], ['id'])
        batch_op.create_foreign_key(batch_op.f('stock_entries_company_id_fkey'), 'companies', ['company_id'], ['id'])
        batch_op.drop_index('idx_se_company_posting')
        batch_op.drop_index('idx_se_branch_posting')

    # lcv_charges
    with op.batch_alter_table('lcv_charges', schema=None) as batch_op:
        batch_op.drop_index('ix_lcvcharge_account')
        batch_op.drop_index(batch_op.f('ix_lcv_charges_updated_at'))
        batch_op.drop_index(batch_op.f('ix_lcv_charges_lcv_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_charges_expense_account_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_charges_created_at'))
        batch_op.drop_index(batch_op.f('ix_lcv_charges_charge_type'))
    op.drop_table('lcv_charges')

    # lcv_allocations
    with op.batch_alter_table('lcv_allocations', schema=None) as batch_op:
        batch_op.drop_index('ix_lcvalc_type_item')
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_updated_at'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_uom_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_lcv_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_item_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_document_item_id'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_doc_type'))
        batch_op.drop_index(batch_op.f('ix_lcv_allocations_created_at'))
    op.drop_table('lcv_allocations')

    # system_nav_visibility
    with op.batch_alter_table('system_nav_visibility', schema=None) as batch_op:
        batch_op.drop_index('uq_sysvis_company_workspace', postgresql_where=sa.text('link_id IS NULL'))
        batch_op.drop_index('uq_sysvis_company_link', postgresql_where=sa.text('workspace_id IS NULL'))
        batch_op.drop_index('ix_sysvis_company')
        batch_op.drop_index(batch_op.f('ix_system_nav_visibility_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_system_nav_visibility_updated_at'))
        batch_op.drop_index(batch_op.f('ix_system_nav_visibility_link_id'))
        batch_op.drop_index(batch_op.f('ix_system_nav_visibility_created_at'))
        batch_op.drop_index(batch_op.f('ix_system_nav_visibility_company_id'))
    op.drop_table('system_nav_visibility')

    # landed_cost_vouchers
    with op.batch_alter_table('landed_cost_vouchers', schema=None) as batch_op:
        batch_op.drop_index('ix_lcv_company_posting_date')
        batch_op.drop_index('ix_lcv_company_branch_status')
        batch_op.drop_index('ix_lcv_company_alloc_method')
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_updated_at'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_posting_date'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_doc_status'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_created_by_id'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_created_at'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_company_id'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_code'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_branch_id'))
        batch_op.drop_index(batch_op.f('ix_landed_cost_vouchers_allocation_method'))
    op.drop_table('landed_cost_vouchers')

    # company_nav_visibility
    with op.batch_alter_table('company_nav_visibility', schema=None) as batch_op:
        batch_op.drop_index('uq_cmpvis_user_workspace', postgresql_where=sa.text('link_id IS NULL AND user_id IS NOT NULL'))
        batch_op.drop_index('uq_cmpvis_user_link', postgresql_where=sa.text('workspace_id IS NULL AND user_id IS NOT NULL'))
        batch_op.drop_index('uq_cmpvis_co_workspace', postgresql_where=sa.text('link_id IS NULL AND branch_id IS NULL AND user_id IS NULL'))
        batch_op.drop_index('uq_cmpvis_co_link', postgresql_where=sa.text('workspace_id IS NULL AND branch_id IS NULL AND user_id IS NULL'))
        batch_op.drop_index('uq_cmpvis_branch_workspace', postgresql_where=sa.text('link_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL'))
        batch_op.drop_index('uq_cmpvis_branch_link', postgresql_where=sa.text('workspace_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_user_id'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_updated_at'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_link_id'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_created_at'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_company_id'))
        batch_op.drop_index(batch_op.f('ix_company_nav_visibility_branch_id'))
        batch_op.drop_index('ix_cmpvis_user')
        batch_op.drop_index('ix_cmpvis_company')
        batch_op.drop_index('ix_cmpvis_branch')
    op.drop_table('company_nav_visibility')

    # workspace_links
    with op.batch_alter_table('workspace_links', schema=None) as batch_op:
        batch_op.drop_index('ix_wslink_workspace')
        batch_op.drop_index('ix_wslink_type')
        batch_op.drop_index('ix_wslink_section')
        batch_op.drop_index('ix_wslink_dt_act')
        batch_op.drop_index('ix_wslink_doctype')
        batch_op.drop_index('ix_wslink_action')
        batch_op.drop_index(batch_op.f('ix_workspace_links_updated_at'))
        batch_op.drop_index(batch_op.f('ix_workspace_links_required_permission_str'))
        batch_op.drop_index(batch_op.f('ix_workspace_links_required_action_id'))
        batch_op.drop_index(batch_op.f('ix_workspace_links_doctype_id'))
        batch_op.drop_index(batch_op.f('ix_workspace_links_created_at'))
    op.drop_table('workspace_links')

    # workspace_sections
    with op.batch_alter_table('workspace_sections', schema=None) as batch_op:
        batch_op.drop_index('ix_ws_section_ws')
        batch_op.drop_index(batch_op.f('ix_workspace_sections_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_workspace_sections_updated_at'))
        batch_op.drop_index(batch_op.f('ix_workspace_sections_created_at'))
    op.drop_table('workspace_sections')

    # workspaces
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_index('ix_ws_status')
        batch_op.drop_index('ix_ws_order')
        batch_op.drop_index(batch_op.f('ix_workspaces_updated_at'))
        batch_op.drop_index(batch_op.f('ix_workspaces_feature_flag'))
        batch_op.drop_index(batch_op.f('ix_workspaces_domain_key'))
        batch_op.drop_index(batch_op.f('ix_workspaces_created_at'))
    op.drop_table('workspaces')

    # drop only enums created/ensured by this migration
    bind = op.get_bind()
    stock_source_doctype_enum.drop(bind, checkfirst=True)
    lcv_charge_type_enum.drop(bind, checkfirst=True)
    lcv_alloc_method_enum.drop(bind, checkfirst=True)
    navlink_enum.drop(bind, checkfirst=True)
