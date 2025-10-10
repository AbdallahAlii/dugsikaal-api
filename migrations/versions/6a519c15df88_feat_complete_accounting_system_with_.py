"""feat: complete accounting system with sales, purchase, inventory and party models

Revision ID: 6a519c15df88
Revises: a37a6aa39905
Create Date: 2025-10-05 13:09:11.558896

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '6a519c15df88'
down_revision = 'a37a6aa39905'
branch_labels = None
depends_on = None

# -------------------------------------------------------------------
# Reuse PostgreSQL ENUMs so we don't re-create existing types
# -------------------------------------------------------------------
docstatus_enum = postgresql.ENUM(
    'DRAFT', 'SUBMITTED', 'CANCELLED', 'UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'RETURNED',
    name='docstatusenum',
    create_type=False,
)

pricelisttype_enum = postgresql.ENUM(
    'BUYING', 'SELLING', 'BOTH',
    name='pricelisttype',
    create_type=False,
)

modeofpaymenttype_enum = postgresql.ENUM(
    'CASH', 'BANK', 'MOBILE_MONEY', 'CREDIT_CARD', 'OTHER',
    name='modeofpaymenttypeenum',
    create_type=False,
)

accountuserole_enum = postgresql.ENUM(
    'CASH_IN', 'CASH_OUT', 'TRANSFER_SOURCE', 'TRANSFER_TARGET', 'EXPENSE',
    name='accountuseroleenum',
    create_type=False,
)

accountruletype_enum = postgresql.ENUM(
    'DEFAULT', 'ALLOW', 'BLOCK',
    name='accountruletypeenum',
    create_type=False,
)


def upgrade():
    # Ensure ENUM types exist once
    bind = op.get_bind()

    postgresql.ENUM(
        'DRAFT', 'SUBMITTED', 'CANCELLED', 'UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'RETURNED',
        name='docstatusenum'
    ).create(bind, checkfirst=True)

    postgresql.ENUM('DRAFT', 'SUBMITTED', 'CANCELLED', 'UNPAID', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', 'RETURNED',
                    name='docstatusenum').create(bind, checkfirst=True)
    postgresql.ENUM('BUYING', 'SELLING', 'BOTH', name='pricelisttype').create(bind, checkfirst=True)
    postgresql.ENUM('CASH', 'BANK', 'MOBILE_MONEY', 'CREDIT_CARD', 'OTHER', name='modeofpaymenttypeenum').create(bind,
                                                                                                                 checkfirst=True)
    postgresql.ENUM('CASH_IN', 'CASH_OUT', 'TRANSFER_SOURCE', 'TRANSFER_TARGET', 'EXPENSE',
                    name='accountuseroleenum').create(bind, checkfirst=True)
    postgresql.ENUM('DEFAULT', 'ALLOW', 'BLOCK', name='accountruletypeenum').create(bind, checkfirst=True)

    # JournalEntryTypeEnum: add "Closing" safely
    op.execute("""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'journalentrytypeenum') THEN
            CREATE TYPE journalentrytypeenum AS ENUM ('General','Opening','Adjustment','Auto','Auto Reversal','Closing');
        ELSIF NOT EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel='Closing' AND enumtypid='journalentrytypeenum'::regtype
        ) THEN
            ALTER TYPE journalentrytypeenum ADD VALUE 'Closing';
        END IF;
    END $$;
    """)

    # ---------- CREATE NEW TABLES ----------
    op.create_table('price_lists',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('name', sa.String(255), nullable=False,
                              comment="e.g., 'Standard Selling Price', 'Wholesale Purchase Price'"),
                    sa.Column('list_type', pricelisttype_enum, nullable=False,
                              comment='Determines if this price list is used for Sales, Purchases, or both.'),
                    sa.Column('currency_code', sa.String(3), nullable=False,
                              comment='ISO currency code (e.g., USD, EUR).'),
                    sa.Column('is_active', sa.Boolean(), nullable=False,
                              comment='A disabled price list cannot be used in new transactions.'),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('company_id', 'name', name='uq_price_list_company_name'),
                    )
    with op.batch_alter_table('price_lists') as b:
        b.create_index('ix_price_list_type_active', ['list_type', 'is_active'])
        b.create_index(b.f('ix_price_lists_company_id'), ['company_id'])
        b.create_index(b.f('ix_price_lists_created_at'), ['created_at'])
        b.create_index(b.f('ix_price_lists_is_active'), ['is_active'])
        b.create_index(b.f('ix_price_lists_updated_at'), ['updated_at'])

    op.create_table('asset_categories',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('name', sa.String(255), nullable=False),
                    sa.Column('code', sa.String(50), nullable=False),
                    sa.Column('description', sa.Text(), nullable=True),
                    sa.Column('fixed_asset_account_id', sa.BigInteger(), nullable=False,
                              comment='The GL account (Asset) to Debit upon acquisition (e.g., 1212 Office Equipment).'),
                    sa.Column('accumulated_depreciation_account_id', sa.BigInteger(), nullable=False,
                              comment='The GL account (Contra-Asset) to Credit for depreciation.'),
                    sa.Column('depreciation_expense_account_id', sa.BigInteger(), nullable=False,
                              comment='The GL account (Expense) to Debit for depreciation.'),
                    sa.Column('depreciation_method', sa.String(50), nullable=False),
                    sa.Column('total_number_of_depreciations', sa.Integer(), nullable=False),
                    sa.Column('frequency_of_depreciation', sa.Integer(), nullable=False),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['accumulated_depreciation_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['depreciation_expense_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['fixed_asset_account_id'], ['accounts.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('company_id', 'code', name='uq_asset_category_company_code'),
                    sa.UniqueConstraint('company_id', 'name', name='uq_asset_category_company_name'),
                    )
    with op.batch_alter_table('asset_categories') as b:
        b.create_index(b.f('ix_asset_categories_accumulated_depreciation_account_id'),
                       ['accumulated_depreciation_account_id'])
        b.create_index(b.f('ix_asset_categories_code'), ['code'])
        b.create_index(b.f('ix_asset_categories_company_id'), ['company_id'])
        b.create_index(b.f('ix_asset_categories_created_at'), ['created_at'])
        b.create_index(b.f('ix_asset_categories_depreciation_expense_account_id'), ['depreciation_expense_account_id'])
        b.create_index(b.f('ix_asset_categories_fixed_asset_account_id'), ['fixed_asset_account_id'])
        b.create_index(b.f('ix_asset_categories_name'), ['name'])
        b.create_index(b.f('ix_asset_categories_updated_at'), ['updated_at'])

    op.create_table('item_groups',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('parent_item_group_id', sa.BigInteger(), nullable=True),
                    sa.Column('name', sa.String(255), nullable=False),
                    sa.Column('code', sa.String(100), nullable=False),
                    sa.Column('is_group', sa.Boolean(), nullable=False, comment='True if parent node.'),
                    sa.Column('default_expense_account_id', sa.BigInteger(), nullable=True),
                    sa.Column('default_income_account_id', sa.BigInteger(), nullable=True),
                    sa.Column('default_inventory_account_id', sa.BigInteger(), nullable=True),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['default_expense_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['default_income_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['default_inventory_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['parent_item_group_id'], ['item_groups.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('company_id', 'code', name='uq_item_group_company_code'),
                    )
    with op.batch_alter_table('item_groups') as b:
        b.create_index('ix_item_group_defaults',
                       ['company_id', 'default_expense_account_id', 'default_income_account_id',
                        'default_inventory_account_id'])
        b.create_index(b.f('ix_item_groups_code'), ['code'])
        b.create_index(b.f('ix_item_groups_company_id'), ['company_id'])
        b.create_index(b.f('ix_item_groups_created_at'), ['created_at'])
        b.create_index(b.f('ix_item_groups_default_expense_account_id'), ['default_expense_account_id'])
        b.create_index(b.f('ix_item_groups_default_income_account_id'), ['default_income_account_id'])
        b.create_index(b.f('ix_item_groups_default_inventory_account_id'), ['default_inventory_account_id'])
        b.create_index(b.f('ix_item_groups_name'), ['name'])
        b.create_index(b.f('ix_item_groups_parent_item_group_id'), ['parent_item_group_id'])
        b.create_index(b.f('ix_item_groups_updated_at'), ['updated_at'])

    op.create_table('modes_of_payment',
                    sa.Column('company_id', sa.BigInteger(), nullable=True),
                    sa.Column('branch_id', sa.BigInteger(), nullable=True),
                    sa.Column('name', sa.String(100), nullable=False),
                    sa.Column('type', modeofpaymenttype_enum, nullable=False),
                    sa.Column('default_account_id', sa.BigInteger(), nullable=True),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['default_account_id'], ['accounts.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('name', 'company_id', 'branch_id',
                                        name='uq_mode_of_payment_name_company_branch'),
                    )
    with op.batch_alter_table('modes_of_payment') as b:
        b.create_index('idx_mop_branch_id', ['branch_id'])
        b.create_index('idx_mop_company_id', ['company_id'])
        b.create_index('idx_mop_default_account', ['default_account_id'])
        b.create_index('idx_mop_type', ['type'])
        b.create_index(b.f('ix_modes_of_payment_branch_id'), ['branch_id'])
        b.create_index(b.f('ix_modes_of_payment_company_id'), ['company_id'])
        b.create_index(b.f('ix_modes_of_payment_created_at'), ['created_at'])
        b.create_index(b.f('ix_modes_of_payment_name'), ['name'])
        b.create_index(b.f('ix_modes_of_payment_updated_at'), ['updated_at'])

    op.create_table('account_selection_rules',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('branch_id', sa.BigInteger(), nullable=True),
                    sa.Column('department_id', sa.BigInteger(), nullable=True),
                    sa.Column('user_id', sa.BigInteger(), nullable=True),
                    sa.Column('role', accountuserole_enum, nullable=False),
                    sa.Column('mode_of_payment_id', sa.BigInteger(), nullable=True),
                    sa.Column('rule_type', accountruletype_enum, nullable=False),
                    sa.Column('account_id', sa.BigInteger(), nullable=True),
                    sa.Column('parent_account_id', sa.BigInteger(), nullable=True),
                    sa.Column('include_children', sa.Boolean(), nullable=False),
                    sa.Column('is_active', sa.Boolean(), nullable=False),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.CheckConstraint(
                        "(rule_type <> 'DEFAULT') OR (account_id IS NOT NULL AND parent_account_id IS NULL AND include_children = false)",
                        name='ck_accrule_default_has_account_only'),
                    sa.CheckConstraint(
                        "(rule_type = 'DEFAULT') OR (account_id IS NOT NULL) OR (parent_account_id IS NOT NULL)",
                        name='ck_accrule_allowblock_has_target'),
                    sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
                    sa.ForeignKeyConstraint(['mode_of_payment_id'], ['modes_of_payment.id']),
                    sa.ForeignKeyConstraint(['parent_account_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['user_id'], ['users.id']),
                    sa.PrimaryKeyConstraint('id'),
                    )
    with op.batch_alter_table('account_selection_rules') as b:
        b.create_index(b.f('ix_account_selection_rules_account_id'), ['account_id'])
        b.create_index(b.f('ix_account_selection_rules_branch_id'), ['branch_id'])
        b.create_index(b.f('ix_account_selection_rules_company_id'), ['company_id'])
        b.create_index(b.f('ix_account_selection_rules_created_at'), ['created_at'])
        b.create_index(b.f('ix_account_selection_rules_department_id'), ['department_id'])
        b.create_index(b.f('ix_account_selection_rules_mode_of_payment_id'), ['mode_of_payment_id'])
        b.create_index(b.f('ix_account_selection_rules_parent_account_id'), ['parent_account_id'])
        b.create_index(b.f('ix_account_selection_rules_role'), ['role'])
        b.create_index(b.f('ix_account_selection_rules_rule_type'), ['rule_type'])
        b.create_index(b.f('ix_account_selection_rules_updated_at'), ['updated_at'])
        b.create_index(b.f('ix_account_selection_rules_user_id'), ['user_id'])
        b.create_index('uq_accrule_allow_account',
                       ['company_id', 'branch_id', 'department_id', 'user_id', 'role', 'mode_of_payment_id',
                        'account_id'], unique=True,
                       postgresql_where=sa.text("rule_type = 'ALLOW' AND account_id IS NOT NULL"))
        b.create_index('uq_accrule_allow_parent',
                       ['company_id', 'branch_id', 'department_id', 'user_id', 'role', 'mode_of_payment_id',
                        'parent_account_id', 'include_children'], unique=True,
                       postgresql_where=sa.text("rule_type = 'ALLOW' AND parent_account_id IS NOT NULL"))
        b.create_index('uq_accrule_default_mop',
                       ['company_id', 'branch_id', 'department_id', 'user_id', 'role', 'mode_of_payment_id'],
                       unique=True,
                       postgresql_where=sa.text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NOT NULL"))
        b.create_index('uq_accrule_default_nomop', ['company_id', 'branch_id', 'department_id', 'user_id', 'role'],
                       unique=True, postgresql_where=sa.text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NULL"))

    op.create_table('period_closing_vouchers',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('closing_fiscal_year_id', sa.BigInteger(), nullable=False),
                    sa.Column('closing_account_head_id', sa.BigInteger(), nullable=False),
                    sa.Column('generated_journal_entry_id', sa.BigInteger(), nullable=True),
                    sa.Column('submitted_by_id', sa.BigInteger(), nullable=True),
                    sa.Column('code', sa.String(100), nullable=False),
                    sa.Column('posting_date', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('doc_status', docstatus_enum, nullable=False),
                    sa.Column('remarks', sa.Text(), nullable=True),
                    sa.Column('auto_prepared', sa.Boolean(), nullable=False),
                    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
                    sa.Column('total_profit_loss', sa.Numeric(14, 4), nullable=False),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.CheckConstraint("NOT (doc_status = 'SUBMITTED' AND submitted_by_id IS NULL)",
                                       name='ck_human_submission_required'),
                    sa.ForeignKeyConstraint(['closing_account_head_id'], ['accounts.id']),
                    sa.ForeignKeyConstraint(['closing_fiscal_year_id'], ['fiscal_years.id']),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['generated_journal_entry_id'], ['journal_entries.id']),
                    sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('closing_fiscal_year_id', 'company_id', name='uq_pcv_fiscal_year_company'),
                    sa.UniqueConstraint('company_id', 'code', name='uq_pcv_company_code'),
                    )
    with op.batch_alter_table('period_closing_vouchers') as b:
        b.create_index('ix_pcv_auto_status', ['auto_prepared', 'doc_status'])
        b.create_index('ix_pcv_company_status', ['company_id', 'doc_status'])
        b.create_index('ix_pcv_posted_date', ['posting_date', 'doc_status'])
        b.create_index(b.f('ix_period_closing_vouchers_auto_prepared'), ['auto_prepared'])
        b.create_index(b.f('ix_period_closing_vouchers_closing_account_head_id'), ['closing_account_head_id'])
        b.create_index(b.f('ix_period_closing_vouchers_closing_fiscal_year_id'), ['closing_fiscal_year_id'])
        b.create_index(b.f('ix_period_closing_vouchers_code'), ['code'])
        b.create_index(b.f('ix_period_closing_vouchers_company_id'), ['company_id'])
        b.create_index(b.f('ix_period_closing_vouchers_created_at'), ['created_at'])
        b.create_index(b.f('ix_period_closing_vouchers_doc_status'), ['doc_status'])
        b.create_index(b.f('ix_period_closing_vouchers_generated_journal_entry_id'), ['generated_journal_entry_id'],
                       unique=True)
        b.create_index(b.f('ix_period_closing_vouchers_posting_date'), ['posting_date'])
        b.create_index(b.f('ix_period_closing_vouchers_submitted_at'), ['submitted_at'])
        b.create_index(b.f('ix_period_closing_vouchers_submitted_by_id'), ['submitted_by_id'])

    op.create_table('assets',
                    sa.Column('company_id', sa.BigInteger(), nullable=False),
                    sa.Column('asset_category_id', sa.BigInteger(), nullable=False),
                    sa.Column('purchase_invoice_id', sa.BigInteger(), nullable=True),
                    sa.Column('item_id', sa.BigInteger(), nullable=True),
                    sa.Column('cost_center_id', sa.BigInteger(), nullable=True),
                    sa.Column('code', sa.String(100), nullable=False),
                    sa.Column('name', sa.String(255), nullable=False),
                    sa.Column('gross_purchase_amount', sa.Numeric(14, 4), nullable=False),
                    sa.Column('expected_salvage_value', sa.Numeric(14, 4), nullable=False),
                    sa.Column('depreciation_start_date', sa.Date(), nullable=False),
                    sa.Column('current_value', sa.Numeric(14, 4), nullable=False),
                    sa.Column('accumulated_depreciation', sa.Numeric(14, 4), nullable=False),
                    sa.Column('status', sa.String(50), nullable=False),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['asset_category_id'], ['asset_categories.id']),
                    sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
                    sa.ForeignKeyConstraint(['cost_center_id'], ['cost_centers.id']),
                    sa.ForeignKeyConstraint(['item_id'], ['items.id']),
                    sa.ForeignKeyConstraint(['purchase_invoice_id'], ['purchase_invoices.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('company_id', 'code', name='uq_asset_company_code'),
                    )
    with op.batch_alter_table('assets') as b:
        b.create_index('ix_asset_status', ['status'])
        b.create_index(b.f('ix_assets_asset_category_id'), ['asset_category_id'])
        b.create_index(b.f('ix_assets_code'), ['code'])
        b.create_index(b.f('ix_assets_company_id'), ['company_id'])
        b.create_index(b.f('ix_assets_cost_center_id'), ['cost_center_id'])
        b.create_index(b.f('ix_assets_created_at'), ['created_at'])
        b.create_index(b.f('ix_assets_item_id'), ['item_id'])
        b.create_index(b.f('ix_assets_purchase_invoice_id'), ['purchase_invoice_id'])
        b.create_index(b.f('ix_assets_updated_at'), ['updated_at'])

    op.create_table('item_prices',
                    sa.Column('item_id', sa.BigInteger(), nullable=False),
                    sa.Column('price_list_id', sa.BigInteger(), nullable=False),
                    sa.Column('branch_id', sa.BigInteger(), nullable=True),
                    sa.Column('uom_id', sa.BigInteger(), nullable=True),
                    sa.Column('rate', sa.Numeric(14, 4), nullable=False),
                    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
                    sa.Column('valid_upto', sa.DateTime(timezone=True), nullable=True),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
                    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['price_list_id'], ['price_lists.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['uom_id'], ['units_of_measure.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('price_list_id', 'item_id', 'uom_id', 'branch_id',
                                        name='uq_item_price_branch_unique'),
                    )
    with op.batch_alter_table('item_prices') as b:
        b.create_index('ix_item_price_lookup', ['item_id', 'price_list_id', 'branch_id'])
        b.create_index('ix_item_price_uom', ['item_id', 'uom_id', 'price_list_id'])
        b.create_index('ix_item_price_validity', ['valid_from', 'valid_upto'])
        b.create_index(b.f('ix_item_prices_branch_id'), ['branch_id'])
        b.create_index(b.f('ix_item_prices_created_at'), ['created_at'])
        b.create_index(b.f('ix_item_prices_item_id'), ['item_id'])
        b.create_index(b.f('ix_item_prices_price_list_id'), ['price_list_id'])
        b.create_index(b.f('ix_item_prices_uom_id'), ['uom_id'])
        b.create_index(b.f('ix_item_prices_updated_at'), ['updated_at'])

    op.create_table('asset_depreciation_entries',
                    sa.Column('asset_id', sa.BigInteger(), nullable=False),
                    sa.Column('journal_entry_id', sa.BigInteger(), nullable=True),
                    sa.Column('posting_date', sa.DateTime(timezone=True), nullable=False),
                    sa.Column('depreciation_amount', sa.Numeric(14, 4), nullable=False),
                    sa.Column('accumulated_depreciation_after', sa.Numeric(14, 4), nullable=False),
                    sa.Column('current_value_after', sa.Numeric(14, 4), nullable=False),
                    sa.Column('remarks', sa.String(255), nullable=True),
                    sa.Column('id', sa.BigInteger(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
                    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id']),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('asset_id', 'posting_date', name='uq_ade_asset_posting_date'),
                    )
    with op.batch_alter_table('asset_depreciation_entries') as b:
        b.create_index(b.f('ix_asset_depreciation_entries_asset_id'), ['asset_id'])
        b.create_index(b.f('ix_asset_depreciation_entries_created_at'), ['created_at'])
        b.create_index(b.f('ix_asset_depreciation_entries_journal_entry_id'), ['journal_entry_id'])
        b.create_index(b.f('ix_asset_depreciation_entries_posting_date'), ['posting_date'])
        b.create_index(b.f('ix_asset_depreciation_entries_updated_at'), ['updated_at'])

    # ---------- DROP OLD TABLES (CHILD FIRST) ----------
    # purchase returns
    with op.batch_alter_table('purchase_return_items') as b:
        b.drop_index('ix_pret_item')
        b.drop_index('ix_purchase_return_items_batch_number')
        b.drop_index('ix_purchase_return_items_created_at')
        b.drop_index('ix_purchase_return_items_invoice_item_id')
        b.drop_index('ix_purchase_return_items_item_id')
        b.drop_index('ix_purchase_return_items_purchase_return_id')
        b.drop_index('ix_purchase_return_items_receipt_item_id')
        b.drop_index('ix_purchase_return_items_uom_id')
        b.drop_index('ix_purchase_return_items_updated_at')
    op.drop_table('purchase_return_items')

    with op.batch_alter_table('purchase_returns') as b:
        b.drop_index('ix_pret_company_branch_status')
        b.drop_index('ix_pret_company_posting_date')
        b.drop_index('ix_pret_company_supplier')
        b.drop_index('ix_purchase_returns_branch_id')
        b.drop_index('ix_purchase_returns_code')
        b.drop_index('ix_purchase_returns_company_id')
        b.drop_index('ix_purchase_returns_created_at')
        b.drop_index('ix_purchase_returns_created_by_id')
        b.drop_index('ix_purchase_returns_doc_status')
        b.drop_index('ix_purchase_returns_invoice_id')
        b.drop_index('ix_purchase_returns_posting_date')
        b.drop_index('ix_purchase_returns_receipt_id')
        b.drop_index('ix_purchase_returns_supplier_id')
        b.drop_index('ix_purchase_returns_updated_at')
        b.drop_index('ix_purchase_returns_warehouse_id')
    op.drop_table('purchase_returns')

    # sales returns
    with op.batch_alter_table('sales_return_items') as b:
        b.drop_index('ix_sales_return_items_batch_number')
        b.drop_index('ix_sales_return_items_created_at')
        b.drop_index('ix_sales_return_items_delivery_note_item_id')
        b.drop_index('ix_sales_return_items_invoice_item_id')
        b.drop_index('ix_sales_return_items_item_id')
        b.drop_index('ix_sales_return_items_sales_return_id')
        b.drop_index('ix_sales_return_items_uom_id')
        b.drop_index('ix_sales_return_items_updated_at')
        b.drop_index('ix_sret_item')
    op.drop_table('sales_return_items')

    with op.batch_alter_table('sales_returns') as b:
        b.drop_index('ix_sales_returns_branch_id')
        b.drop_index('ix_sales_returns_code')
        b.drop_index('ix_sales_returns_company_id')
        b.drop_index('ix_sales_returns_created_at')
        b.drop_index('ix_sales_returns_created_by_id')
        b.drop_index('ix_sales_returns_customer_id')
        b.drop_index('ix_sales_returns_delivery_note_id')
        b.drop_index('ix_sales_returns_doc_status')
        b.drop_index('ix_sales_returns_invoice_id')
        b.drop_index('ix_sales_returns_posting_date')
        b.drop_index('ix_sales_returns_updated_at')
        b.drop_index('ix_sales_returns_warehouse_id')
        b.drop_index('ix_sret_company_branch_status')
        b.drop_index('ix_sret_company_customer')
        b.drop_index('ix_sret_company_posting_date')
    op.drop_table('sales_returns')

    # old branch item pricing
    with op.batch_alter_table('branch_item_pricing') as b:
        b.drop_index('ix_branch_item_pricing_company_id')
        b.drop_index('ix_branch_item_pricing_created_at')
        b.drop_index('ix_branch_item_pricing_updated_at')
    op.drop_table('branch_item_pricing')

    # ---------- EXISTING TABLE ALTERATIONS (DATA-SAFE) ----------
    with op.batch_alter_table('bins') as b:
        b.create_index('idx_bin_item_company', ['item_id', 'company_id'])

    with op.batch_alter_table('fiscal_years') as b:
        b.add_column(sa.Column('name', sa.String(100), nullable=False,
                               comment="User-friendly name (e.g., 'FY 2024' or '2024-2025')"))
        b.add_column(
            sa.Column('is_short_year', sa.Boolean(), nullable=False, comment='True if period is less than 12 months.'))
        b.drop_index('ix_fiscal_years_year')
        b.drop_constraint('uq_fiscal_year_company', type_='unique')
        b.create_index(b.f('ix_fiscal_years_end_date'), ['end_date'])
        b.create_index(b.f('ix_fiscal_years_name'), ['name'])
        b.create_index(b.f('ix_fiscal_years_start_date'), ['start_date'])
        b.create_index(b.f('ix_fiscal_years_status'), ['status'])
        b.create_index('ix_fy_company_dates', ['company_id', 'start_date', 'end_date'])
        b.create_index('ix_fy_company_status', ['company_id', 'status'])
        b.create_index('ix_fy_dates_range', ['start_date', 'end_date'])
        b.create_unique_constraint('uq_fiscal_year_company_name', ['company_id', 'name'])
        b.drop_column('year')

    # NOTE: make new cols nullable or give safe defaults
    with op.batch_alter_table('general_ledger_entries') as b:
        b.add_column(sa.Column('fiscal_year_id', sa.BigInteger(), nullable=True))  # backfill later then tighten
        b.create_index(b.f('ix_general_ledger_entries_fiscal_year_id'), ['fiscal_year_id'])
        b.create_index('ix_gle_company_account_fy_date', ['company_id', 'account_id', 'fiscal_year_id', 'posting_date'])
        b.create_index('ix_gle_debit_credit', ['debit', 'credit'])
        b.create_index('ix_gle_fy_account', ['fiscal_year_id', 'account_id'])
        b.create_foreign_key(None, 'fiscal_years', ['fiscal_year_id'], ['id'])

    with op.batch_alter_table('items') as b:
        # Make item_group_id nullable to avoid failing on existing rows
        b.add_column(sa.Column('item_group_id', sa.BigInteger(), nullable=True,
                               comment='Mandatory link for inheriting accounting and inventory rules.'))
        b.add_column(sa.Column('asset_category_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('is_fixed_asset', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.create_index('ix_item_base_uom', ['base_uom_id', 'status'])
        b.create_index('ix_item_company_status', ['company_id', 'status'])
        b.create_index('ix_item_fks', ['item_group_id', 'brand_id', 'base_uom_id'])
        b.create_index('ix_item_sku_status', ['sku', 'status'])
        b.create_index(b.f('ix_items_asset_category_id'), ['asset_category_id'])
        b.create_index(b.f('ix_items_base_uom_id'), ['base_uom_id'])
        b.create_index(b.f('ix_items_brand_id'), ['brand_id'])
        b.create_index(b.f('ix_items_is_fixed_asset'), ['is_fixed_asset'])
        b.create_index(b.f('ix_items_item_group_id'), ['item_group_id'])
        b.create_index(b.f('ix_items_status'), ['status'])
        b.create_foreign_key(None, 'item_groups', ['item_group_id'], ['id'])
        b.create_foreign_key(None, 'asset_categories', ['asset_category_id'], ['id'])
    # drop default to keep schema clean
    op.alter_column('items', 'is_fixed_asset', server_default=None)

    with op.batch_alter_table('journal_entries') as b:
        b.create_index('ix_je_company_date', ['company_id', 'posting_date'])
        b.create_index('ix_je_entry_type', ['entry_type', 'posting_date'])
        b.create_index('ix_je_fy_status', ['fiscal_year_id', 'doc_status'])

    with op.batch_alter_table('purchase_invoice_items') as b:
        b.add_column(sa.Column('return_against_item_id', sa.BigInteger(), nullable=True))
        b.create_index('ix_pii_return_against', ['return_against_item_id'])
        b.create_index(b.f('ix_purchase_invoice_items_return_against_item_id'), ['return_against_item_id'])
        b.create_foreign_key(None, 'purchase_invoice_items', ['return_against_item_id'], ['id'])

    with op.batch_alter_table('purchase_invoices') as b:
        b.add_column(sa.Column('return_against_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('payable_account_id', sa.BigInteger(), nullable=False))
        b.add_column(sa.Column('mode_of_payment_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('cash_bank_account_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('is_return', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('is_debit_note', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('paid_amount', sa.Numeric(14, 4), nullable=False, server_default='0'))
        b.add_column(sa.Column('outstanding_amount', sa.Numeric(14, 4), nullable=False, server_default='0'))
        b.create_index('ix_pin_cash_bank_account', ['cash_bank_account_id'])
        b.create_index('ix_pin_is_return', ['is_return'])
        b.create_index('ix_pin_mode_of_payment', ['mode_of_payment_id'])
        b.create_index('ix_pin_payable_account', ['payable_account_id'])
        b.create_index(b.f('ix_purchase_invoices_cash_bank_account_id'), ['cash_bank_account_id'])
        b.create_index(b.f('ix_purchase_invoices_is_debit_note'), ['is_debit_note'])
        b.create_index(b.f('ix_purchase_invoices_is_return'), ['is_return'])
        b.create_index(b.f('ix_purchase_invoices_mode_of_payment_id'), ['mode_of_payment_id'])
        b.create_index(b.f('ix_purchase_invoices_payable_account_id'), ['payable_account_id'])
        b.create_index(b.f('ix_purchase_invoices_return_against_id'), ['return_against_id'])
        b.create_foreign_key(None, 'accounts', ['cash_bank_account_id'], ['id'])
        b.create_foreign_key(None, 'modes_of_payment', ['mode_of_payment_id'], ['id'])
        b.create_foreign_key(None, 'purchase_invoices', ['return_against_id'], ['id'])
        b.create_foreign_key(None, 'accounts', ['payable_account_id'], ['id'])
        b.drop_column('balance_due')
        b.drop_column('amount_paid')
    op.alter_column('purchase_invoices', 'is_return', server_default=None)
    op.alter_column('purchase_invoices', 'is_debit_note', server_default=None)
    op.alter_column('purchase_invoices', 'paid_amount', server_default=None)
    op.alter_column('purchase_invoices', 'outstanding_amount', server_default=None)

    with op.batch_alter_table('purchase_receipt_items') as b:
        b.add_column(sa.Column('return_against_item_id', sa.BigInteger(), nullable=True))
        b.create_index('ix_pri_return_against', ['return_against_item_id'])
        b.create_index(b.f('ix_purchase_receipt_items_return_against_item_id'), ['return_against_item_id'])
        b.create_foreign_key(None, 'purchase_receipt_items', ['return_against_item_id'], ['id'])

    with op.batch_alter_table('purchase_receipts') as b:
        b.add_column(sa.Column('return_against_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('is_return', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.create_index('ix_pr_is_return', ['is_return'])
        b.create_index(b.f('ix_purchase_receipts_is_return'), ['is_return'])
        b.create_index(b.f('ix_purchase_receipts_return_against_id'), ['return_against_id'])
        b.create_foreign_key(None, 'purchase_receipts', ['return_against_id'], ['id'])
    op.alter_column('purchase_receipts', 'is_return', server_default=None)

    with op.batch_alter_table('sales_delivery_note_items') as b:
        b.add_column(sa.Column('return_against_item_id', sa.BigInteger(), nullable=True))
        b.create_index(b.f('ix_sales_delivery_note_items_return_against_item_id'), ['return_against_item_id'])
        b.create_index('ix_sdni_return_against', ['return_against_item_id'])
        b.create_foreign_key(None, 'sales_delivery_note_items', ['return_against_item_id'], ['id'])

    with op.batch_alter_table('sales_delivery_notes') as b:
        b.add_column(sa.Column('return_against_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('is_return', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.create_index(b.f('ix_sales_delivery_notes_is_return'), ['is_return'])
        b.create_index(b.f('ix_sales_delivery_notes_return_against_id'), ['return_against_id'])
        b.create_index('ix_sdn_is_return', ['is_return'])
        b.create_foreign_key(None, 'sales_delivery_notes', ['return_against_id'], ['id'])
    op.alter_column('sales_delivery_notes', 'is_return', server_default=None)

    with op.batch_alter_table('sales_invoice_items') as b:
        b.add_column(sa.Column('return_against_item_id', sa.BigInteger(), nullable=True))
        b.create_index(b.f('ix_sales_invoice_items_return_against_item_id'), ['return_against_item_id'])
        b.create_index('ix_sii_return_against', ['return_against_item_id'])
        b.create_foreign_key(None, 'sales_invoice_items', ['return_against_item_id'], ['id'])

    with op.batch_alter_table('sales_invoices') as b:
        b.add_column(sa.Column('return_against_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('vat_account_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('vat_amount', sa.Numeric(14, 4), nullable=False, server_default='0'))
        b.add_column(sa.Column('mode_of_payment_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('cash_bank_account_id', sa.BigInteger(), nullable=True))
        b.add_column(sa.Column('is_return', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('is_credit_note', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('is_pos', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('send_sms', sa.Boolean(), nullable=False, server_default=sa.text('false')))
        b.add_column(sa.Column('paid_amount', sa.Numeric(14, 4), nullable=False, server_default='0'))
        b.add_column(sa.Column('outstanding_amount', sa.Numeric(14, 4), nullable=False, server_default='0'))
        b.create_index(b.f('ix_sales_invoices_cash_bank_account_id'), ['cash_bank_account_id'])
        b.create_index(b.f('ix_sales_invoices_is_credit_note'), ['is_credit_note'])
        b.create_index(b.f('ix_sales_invoices_is_pos'), ['is_pos'])
        b.create_index(b.f('ix_sales_invoices_is_return'), ['is_return'])
        b.create_index(b.f('ix_sales_invoices_mode_of_payment_id'), ['mode_of_payment_id'])
        b.create_index(b.f('ix_sales_invoices_return_against_id'), ['return_against_id'])
        b.create_index(b.f('ix_sales_invoices_send_sms'), ['send_sms'])
        b.create_index(b.f('ix_sales_invoices_vat_account_id'), ['vat_account_id'])
        b.create_index('ix_sin_cash_bank_account', ['cash_bank_account_id'])
        b.create_index('ix_sin_is_pos', ['is_pos'])
        b.create_index('ix_sin_is_return', ['is_return'])
        b.create_index('ix_sin_mode_of_payment', ['mode_of_payment_id'])
        b.create_index('ix_sin_vat_account', ['vat_account_id'])
        b.create_foreign_key(None, 'sales_invoices', ['return_against_id'], ['id'])
        b.create_foreign_key(None, 'accounts', ['vat_account_id'], ['id'])
        b.create_foreign_key(None, 'modes_of_payment', ['mode_of_payment_id'], ['id'])
        b.create_foreign_key(None, 'accounts', ['cash_bank_account_id'], ['id'])
        b.drop_column('balance_due')
        b.drop_column('amount_paid')
    op.alter_column('sales_invoices', 'vat_amount', server_default=None)
    op.alter_column('sales_invoices', 'is_return', server_default=None)
    op.alter_column('sales_invoices', 'is_credit_note', server_default=None)
    op.alter_column('sales_invoices', 'is_pos', server_default=None)
    op.alter_column('sales_invoices', 'send_sms', server_default=None)
    op.alter_column('sales_invoices', 'paid_amount', server_default=None)
    op.alter_column('sales_invoices', 'outstanding_amount', server_default=None)

    with op.batch_alter_table('stock_entries') as b:
        b.create_index('idx_se_type_status', ['stock_entry_type', 'doc_status'])

    with op.batch_alter_table('stock_entry_items') as b:
        b.create_index('idx_sei_item_uom', ['item_id', 'uom_id'])

    with op.batch_alter_table('stock_ledger_entries') as b:
        # base_uom_id made nullable to avoid failing on existing SLE rows
        b.add_column(
            sa.Column('base_uom_id', sa.BigInteger(), nullable=True, comment='Base UOM for the item (stock UOM)'))
        b.add_column(
            sa.Column('transaction_uom_id', sa.BigInteger(), nullable=True, comment='UOM used in the transaction'))
        b.add_column(
            sa.Column('transaction_quantity', sa.Numeric(18, 6), nullable=True, comment='Quantity in transaction UOM'))
        b.add_column(sa.Column('stock_entry_id', sa.BigInteger(), nullable=True,
                               comment='Link to Stock Entry for direct tracing'))
        b.create_index('ix_sle_stock_entry', ['stock_entry_id'])
        b.create_index('ix_sle_uom_tracking', ['item_id', 'base_uom_id', 'transaction_uom_id'])
        b.create_index(b.f('ix_stock_ledger_entries_base_uom_id'), ['base_uom_id'])
        b.create_index(b.f('ix_stock_ledger_entries_stock_entry_id'), ['stock_entry_id'])
        b.create_index(b.f('ix_stock_ledger_entries_transaction_uom_id'), ['transaction_uom_id'])
        b.create_foreign_key(None, 'units_of_measure', ['transaction_uom_id'], ['id'])
        b.create_foreign_key(None, 'stock_entries', ['stock_entry_id'], ['id'])
        b.create_foreign_key(None, 'units_of_measure', ['base_uom_id'], ['id'])

    with op.batch_alter_table('stock_reconciliation_items') as b:
        b.alter_column('quantity', existing_type=sa.NUMERIC(12, 3), type_=sa.Numeric(18, 6), existing_nullable=False)
        b.alter_column('valuation_rate', existing_type=sa.NUMERIC(12, 2), type_=sa.Numeric(18, 6),
                       existing_nullable=True)

    with op.batch_alter_table('units_of_measure') as b:
        b.create_index('ix_uom_name_symbol', ['name', 'symbol'])

    with op.batch_alter_table('uom_conversions') as b:
        b.add_column(sa.Column('uom_id', sa.BigInteger(), nullable=False))
        b.add_column(sa.Column('is_active', sa.Boolean(), nullable=False))
        b.alter_column('conversion_factor', existing_type=sa.NUMERIC(10, 4), type_=sa.Numeric(18, 6),
                       comment='1 [This UOM] = conversion_factor [Stock UOM]', existing_nullable=False)
        b.drop_index('ix_uom_conversions_company_id')
        b.drop_constraint('uq_uom_conversion', type_='unique')
        b.create_index('ix_uom_conv_active', ['item_id', 'is_active'])
        b.create_index('ix_uom_conv_fast', ['item_id', 'uom_id', 'is_active', 'conversion_factor'])
        b.create_index('ix_uom_conv_item_lookup', ['item_id', 'uom_id'])
        b.create_index(b.f('ix_uom_conversions_is_active'), ['is_active'])
        b.create_index(b.f('ix_uom_conversions_item_id'), ['item_id'])
        b.create_index(b.f('ix_uom_conversions_uom_id'), ['uom_id'])
        b.create_unique_constraint('uq_uom_conv_item_uom', ['item_id', 'uom_id'])
        b.drop_constraint('uom_conversions_to_uom_id_fkey', type_='foreignkey')
        b.drop_constraint('uom_conversions_company_id_fkey', type_='foreignkey')
        b.drop_constraint('uom_conversions_from_uom_id_fkey', type_='foreignkey')
        b.create_foreign_key(None, 'units_of_measure', ['uom_id'], ['id'])
        b.drop_column('company_id')
        b.drop_column('from_uom_id')
        b.drop_column('to_uom_id')


def downgrade():
    # Reverse of upgrade. Important: create parents first, then children.

    # uom_conversions
    with op.batch_alter_table('uom_conversions') as batch_op:
        batch_op.add_column(sa.Column('to_uom_id', sa.BIGINT(), nullable=False))
        batch_op.add_column(sa.Column('from_uom_id', sa.BIGINT(), nullable=False))
        batch_op.add_column(sa.Column('company_id', sa.BIGINT(), nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key('uom_conversions_from_uom_id_fkey', 'units_of_measure', ['from_uom_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key('uom_conversions_company_id_fkey', 'companies', ['company_id'], ['id'])
        batch_op.create_foreign_key('uom_conversions_to_uom_id_fkey', 'units_of_measure', ['to_uom_id'], ['id'], ondelete='RESTRICT')
        batch_op.drop_constraint('uq_uom_conv_item_uom', type_='unique')
        batch_op.drop_index(batch_op.f('ix_uom_conversions_uom_id'))
        batch_op.drop_index(batch_op.f('ix_uom_conversions_item_id'))
        batch_op.drop_index(batch_op.f('ix_uom_conversions_is_active'))
        batch_op.drop_index('ix_uom_conv_item_lookup')
        batch_op.drop_index('ix_uom_conv_fast')
        batch_op.drop_index('ix_uom_conv_active')
        batch_op.create_unique_constraint('uq_uom_conversion', ['item_id', 'from_uom_id', 'to_uom_id'])
        batch_op.create_index('ix_uom_conversions_company_id', ['company_id'])
        batch_op.alter_column('conversion_factor',
               existing_type=sa.Numeric(precision=18, scale=6),
               type_=sa.NUMERIC(precision=10, scale=4),
               comment=None,
               existing_comment='1 [This UOM] = conversion_factor [Stock UOM]',
               existing_nullable=False)
        batch_op.drop_column('is_active')
        batch_op.drop_column('uom_id')

    with op.batch_alter_table('units_of_measure') as batch_op:
        batch_op.drop_index('ix_uom_name_symbol')

    with op.batch_alter_table('stock_reconciliation_items') as batch_op:
        batch_op.alter_column('valuation_rate',
               existing_type=sa.Numeric(precision=18, scale=6),
               type_=sa.NUMERIC(precision=12, scale=2),
               existing_nullable=True)
        batch_op.alter_column('quantity',
               existing_type=sa.Numeric(precision=18, scale=6),
               type_=sa.NUMERIC(precision=12, scale=3),
               existing_nullable=False)

    with op.batch_alter_table('stock_ledger_entries') as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_transaction_uom_id'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_stock_entry_id'))
        batch_op.drop_index(batch_op.f('ix_stock_ledger_entries_base_uom_id'))
        batch_op.drop_index('ix_sle_uom_tracking')
        batch_op.drop_index('ix_sle_stock_entry')
        batch_op.drop_column('stock_entry_id')
        batch_op.drop_column('transaction_quantity')
        batch_op.drop_column('transaction_uom_id')
        batch_op.drop_column('base_uom_id')

    with op.batch_alter_table('stock_entry_items') as batch_op:
        batch_op.drop_index('idx_sei_item_uom')

    with op.batch_alter_table('stock_entries') as batch_op:
        batch_op.drop_index('idx_se_type_status')

    # sales_invoices
    with op.batch_alter_table('sales_invoices') as batch_op:
        batch_op.add_column(sa.Column('amount_paid', sa.NUMERIC(precision=14, scale=4), nullable=False))
        batch_op.add_column(sa.Column('balance_due', sa.NUMERIC(precision=14, scale=4), nullable=False))
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index('ix_sin_vat_account')
        batch_op.drop_index('ix_sin_mode_of_payment')
        batch_op.drop_index('ix_sin_is_return')
        batch_op.drop_index('ix_sin_is_pos')
        batch_op.drop_index('ix_sin_cash_bank_account')
        batch_op.drop_index(batch_op.f('ix_sales_invoices_vat_account_id'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_send_sms'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_return_against_id'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_mode_of_payment_id'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_is_return'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_is_pos'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_is_credit_note'))
        batch_op.drop_index(batch_op.f('ix_sales_invoices_cash_bank_account_id'))
        batch_op.drop_column('outstanding_amount')
        batch_op.drop_column('paid_amount')
        batch_op.drop_column('send_sms')
        batch_op.drop_column('is_pos')
        batch_op.drop_column('is_credit_note')
        batch_op.drop_column('is_return')
        batch_op.drop_column('cash_bank_account_id')
        batch_op.drop_column('mode_of_payment_id')
        batch_op.drop_column('vat_amount')
        batch_op.drop_column('vat_account_id')
        batch_op.drop_column('return_against_id')

    with op.batch_alter_table('sales_invoice_items') as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index('ix_sii_return_against')
        batch_op.drop_index(batch_op.f('ix_sales_invoice_items_return_against_item_id'))
        batch_op.drop_column('return_against_item_id')

    with op.batch_alter_table('sales_delivery_notes') as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index('ix_sdn_is_return')
        batch_op.drop_index(batch_op.f('ix_sales_delivery_notes_return_against_id'))
        batch_op.drop_index(batch_op.f('ix_sales_delivery_notes_is_return'))
        batch_op.drop_column('is_return')
        batch_op.drop_column('return_against_id')

    with op.batch_alter_table('sales_delivery_note_items') as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index('ix_sdni_return_against')
        batch_op.drop_index(batch_op.f('ix_sales_delivery_note_items_return_against_item_id'))
        batch_op.drop_column('return_against_item_id')

    # PURCHASE RETURNS (parent then items on downgrade)
    op.create_table('purchase_returns',
        sa.Column('company_id', sa.BIGINT(), nullable=False),
        sa.Column('branch_id', sa.BIGINT(), nullable=False),
        sa.Column('created_by_id', sa.BIGINT(), nullable=False),
        sa.Column('supplier_id', sa.BIGINT(), nullable=False),
        sa.Column('warehouse_id', sa.BIGINT(), nullable=False),
        sa.Column('receipt_id', sa.BIGINT(), nullable=True),
        sa.Column('invoice_id', sa.BIGINT(), nullable=True),
        sa.Column('code', sa.VARCHAR(length=100), nullable=False),
        sa.Column('posting_date', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('doc_status', docstatus_enum, nullable=False),
        sa.Column('remarks', sa.TEXT(), nullable=True),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['purchase_invoices.id']),
        sa.ForeignKeyConstraint(['receipt_id'], ['purchase_receipts.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['parties.id']),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'branch_id', 'code', name='uq_pret_branch_code')
    )
    with op.batch_alter_table('purchase_returns') as batch_op:
        batch_op.create_index('ix_purchase_returns_warehouse_id', ['warehouse_id'])
        batch_op.create_index('ix_purchase_returns_updated_at', ['updated_at'])
        batch_op.create_index('ix_purchase_returns_supplier_id', ['supplier_id'])
        batch_op.create_index('ix_purchase_returns_receipt_id', ['receipt_id'])
        batch_op.create_index('ix_purchase_returns_posting_date', ['posting_date'])
        batch_op.create_index('ix_purchase_returns_invoice_id', ['invoice_id'])
        batch_op.create_index('ix_purchase_returns_doc_status', ['doc_status'])
        batch_op.create_index('ix_purchase_returns_created_by_id', ['created_by_id'])
        batch_op.create_index('ix_purchase_returns_created_at', ['created_at'])
        batch_op.create_index('ix_purchase_returns_company_id', ['company_id'])
        batch_op.create_index('ix_purchase_returns_code', ['code'])
        batch_op.create_index('ix_purchase_returns_branch_id', ['branch_id'])
        batch_op.create_index('ix_pret_company_supplier', ['company_id', 'supplier_id'])
        batch_op.create_index('ix_pret_company_posting_date', ['company_id', 'posting_date'])
        batch_op.create_index('ix_pret_company_branch_status', ['company_id', 'branch_id', 'doc_status'])

    op.create_table('purchase_return_items',
        sa.Column('purchase_return_id', sa.BIGINT(), nullable=False),
        sa.Column('item_id', sa.BIGINT(), nullable=False),
        sa.Column('uom_id', sa.BIGINT(), nullable=False),
        sa.Column('receipt_item_id', sa.BIGINT(), nullable=True),
        sa.Column('invoice_item_id', sa.BIGINT(), nullable=True),
        sa.Column('quantity', sa.NUMERIC(precision=12, scale=3), nullable=False),
        sa.Column('rate', sa.NUMERIC(precision=12, scale=4), nullable=True),
        sa.Column('amount', sa.NUMERIC(precision=14, scale=4), sa.Computed("""
CASE
    WHEN (rate IS NULL) THEN NULL::numeric
    ELSE (quantity * rate)
END
""", persisted=True), nullable=True),
        sa.Column('batch_number', sa.VARCHAR(length=100), nullable=True),
        sa.Column('remarks', sa.VARCHAR(length=255), nullable=True),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity > 0::numeric', name='ck_pret_qty_pos'),
        sa.CheckConstraint('rate IS NULL OR rate >= 0::numeric', name='ck_pret_rate_nonneg'),
        sa.ForeignKeyConstraint(['invoice_item_id'], ['purchase_invoice_items.id']),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['purchase_return_id'], ['purchase_returns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['receipt_item_id'], ['purchase_receipt_items.id']),
        sa.ForeignKeyConstraint(['uom_id'], ['units_of_measure.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('purchase_return_id', 'item_id', 'batch_number', name='uq_pret_item_batch')
    )
    with op.batch_alter_table('purchase_return_items') as batch_op:
        batch_op.create_index('ix_purchase_return_items_updated_at', ['updated_at'])
        batch_op.create_index('ix_purchase_return_items_uom_id', ['uom_id'])
        batch_op.create_index('ix_purchase_return_items_receipt_item_id', ['receipt_item_id'])
        batch_op.create_index('ix_purchase_return_items_purchase_return_id', ['purchase_return_id'])
        batch_op.create_index('ix_purchase_return_items_item_id', ['item_id'])
        batch_op.create_index('ix_purchase_return_items_invoice_item_id', ['invoice_item_id'])
        batch_op.create_index('ix_purchase_return_items_created_at', ['created_at'])
        batch_op.create_index('ix_purchase_return_items_batch_number', ['batch_number'])
        batch_op.create_index('ix_pret_item', ['item_id'])

    # Branch item pricing
    op.create_table('branch_item_pricing',
        sa.Column('company_id', sa.BIGINT(), nullable=False),
        sa.Column('item_id', sa.BIGINT(), nullable=False),
        sa.Column('branch_id', sa.BIGINT(), nullable=False),
        sa.Column('standard_rate', sa.NUMERIC(precision=10, scale=2), nullable=False),
        sa.Column('cost', sa.NUMERIC(precision=10, scale=2), nullable=False),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'item_id', 'branch_id', name='uq_branch_item_price')
    )
    with op.batch_alter_table('branch_item_pricing') as batch_op:
        batch_op.create_index('ix_branch_item_pricing_updated_at', ['updated_at'])
        batch_op.create_index('ix_branch_item_pricing_created_at', ['created_at'])
        batch_op.create_index('ix_branch_item_pricing_company_id', ['company_id'])

    # SALES RETURNS (parent then items)
    op.create_table('sales_returns',
        sa.Column('company_id', sa.BIGINT(), nullable=False),
        sa.Column('branch_id', sa.BIGINT(), nullable=False),
        sa.Column('created_by_id', sa.BIGINT(), nullable=False),
        sa.Column('customer_id', sa.BIGINT(), nullable=False),
        sa.Column('warehouse_id', sa.BIGINT(), nullable=False),
        sa.Column('delivery_note_id', sa.BIGINT(), nullable=True),
        sa.Column('invoice_id', sa.BIGINT(), nullable=True),
        sa.Column('code', sa.VARCHAR(length=100), nullable=False),
        sa.Column('posting_date', postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('doc_status', docstatus_enum, nullable=False),
        sa.Column('remarks', sa.TEXT(), nullable=True),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['parties.id']),
        sa.ForeignKeyConstraint(['delivery_note_id'], ['sales_delivery_notes.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['sales_invoices.id']),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'branch_id', 'code', name='uq_sret_branch_code')
    )
    with op.batch_alter_table('sales_returns') as batch_op:
        batch_op.create_index('ix_sret_company_posting_date', ['company_id', 'posting_date'])
        batch_op.create_index('ix_sret_company_customer', ['company_id', 'customer_id'])
        batch_op.create_index('ix_sret_company_branch_status', ['company_id', 'branch_id', 'doc_status'])
        batch_op.create_index('ix_sales_returns_warehouse_id', ['warehouse_id'])
        batch_op.create_index('ix_sales_returns_updated_at', ['updated_at'])
        batch_op.create_index('ix_sales_returns_posting_date', ['posting_date'])
        batch_op.create_index('ix_sales_returns_invoice_id', ['invoice_id'])
        batch_op.create_index('ix_sales_returns_doc_status', ['doc_status'])
        batch_op.create_index('ix_sales_returns_delivery_note_id', ['delivery_note_id'])
        batch_op.create_index('ix_sales_returns_customer_id', ['customer_id'])
        batch_op.create_index('ix_sales_returns_created_by_id', ['created_by_id'])
        batch_op.create_index('ix_sales_returns_created_at', ['created_at'])
        batch_op.create_index('ix_sales_returns_company_id', ['company_id'])
        batch_op.create_index('ix_sales_returns_code', ['code'])
        batch_op.create_index('ix_sales_returns_branch_id', ['branch_id'])

    op.create_table('sales_return_items',
        sa.Column('sales_return_id', sa.BIGINT(), nullable=False),
        sa.Column('item_id', sa.BIGINT(), nullable=False),
        sa.Column('uom_id', sa.BIGINT(), nullable=False),
        sa.Column('delivery_note_item_id', sa.BIGINT(), nullable=True),
        sa.Column('invoice_item_id', sa.BIGINT(), nullable=True),
        sa.Column('quantity', sa.NUMERIC(precision=12, scale=3), nullable=False),
        sa.Column('rate', sa.NUMERIC(precision=12, scale=4), nullable=True),
        sa.Column('amount', sa.NUMERIC(precision=14, scale=4), sa.Computed("""
CASE
    WHEN (rate IS NULL) THEN NULL::numeric
    ELSE (quantity * rate)
END
""", persisted=True), nullable=True),
        sa.Column('batch_number', sa.VARCHAR(length=100), nullable=True),
        sa.Column('remarks', sa.VARCHAR(length=255), nullable=True),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity > 0::numeric', name='ck_sret_qty_pos'),
        sa.CheckConstraint('rate IS NULL OR rate >= 0::numeric', name='ck_sret_rate_nonneg'),
        sa.ForeignKeyConstraint(['delivery_note_item_id'], ['sales_delivery_note_items.id']),
        sa.ForeignKeyConstraint(['invoice_item_id'], ['sales_invoice_items.id']),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['sales_return_id'], ['sales_returns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uom_id'], ['units_of_measure.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sales_return_id', 'item_id', 'batch_number', name='uq_sret_item_batch')
    )
    with op.batch_alter_table('sales_return_items') as batch_op:
        batch_op.create_index('ix_sret_item', ['item_id'])
        batch_op.create_index('ix_sales_return_items_updated_at', ['updated_at'])
        batch_op.create_index('ix_sales_return_items_uom_id', ['uom_id'])
        batch_op.create_index('ix_sales_return_items_sales_return_id', ['sales_return_id'])
        batch_op.create_index('ix_sales_return_items_item_id', ['item_id'])
        batch_op.create_index('ix_sales_return_items_invoice_item_id', ['invoice_item_id'])
        batch_op.create_index('ix_sales_return_items_delivery_note_item_id', ['delivery_note_item_id'])
        batch_op.create_index('ix_sales_return_items_created_at', ['created_at'])
        batch_op.create_index('ix_sales_return_items_batch_number', ['batch_number'])

    # assets / item_prices / asset_depreciation_entries / item_groups / asset_categories / price_lists
    with op.batch_alter_table('asset_depreciation_entries') as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_depreciation_entries_updated_at'))
        batch_op.drop_index(batch_op.f('ix_asset_depreciation_entries_posting_date'))
        batch_op.drop_index(batch_op.f('ix_asset_depreciation_entries_journal_entry_id'))
        batch_op.drop_index(batch_op.f('ix_asset_depreciation_entries_created_at'))
        batch_op.drop_index(batch_op.f('ix_asset_depreciation_entries_asset_id'))
    op.drop_table('asset_depreciation_entries')

    with op.batch_alter_table('item_prices') as batch_op:
        batch_op.drop_index(batch_op.f('ix_item_prices_updated_at'))
        batch_op.drop_index(batch_op.f('ix_item_prices_uom_id'))
        batch_op.drop_index(batch_op.f('ix_item_prices_price_list_id'))
        batch_op.drop_index(batch_op.f('ix_item_prices_item_id'))
        batch_op.drop_index(batch_op.f('ix_item_prices_created_at'))
        batch_op.drop_index(batch_op.f('ix_item_prices_branch_id'))
        batch_op.drop_index('ix_item_price_validity')
        batch_op.drop_index('ix_item_price_uom')
        batch_op.drop_index('ix_item_price_lookup')
    op.drop_table('item_prices')

    with op.batch_alter_table('assets') as batch_op:
        batch_op.drop_index(batch_op.f('ix_assets_updated_at'))
        batch_op.drop_index(batch_op.f('ix_assets_purchase_invoice_id'))
        batch_op.drop_index(batch_op.f('ix_assets_item_id'))
        batch_op.drop_index(batch_op.f('ix_assets_created_at'))
        batch_op.drop_index(batch_op.f('ix_assets_cost_center_id'))
        batch_op.drop_index(batch_op.f('ix_assets_company_id'))
        batch_op.drop_index(batch_op.f('ix_assets_code'))
        batch_op.drop_index(batch_op.f('ix_assets_asset_category_id'))
        batch_op.drop_index('ix_asset_status')
    op.drop_table('assets')

    with op.batch_alter_table('period_closing_vouchers') as batch_op:
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_updated_at'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_submitted_by_id'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_submitted_at'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_posting_date'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_generated_journal_entry_id'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_doc_status'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_created_at'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_company_id'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_code'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_closing_fiscal_year_id'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_closing_account_head_id'))
        batch_op.drop_index(batch_op.f('ix_period_closing_vouchers_auto_prepared'))
        batch_op.drop_index('ix_pcv_posted_date')
        batch_op.drop_index('ix_pcv_company_status')
        batch_op.drop_index('ix_pcv_auto_status')
    op.drop_table('period_closing_vouchers')

    with op.batch_alter_table('account_selection_rules') as batch_op:
        batch_op.drop_index('uq_accrule_default_nomop', postgresql_where=sa.text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NULL"))
        batch_op.drop_index('uq_accrule_default_mop', postgresql_where=sa.text("rule_type = 'DEFAULT' AND mode_of_payment_id IS NOT NULL"))
        batch_op.drop_index('uq_accrule_allow_parent', postgresql_where=sa.text("rule_type = 'ALLOW' AND parent_account_id IS NOT NULL"))
        batch_op.drop_index('uq_accrule_allow_account', postgresql_where=sa.text("rule_type = 'ALLOW' AND account_id IS NOT NULL"))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_user_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_updated_at'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_rule_type'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_role'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_parent_account_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_mode_of_payment_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_department_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_created_at'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_company_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_branch_id'))
        batch_op.drop_index(batch_op.f('ix_account_selection_rules_account_id'))
    op.drop_table('account_selection_rules')

    with op.batch_alter_table('modes_of_payment') as batch_op:
        batch_op.drop_index(batch_op.f('ix_modes_of_payment_updated_at'))
        batch_op.drop_index(batch_op.f('ix_modes_of_payment_name'))
        batch_op.drop_index(batch_op.f('ix_modes_of_payment_created_at'))
        batch_op.drop_index(batch_op.f('ix_modes_of_payment_company_id'))
        batch_op.drop_index(batch_op.f('ix_modes_of_payment_branch_id'))
        batch_op.drop_index('idx_mop_type')
        batch_op.drop_index('idx_mop_default_account')
        batch_op.drop_index('idx_mop_company_id')
        batch_op.drop_index('idx_mop_branch_id')
    op.drop_table('modes_of_payment')

    with op.batch_alter_table('item_groups') as batch_op:
        batch_op.drop_index(batch_op.f('ix_item_groups_updated_at'))
        batch_op.drop_index(batch_op.f('ix_item_groups_parent_item_group_id'))
        batch_op.drop_index(batch_op.f('ix_item_groups_name'))
        batch_op.drop_index(batch_op.f('ix_item_groups_default_inventory_account_id'))
        batch_op.drop_index(batch_op.f('ix_item_groups_default_income_account_id'))
        batch_op.drop_index(batch_op.f('ix_item_groups_default_expense_account_id'))
        batch_op.drop_index(batch_op.f('ix_item_groups_created_at'))
        batch_op.drop_index(batch_op.f('ix_item_groups_company_id'))
        batch_op.drop_index(batch_op.f('ix_item_groups_code'))
        batch_op.drop_index('ix_item_group_defaults')
    op.drop_table('item_groups')

    with op.batch_alter_table('asset_categories') as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_categories_updated_at'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_name'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_fixed_asset_account_id'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_depreciation_expense_account_id'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_created_at'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_company_id'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_code'))
        batch_op.drop_index(batch_op.f('ix_asset_categories_accumulated_depreciation_account_id'))
    op.drop_table('asset_categories')

    with op.batch_alter_table('price_lists') as batch_op:
        batch_op.drop_index(batch_op.f('ix_price_lists_updated_at'))
        batch_op.drop_index(batch_op.f('ix_price_lists_is_active'))
        batch_op.drop_index(batch_op.f('ix_price_lists_created_at'))
        batch_op.drop_index(batch_op.f('ix_price_lists_company_id'))
        batch_op.drop_index('ix_price_list_type_active')
    op.drop_table('price_lists')

    # undo fiscal_years change
    with op.batch_alter_table('fiscal_years') as batch_op:
        batch_op.add_column(sa.Column('year', sa.INTEGER(), nullable=False))
        batch_op.drop_constraint('uq_fiscal_year_company_name', type_='unique')
        batch_op.drop_index('ix_fy_dates_range')
        batch_op.drop_index('ix_fy_company_status')
        batch_op.drop_index('ix_fy_company_dates')
        batch_op.drop_index(batch_op.f('ix_fiscal_years_status'))
        batch_op.drop_index(batch_op.f('ix_fiscal_years_start_date'))
        batch_op.drop_index(batch_op.f('ix_fiscal_years_name'))
        batch_op.drop_index(batch_op.f('ix_fiscal_years_end_date'))
        batch_op.create_unique_constraint('uq_fiscal_year_company', ['company_id', 'year'])
        batch_op.create_index('ix_fiscal_years_year', ['year'])
        batch_op.drop_column('is_short_year')
        batch_op.drop_column('name')

    with op.batch_alter_table('bins') as batch_op:
        batch_op.drop_index('idx_bin_item_company')

    # Drop ENUMs we created in upgrade (keep docstatusenum & journalentrytypeenum)
    bind = op.get_bind()
    postgresql.ENUM(name='accountruletypeenum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='accountuseroleenum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='modeofpaymenttypeenum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='pricelisttype').drop(bind, checkfirst=True)
