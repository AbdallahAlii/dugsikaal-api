"""Refactor workspace navigation & packages

Revision ID: 84ac9a54bd37
Revises: 6d7a32bcc68c
Create Date: 2025-11-23 18:59:55.265351

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '84ac9a54bd37'
down_revision = '6d7a32bcc68c'
branch_labels = None
depends_on = None


def upgrade():
    # -------------------------------------------------------------------------
    # 0. CLEAN UP OLD NAVIGATION TABLES FIRST (avoid index name clashes)
    # -------------------------------------------------------------------------
    # Drop indexes + table: system_nav_visibility
    with op.batch_alter_table('system_nav_visibility', schema=None) as batch_op:
        batch_op.drop_index('ix_system_nav_visibility_company_id')
        batch_op.drop_index('ix_system_nav_visibility_created_at')
        batch_op.drop_index('ix_system_nav_visibility_link_id')
        batch_op.drop_index('ix_system_nav_visibility_updated_at')
        batch_op.drop_index('ix_system_nav_visibility_workspace_id')
        batch_op.drop_index('ix_sysvis_company')
        batch_op.drop_index(
            'uq_sysvis_company_link',
            postgresql_where='(workspace_id IS NULL)'
        )
        batch_op.drop_index(
            'uq_sysvis_company_workspace',
            postgresql_where='(link_id IS NULL)'
        )

    op.drop_table('system_nav_visibility')

    # Drop indexes + table: company_nav_visibility
    with op.batch_alter_table('company_nav_visibility', schema=None) as batch_op:
        batch_op.drop_index('ix_cmpvis_branch')
        batch_op.drop_index('ix_cmpvis_company')
        batch_op.drop_index('ix_cmpvis_user')
        batch_op.drop_index('ix_company_nav_visibility_branch_id')
        batch_op.drop_index('ix_company_nav_visibility_company_id')
        batch_op.drop_index('ix_company_nav_visibility_created_at')
        batch_op.drop_index('ix_company_nav_visibility_link_id')
        batch_op.drop_index('ix_company_nav_visibility_updated_at')
        batch_op.drop_index('ix_company_nav_visibility_user_id')
        batch_op.drop_index('ix_company_nav_visibility_workspace_id')
        batch_op.drop_index(
            'uq_cmpvis_branch_link',
            postgresql_where='((workspace_id IS NULL) AND (branch_id IS NOT NULL) AND (user_id IS NULL))'
        )
        batch_op.drop_index(
            'uq_cmpvis_branch_workspace',
            postgresql_where='((link_id IS NULL) AND (branch_id IS NOT NULL) AND (user_id IS NULL))'
        )
        batch_op.drop_index(
            'uq_cmpvis_co_link',
            postgresql_where='((workspace_id IS NULL) AND (branch_id IS NULL) AND (user_id IS NULL))'
        )
        batch_op.drop_index(
            'uq_cmpvis_co_workspace',
            postgresql_where='((link_id IS NULL) AND (branch_id IS NULL) AND (user_id IS NULL))'
        )
        batch_op.drop_index(
            'uq_cmpvis_user_link',
            postgresql_where='((workspace_id IS NULL) AND (user_id IS NOT NULL))'
        )
        batch_op.drop_index(
            'uq_cmpvis_user_workspace',
            postgresql_where='((link_id IS NULL) AND (user_id IS NOT NULL))'
        )

    op.drop_table('company_nav_visibility')

    # Drop indexes + table: workspace_links
    with op.batch_alter_table('workspace_links', schema=None) as batch_op:
        batch_op.drop_index('ix_workspace_links_created_at')
        batch_op.drop_index('ix_workspace_links_doctype_id')
        batch_op.drop_index('ix_workspace_links_required_action_id')
        batch_op.drop_index('ix_workspace_links_required_permission_str')
        batch_op.drop_index('ix_workspace_links_updated_at')
        batch_op.drop_index('ix_wslink_action')
        batch_op.drop_index('ix_wslink_doctype')
        batch_op.drop_index('ix_wslink_dt_act')
        batch_op.drop_index('ix_wslink_section')
        batch_op.drop_index('ix_wslink_type')
        batch_op.drop_index('ix_wslink_workspace')

    op.drop_table('workspace_links')

    # -------------------------------------------------------------------------
    # 1. NEW TABLES: PACKAGES, PAGES, VISIBILITY, LINKS
    # -------------------------------------------------------------------------
    op.create_table(
        'module_packages',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'extra',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_module_package_slug'),
    )
    with op.batch_alter_table('module_packages', schema=None) as batch_op:
        batch_op.create_index('ix_module_package_is_enabled', ['is_enabled'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_module_packages_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_module_packages_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_module_packages_updated_at'),
            ['updated_at'],
            unique=False,
        )

    op.create_table(
        'package_workspaces',
        sa.Column('package_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['package_id'], ['module_packages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('package_id', 'workspace_id', name='uq_package_workspace'),
    )
    with op.batch_alter_table('package_workspaces', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_package_workspaces_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_package_workspaces_package_id'),
            ['package_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_package_workspaces_updated_at'),
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_package_workspaces_workspace_id'),
            ['workspace_id'],
            unique=False,
        )
        batch_op.create_index('ix_pkgws_package', ['package_id'], unique=False)
        batch_op.create_index('ix_pkgws_workspace', ['workspace_id'], unique=False)

    op.create_table(
        'pages',
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column(
            'kind',
            sa.Enum('PAGE', 'DASHBOARD', 'SETTINGS', name='page_kind_enum'),
            nullable=False,
        ),
        sa.Column('route_path', sa.String(length=255), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('doctype_id', sa.BigInteger(), nullable=True),
        sa.Column('default_action_id', sa.BigInteger(), nullable=True),
        sa.Column('icon', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('keywords', sa.String(length=255), nullable=True),
        sa.Column(
            'extra',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['default_action_id'],
            ['actions.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['doctype_id'],
            ['doc_types.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_path', name='uq_page_route'),
        sa.UniqueConstraint('slug', name='uq_page_slug'),
    )
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.create_index('ix_page_doctype', ['doctype_id'], unique=False)
        batch_op.create_index('ix_page_is_enabled', ['is_enabled'], unique=False)
        batch_op.create_index('ix_page_kind', ['kind'], unique=False)
        batch_op.create_index('ix_page_workspace', ['workspace_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_pages_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_pages_default_action_id'),
            ['default_action_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_pages_doctype_id'),
            ['doctype_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_pages_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_pages_updated_at'),
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_pages_workspace_id'),
            ['workspace_id'],
            unique=False,
        )

    op.create_table(
        'company_package_subscriptions',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('package_id', sa.BigInteger(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'extra',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['companies.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['package_id'],
            ['module_packages.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'package_id', name='uq_company_package'),
    )
    with op.batch_alter_table('company_package_subscriptions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_company_package_subscriptions_company_id'),
            ['company_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_package_subscriptions_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_package_subscriptions_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_package_subscriptions_package_id'),
            ['package_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_package_subscriptions_updated_at'),
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index('ix_cps_company', ['company_id'], unique=False)
        batch_op.create_index('ix_cps_is_enabled', ['is_enabled'], unique=False)
        batch_op.create_index('ix_cps_package', ['package_id'], unique=False)

    op.create_table(
        'system_workspace_visibility',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['companies.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'company_id',
            'workspace_id',
            name='uq_sys_vis_company_workspace',
        ),
    )
    with op.batch_alter_table('system_workspace_visibility', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_system_workspace_visibility_company_id'),
            ['company_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_system_workspace_visibility_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_system_workspace_visibility_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_system_workspace_visibility_updated_at'),
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_system_workspace_visibility_workspace_id'),
            ['workspace_id'],
            unique=False,
        )
        batch_op.create_index('ix_sysvis_company', ['company_id'], unique=False)
        batch_op.create_index('ix_sysvis_workspace', ['workspace_id'], unique=False)

    op.create_table(
        'workspace_page_links',
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('page_id', sa.BigInteger(), nullable=True),
        sa.Column('target_route', sa.String(length=255), nullable=True),
        sa.Column('label', sa.String(length=160), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column(
            'extra',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            '((page_id IS NOT NULL) <> (target_route IS NOT NULL))',
            name='ck_wslink_xor_page_vs_route',
        ),
        sa.ForeignKeyConstraint(
            ['page_id'],
            ['pages.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['section_id'],
            ['workspace_sections.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('workspace_page_links', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_workspace_page_links_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_workspace_page_links_page_id'),
            ['page_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_workspace_page_links_section_id'),
            ['section_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_workspace_page_links_updated_at'),
            ['updated_at'],
            unique=False,
        )

    op.create_table(
        'company_workspace_visibility',
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('workspace_id', sa.BigInteger(), nullable=False),
        sa.Column('branch_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['branch_id'],
            ['branches.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['companies.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'company_id',
            'workspace_id',
            'branch_id',
            'user_id',
            name='uq_cmp_vis_company_workspace_branch_user',
        ),
    )
    with op.batch_alter_table('company_workspace_visibility', schema=None) as batch_op:
        batch_op.create_index('ix_cmpvis_branch', ['branch_id'], unique=False)
        batch_op.create_index('ix_cmpvis_company', ['company_id'], unique=False)
        batch_op.create_index('ix_cmpvis_user', ['user_id'], unique=False)
        batch_op.create_index('ix_cmpvis_workspace', ['workspace_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_branch_id'),
            ['branch_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_company_id'),
            ['company_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_created_at'),
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_updated_at'),
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_user_id'),
            ['user_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_company_workspace_visibility_workspace_id'),
            ['workspace_id'],
            unique=False,
        )

    # -------------------------------------------------------------------------
    # 2. OTHER MODEL TWEAKS (same as autogen)
    # -------------------------------------------------------------------------
    with op.batch_alter_table('general_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column(
            'fiscal_year_id',
            existing_type=sa.BIGINT(),
            nullable=False,
        )

    with op.batch_alter_table('item_groups', schema=None) as batch_op:
        batch_op.alter_column(
            'is_group',
            existing_type=sa.BOOLEAN(),
            comment='True if this is a parent node, False if it holds items.',
            existing_comment='True if parent node.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'default_expense_account_id',
            existing_type=sa.BIGINT(),
            comment='Default account for expense/COGS when buying/selling items in this group.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'default_income_account_id',
            existing_type=sa.BIGINT(),
            comment='Default Income/Sales account.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'default_inventory_account_id',
            existing_type=sa.BIGINT(),
            comment='Default Inventory Asset (Stocks in Hand) account.',
            existing_nullable=True,
        )

    # ITEM PRICES INDEXES – SAFE, idempotent
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_item_price_branch_null
        ON item_prices (price_list_id, item_id, uom_id, valid_from, valid_upto)
        WHERE branch_id IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_item_price_branch_some
        ON item_prices (price_list_id, item_id, uom_id, branch_id, valid_from, valid_upto)
        WHERE branch_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_item_price_lookup_full
        ON item_prices (price_list_id, item_id, uom_id, branch_id, valid_from, valid_upto)
        INCLUDE (rate)
        """
    )

    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.alter_column(
            'item_group_id',
            existing_type=sa.BIGINT(),
            nullable=False,
            existing_comment='Mandatory link for inheriting accounting and inventory rules.',
        )

    with op.batch_alter_table('period_closing_vouchers', schema=None) as batch_op:
        batch_op.alter_column(
            'closing_fiscal_year_id',
            existing_type=sa.BIGINT(),
            comment='The Fiscal Year being closed.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'closing_account_head_id',
            existing_type=sa.BIGINT(),
            comment='The Equity account (Retained Earnings) to book P&L.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'generated_journal_entry_id',
            existing_type=sa.BIGINT(),
            comment='The final Journal Entry for the closing process.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'submitted_by_id',
            existing_type=sa.BIGINT(),
            comment='The User who submitted the voucher (required for SUBMITTED status).',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'code',
            existing_type=sa.VARCHAR(length=100),
            comment='Unique document identifier.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'posting_date',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            comment='The effective date of the closing entry.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'auto_prepared',
            existing_type=sa.BOOLEAN(),
            comment='True if system created this document as a DRAFT for human review.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'total_profit_loss',
            existing_type=sa.NUMERIC(precision=14, scale=4),
            comment='Calculated Net P/L for the year.',
            existing_nullable=False,
        )

    # SAFE, idempotent index on period_closing_vouchers.updated_at
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_period_closing_vouchers_updated_at
        ON period_closing_vouchers (updated_at)
        """
    )

    with op.batch_alter_table('purchase_receipt_items', schema=None) as batch_op:
        batch_op.alter_column(
            'returned_qty',
            existing_type=sa.NUMERIC(precision=12, scale=3),
            comment='Total quantity returned against this item line',
            existing_nullable=False,
            existing_server_default=sa.text('0'),
        )

    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column(
            'base_uom_id',
            existing_type=sa.BIGINT(),
            nullable=False,
            existing_comment='Base UOM for the item (stock UOM)',
        )
        batch_op.alter_column(
            'transaction_uom_id',
            existing_type=sa.BIGINT(),
            comment='UOM used in the transaction (for UOM conversion tracking)',
            existing_comment='UOM used in the transaction',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'transaction_quantity',
            existing_type=sa.NUMERIC(precision=18, scale=6),
            comment='Quantity in transaction UOM (before conversion)',
            existing_comment='Quantity in transaction UOM',
            existing_nullable=True,
        )

    # -------------------------------------------------------------------------
    # 3. SAFE CHANGE: workspace_sections.label -> title
    # -------------------------------------------------------------------------
    # Step 1: add new columns (title nullable for now)
    with op.batch_alter_table('workspace_sections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('title', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('description', sa.String(length=255), nullable=True))
        batch_op.drop_index('ix_ws_section_ws')
        batch_op.create_index('ix_wssection_order', ['order_index'], unique=False)
        batch_op.create_index('ix_wssection_workspace', ['workspace_id'], unique=False)

    # Step 2: copy existing label -> title
    op.execute("UPDATE workspace_sections SET title = label")

    # Step 3: enforce NOT NULL on title and drop old label
    with op.batch_alter_table('workspace_sections', schema=None) as batch_op:
        batch_op.alter_column(
            'title',
            existing_type=sa.String(length=120),
            nullable=False,
        )
        batch_op.drop_column('label')

    # -------------------------------------------------------------------------
    # 4. SAFE CHANGE: workspaces enable flags
    # -------------------------------------------------------------------------
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        # add with defaults so existing rows are valid
        batch_op.add_column(
            sa.Column(
                'is_enabled',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                'is_system_only',
                sa.Boolean(),
                server_default=sa.text('false'),
                nullable=False,
            )
        )
        batch_op.drop_index('ix_workspaces_domain_key')
        batch_op.drop_index('ix_workspaces_feature_flag')
        batch_op.drop_index('ix_ws_status')
        batch_op.drop_index('ix_ws_admin_only')
        batch_op.create_index('ix_ws_admin_only', ['is_system_only'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_workspaces_is_enabled'),
            ['is_enabled'],
            unique=False,
        )
        batch_op.create_index('ix_ws_is_enabled', ['is_enabled'], unique=False)
        batch_op.drop_column('domain_key')
        batch_op.drop_column('status')
        batch_op.drop_column('feature_flag')
        batch_op.drop_column('admin_only')

    # ### end Alembic commands ###


def downgrade():
    # NOTE: Downgrade is kept as generated, except for small corrections to
    #       CheckConstraint strings where parentheses were off, and
    #       idempotent index drops.

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'admin_only',
                sa.BOOLEAN(),
                server_default=sa.text('false'),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                'feature_flag',
                sa.VARCHAR(length=64),
                autoincrement=False,
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                'status',
                postgresql.ENUM('ACTIVE', 'INACTIVE', name='statusenum'),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                'domain_key',
                sa.VARCHAR(length=64),
                autoincrement=False,
                nullable=True,
            )
        )
        batch_op.drop_index('ix_ws_is_enabled')
        batch_op.drop_index(batch_op.f('ix_workspaces_is_enabled'))
        batch_op.drop_index('ix_ws_admin_only')
        batch_op.create_index('ix_ws_admin_only', ['admin_only'], unique=False)
        batch_op.create_index('ix_ws_status', ['status'], unique=False)
        batch_op.create_index('ix_workspaces_feature_flag', ['feature_flag'], unique=False)
        batch_op.create_index('ix_workspaces_domain_key', ['domain_key'], unique=False)
        batch_op.drop_column('is_system_only')
        batch_op.drop_column('is_enabled')

    with op.batch_alter_table('workspace_sections', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'label',
                sa.VARCHAR(length=120),
                autoincrement=False,
                nullable=False,
            )
        )
        batch_op.drop_index('ix_wssection_workspace')
        batch_op.drop_index('ix_wssection_order')
        batch_op.create_index('ix_ws_section_ws', ['workspace_id'], unique=False)
        batch_op.drop_column('description')
        batch_op.drop_column('title')

    with op.batch_alter_table('stock_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column(
            'transaction_quantity',
            existing_type=sa.NUMERIC(precision=18, scale=6),
            comment='Quantity in transaction UOM',
            existing_comment='Quantity in transaction UOM (before conversion)',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'transaction_uom_id',
            existing_type=sa.BIGINT(),
            comment='UOM used in the transaction',
            existing_comment='UOM used in the transaction (for UOM conversion tracking)',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'base_uom_id',
            existing_type=sa.BIGINT(),
            nullable=True,
            existing_comment='Base UOM for the item (stock UOM)',
        )

    with op.batch_alter_table('purchase_receipt_items', schema=None) as batch_op:
        batch_op.alter_column(
            'returned_qty',
            existing_type=sa.NUMERIC(precision=12, scale=3),
            comment=None,
            existing_comment='Total quantity returned against this item line',
            existing_nullable=False,
            existing_server_default=sa.text('0'),
        )

    # Drop ix_period_closing_vouchers_updated_at safely
    op.execute("DROP INDEX IF EXISTS ix_period_closing_vouchers_updated_at")

    with op.batch_alter_table('period_closing_vouchers', schema=None) as batch_op:
        batch_op.alter_column(
            'total_profit_loss',
            existing_type=sa.NUMERIC(precision=14, scale=4),
            comment=None,
            existing_comment='Calculated Net P/L for the year.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'auto_prepared',
            existing_type=sa.BOOLEAN(),
            comment=None,
            existing_comment='True if system created this document as a DRAFT for human review.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'posting_date',
            existing_type=postgresql.TIMESTAMP(timezone=True),
            comment=None,
            existing_comment='The effective date of the closing entry.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'code',
            existing_type=sa.VARCHAR(length=100),
            comment=None,
            existing_comment='Unique document identifier.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'submitted_by_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='The User who submitted the voucher (required for SUBMITTED status).',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'generated_journal_entry_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='The final Journal Entry for the closing process.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'closing_account_head_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='The Equity account (Retained Earnings) to book P&L.',
            existing_nullable=False,
        )
        batch_op.alter_column(
            'closing_fiscal_year_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='The Fiscal Year being closed.',
            existing_nullable=False,
        )

    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.alter_column(
            'item_group_id',
            existing_type=sa.BIGINT(),
            nullable=True,
            existing_comment='Mandatory link for inheriting accounting and inventory rules.',
        )

    # Drop ITEM PRICES indexes safely
    op.execute("DROP INDEX IF EXISTS ix_item_price_lookup_full")
    op.execute("DROP INDEX IF EXISTS ix_item_price_branch_some")
    op.execute("DROP INDEX IF EXISTS ix_item_price_branch_null")

    with op.batch_alter_table('item_groups', schema=None) as batch_op:
        batch_op.alter_column(
            'default_inventory_account_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='Default Inventory Asset (Stocks in Hand) account.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'default_income_account_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='Default Income/Sales account.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'default_expense_account_id',
            existing_type=sa.BIGINT(),
            comment=None,
            existing_comment='Default account for expense/COGS when buying/selling items in this group.',
            existing_nullable=True,
        )
        batch_op.alter_column(
            'is_group',
            existing_type=sa.BOOLEAN(),
            comment='True if parent node.',
            existing_comment='True if this is a parent node, False if it holds items.',
            existing_nullable=False,
        )

    with op.batch_alter_table('general_ledger_entries', schema=None) as batch_op:
        batch_op.alter_column(
            'fiscal_year_id',
            existing_type=sa.BIGINT(),
            nullable=True,
        )

    # recreate old workspace_links
    op.create_table(
        'workspace_links',
        sa.Column('workspace_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('section_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('label', sa.VARCHAR(length=160), autoincrement=False, nullable=False),
        sa.Column(
            'link_type',
            postgresql.ENUM('LIST', 'FORM_NEW', 'REPORT', 'PAGE', 'EXTERNAL', name='navlinktypeenum'),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column('route_path', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
        sa.Column('icon', sa.VARCHAR(length=64), autoincrement=False, nullable=True),
        sa.Column('order_index', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('doctype_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('required_action_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('required_permission_str', sa.VARCHAR(length=180), autoincrement=False, nullable=True),
        sa.Column('keywords', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column(
            'extra',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            'id',
            sa.BIGINT(),
            server_default=sa.text("nextval('workspace_links_id_seq'::regclass)"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.CheckConstraint(
            "((link_type <> 'EXTERNAL'::navlinktypeenum AND route_path::text !~~ 'http%%%%'::text) "
            "OR (link_type = 'EXTERNAL'::navlinktypeenum AND route_path::text ~~ 'http%%%%'::text))",
            name='ck_wslink_route_matches_type',
        ),
        sa.CheckConstraint(
            '((doctype_id IS NOT NULL AND required_action_id IS NOT NULL) OR '
            '(required_permission_str IS NOT NULL) OR '
            '(doctype_id IS NULL AND required_action_id IS NULL AND required_permission_str IS NULL))',
            name='ck_wslink_perm_binding',
        ),
        sa.CheckConstraint(
            '((workspace_id IS NOT NULL) <> (section_id IS NOT NULL))',
            name='ck_wslink_xor_anchor',
        ),
        sa.ForeignKeyConstraint(
            ['doctype_id'],
            ['doc_types.id'],
            name='workspace_links_doctype_id_fkey',
        ),
        sa.ForeignKeyConstraint(
            ['required_action_id'],
            ['actions.id'],
            name='workspace_links_required_action_id_fkey',
        ),
        sa.ForeignKeyConstraint(
            ['section_id'],
            ['workspace_sections.id'],
            name='workspace_links_section_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name='workspace_links_workspace_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='workspace_links_pkey'),
        postgresql_ignore_search_path=False,
    )
    with op.batch_alter_table('workspace_links', schema=None) as batch_op:
        batch_op.create_index('ix_wslink_workspace', ['workspace_id'], unique=False)
        batch_op.create_index('ix_wslink_type', ['link_type'], unique=False)
        batch_op.create_index('ix_wslink_section', ['section_id'], unique=False)
        batch_op.create_index('ix_wslink_dt_act', ['doctype_id', 'required_action_id'], unique=False)
        batch_op.create_index('ix_wslink_doctype', ['doctype_id'], unique=False)
        batch_op.create_index('ix_wslink_action', ['required_action_id'], unique=False)
        batch_op.create_index('ix_workspace_links_updated_at', ['updated_at'], unique=False)
        batch_op.create_index(
            'ix_workspace_links_required_permission_str',
            ['required_permission_str'],
            unique=False,
        )
        batch_op.create_index(
            'ix_workspace_links_required_action_id',
            ['required_action_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_workspace_links_doctype_id',
            ['doctype_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_workspace_links_created_at',
            ['created_at'],
            unique=False,
        )

    op.create_table(
        'company_nav_visibility',
        sa.Column('company_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('branch_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('user_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('workspace_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('link_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('is_enabled', sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.CheckConstraint('company_id IS NOT NULL', name='ck_cmpvis_company_required'),
        sa.CheckConstraint(
            '((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))',
            name='ck_cmpvis_xor_target',
        ),
        sa.ForeignKeyConstraint(
            ['branch_id'],
            ['branches.id'],
            name='company_nav_visibility_branch_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['companies.id'],
            name='company_nav_visibility_company_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['link_id'],
            ['workspace_links.id'],
            name='company_nav_visibility_link_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name='company_nav_visibility_user_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name='company_nav_visibility_workspace_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='company_nav_visibility_pkey'),
    )
    with op.batch_alter_table('company_nav_visibility', schema=None) as batch_op:
        batch_op.create_index(
            'uq_cmpvis_user_workspace',
            ['company_id', 'user_id', 'workspace_id'],
            unique=True,
            postgresql_where='((link_id IS NULL) AND (user_id IS NOT NULL))',
        )
        batch_op.create_index(
            'uq_cmpvis_user_link',
            ['company_id', 'user_id', 'link_id'],
            unique=True,
            postgresql_where='((workspace_id IS NULL) AND (user_id IS NOT NULL))',
        )
        batch_op.create_index(
            'uq_cmpvis_co_workspace',
            ['company_id', 'workspace_id'],
            unique=True,
            postgresql_where='((link_id IS NULL) AND (branch_id IS NULL) AND (user_id IS NULL))',
        )
        batch_op.create_index(
            'uq_cmpvis_co_link',
            ['company_id', 'link_id'],
            unique=True,
            postgresql_where='((workspace_id IS NULL) AND (branch_id IS NULL) AND (user_id IS NULL))',
        )
        batch_op.create_index(
            'uq_cmpvis_branch_workspace',
            ['company_id', 'branch_id', 'workspace_id'],
            unique=True,
            postgresql_where='((link_id IS NULL) AND (branch_id IS NOT NULL) AND (user_id IS NULL))',
        )
        batch_op.create_index(
            'uq_cmpvis_branch_link',
            ['company_id', 'branch_id', 'link_id'],
            unique=True,
            postgresql_where='((workspace_id IS NULL) AND (branch_id IS NOT NULL) AND (user_id IS NULL))',
        )
        batch_op.create_index(
            'ix_company_nav_visibility_workspace_id',
            ['workspace_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_user_id',
            ['user_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_updated_at',
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_link_id',
            ['link_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_created_at',
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_company_id',
            ['company_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_company_nav_visibility_branch_id',
            ['branch_id'],
            unique=False,
        )
        batch_op.create_index('ix_cmpvis_user', ['user_id'], unique=False)
        batch_op.create_index('ix_cmpvis_company', ['company_id'], unique=False)
        batch_op.create_index('ix_cmpvis_branch', ['branch_id'], unique=False)

    op.create_table(
        'system_nav_visibility',
        sa.Column('company_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('workspace_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('link_id', sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column('is_enabled', sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            autoincrement=False,
            nullable=False,
        ),
        sa.CheckConstraint(
            '((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))',
            name='ck_sysvis_xor_target',
        ),
        sa.ForeignKeyConstraint(
            ['company_id'],
            ['companies.id'],
            name='system_nav_visibility_company_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['link_id'],
            ['workspace_links.id'],
            name='system_nav_visibility_link_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name='system_nav_visibility_workspace_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='system_nav_visibility_pkey'),
    )
    with op.batch_alter_table('system_nav_visibility', schema=None) as batch_op:
        batch_op.create_index(
            'uq_sysvis_company_workspace',
            ['company_id', 'workspace_id'],
            unique=True,
            postgresql_where='(link_id IS NULL)',
        )
        batch_op.create_index(
            'uq_sysvis_company_link',
            ['company_id', 'link_id'],
            unique=True,
            postgresql_where='(workspace_id IS NULL)',
        )
        batch_op.create_index('ix_sysvis_company', ['company_id'], unique=False)
        batch_op.create_index(
            'ix_system_nav_visibility_workspace_id',
            ['workspace_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_system_nav_visibility_updated_at',
            ['updated_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_system_nav_visibility_link_id',
            ['link_id'],
            unique=False,
        )
        batch_op.create_index(
            'ix_system_nav_visibility_created_at',
            ['created_at'],
            unique=False,
        )
        batch_op.create_index(
            'ix_system_nav_visibility_company_id',
            ['company_id'],
            unique=False,
        )

    # ### end Alembic commands ###
