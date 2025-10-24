"""updated cost center & MoP and others

Revision ID: 62abde36e43c
Revises: a21713620c43
Create Date: 2025-10-23 09:53:41.390190
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "62abde36e43c"
down_revision = "a21713620c43"
branch_labels = None
depends_on = None

# ─────────────────────────
# Module-level ENUM handles
# ─────────────────────────
ACCOUNT_USE_ROLE_ENUM = postgresql.ENUM(
    "CASH_IN", "CASH_OUT", "TRANSFER_SOURCE", "TRANSFER_TARGET", "EXPENSE",
    name="accountuseroleenum"
)

DEPRECIATION_METHOD_ENUM = postgresql.ENUM(
    "STRAIGHT_LINE", "DOUBLE_DECLINING_BALANCE", "WRITTEN_DOWN_VALUE", "MANUAL",
    name="depreciationmethodenum"
)

DOC_STATUS_ENUM = postgresql.ENUM(
    "DRAFT", "SUBMITTED", "CANCELLED", "UNPAID", "PARTIALLY_PAID",
    "PAID", "OVERDUE", "RETURNED",
    name="docstatusenum"
)

ASSET_STATUS_ENUM = postgresql.ENUM(
    "DRAFT", "SUBMITTED", "PARTIALLY_DEPRECIATED", "FULLY_DEPRECIATED",
    "SCRAPPED", "SOLD", "CAPITALIZED", "ISSUED",
    name="assetstatusenum"
)


def upgrade():
    bind = op.get_bind()

    # Ensure ENUM types exist (safe across teammates)
    ACCOUNT_USE_ROLE_ENUM.create(bind, checkfirst=True)
    DEPRECIATION_METHOD_ENUM.create(bind, checkfirst=True)
    DOC_STATUS_ENUM.create(bind, checkfirst=True)
    ASSET_STATUS_ENUM.create(bind, checkfirst=True)

    # account_access_policies.role: VARCHAR -> ENUM with USING
    with op.batch_alter_table("account_access_policies", schema=None) as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=sa.VARCHAR(length=50),
            type_=ACCOUNT_USE_ROLE_ENUM,
            existing_nullable=False,
            postgresql_using="role::accountuseroleenum",
        )

    # accounts: add enabled, backfill from old status, drop status
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False))

    # Disabled only when old status='CANCELLED'
    op.execute("""
        UPDATE accounts
        SET enabled = CASE WHEN status = 'CANCELLED' THEN FALSE ELSE TRUE END
    """)

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column("enabled", server_default=None)
        # these may not exist in every DB; drop defensively
        try:
            batch_op.drop_index("ix_accounts_status")
        except Exception:
            pass
        batch_op.create_index("ix_account_enabled", ["company_id", "enabled"], unique=False)
        batch_op.create_index(batch_op.f("ix_accounts_enabled"), ["enabled"], unique=False)
        batch_op.drop_column("status")

    # asset_categories.depreciation_method -> ENUM (safe cast)
    with op.batch_alter_table("asset_categories", schema=None) as batch_op:
        batch_op.alter_column(
            "depreciation_method",
            existing_type=sa.VARCHAR(length=50),
            type_=DEPRECIATION_METHOD_ENUM,
            existing_nullable=False,
            postgresql_using="depreciation_method::depreciationmethodenum",
            comment=None,
            existing_comment="e.g., Straight Line, Double Declining Balance.",
        )

    # asset_depreciation_entries.journal_entry_id (comment cleanup)
    with op.batch_alter_table("asset_depreciation_entries", schema=None) as batch_op:
        batch_op.alter_column(
            "journal_entry_id",
            existing_type=sa.BIGINT(),
            existing_nullable=True,
            comment=None,
            existing_comment="The link to the actual GL Journal Entry created by this record.",
        )

    # asset_finance_books.depreciation_method -> ENUM
    with op.batch_alter_table("asset_finance_books", schema=None) as batch_op:
        batch_op.alter_column(
            "depreciation_method",
            existing_type=sa.VARCHAR(length=50),
            type_=DEPRECIATION_METHOD_ENUM,
            existing_nullable=False,
            postgresql_using="depreciation_method::depreciationmethodenum",
        )

    # asset_movements.doc_status -> ENUM
    with op.batch_alter_table("asset_movements", schema=None) as batch_op:
        batch_op.alter_column(
            "doc_status",
            existing_type=sa.VARCHAR(length=50),
            type_=DOC_STATUS_ENUM,
            existing_nullable=False,
            postgresql_using="doc_status::docstatusenum",
        )

    # assets: several enum casts + comment cleanups
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.alter_column(
            "doc_status",
            existing_type=sa.VARCHAR(length=50),
            type_=DOC_STATUS_ENUM,
            existing_nullable=False,
            postgresql_using="doc_status::docstatusenum",
        )
        batch_op.alter_column(
            "asset_status",
            existing_type=sa.VARCHAR(length=50),
            type_=ASSET_STATUS_ENUM,
            existing_nullable=False,
            postgresql_using="asset_status::assetstatusenum",
        )
        batch_op.alter_column(
            "item_id",
            existing_type=sa.BIGINT(),
            existing_nullable=True,
            comment=None,
            existing_comment="The Item master from which this asset was purchased.",
        )
        batch_op.alter_column(
            "gross_purchase_amount",
            existing_type=sa.NUMERIC(precision=15, scale=4),
            existing_nullable=True,
            comment=None,
            existing_comment="Original cost of the asset.",
        )
        batch_op.alter_column(
            "expected_salvage_value",
            existing_type=sa.NUMERIC(precision=15, scale=4),
            existing_nullable=True,
            comment=None,
            existing_comment="Residual value at the end of useful life.",
        )
        batch_op.alter_column(
            "depreciation_start_date",
            existing_type=sa.DATE(),
            existing_nullable=True,
            comment=None,
            existing_comment="The date depreciation calculation begins.",
        )

    # cost_centers: add enabled, backfill from old status, drop status
    with op.batch_alter_table("cost_centers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False))

    op.execute("""
        UPDATE cost_centers
        SET enabled = CASE WHEN status = 'CANCELLED' THEN FALSE ELSE TRUE END
    """)

    with op.batch_alter_table("cost_centers", schema=None) as batch_op:
        batch_op.alter_column("enabled", server_default=None)

        # may not exist everywhere; drop if present
        try:
            batch_op.drop_index("ix_cost_centers_status")
        except Exception:
            pass
        try:
            batch_op.drop_constraint("uq_cost_center_company_branch", type_="unique")
        except Exception:
            pass

        batch_op.create_index("ix_cost_center_company_branch", ["company_id", "branch_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_cost_centers_enabled"), ["enabled"], unique=False)
        batch_op.create_index(batch_op.f("ix_cost_centers_name"), ["name"], unique=False)
        batch_op.create_unique_constraint(
            "uq_cost_center_company_branch_name",
            ["company_id", "branch_id", "name"]
        )
        batch_op.drop_column("status")


def downgrade():
    # cost_centers: restore status from enabled
    with op.batch_alter_table("cost_centers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                DOC_STATUS_ENUM,
                nullable=False,
                server_default=sa.text("'SUBMITTED'"),
            )
        )

    op.execute("""
        UPDATE cost_centers
        SET status = CASE WHEN enabled = FALSE THEN 'CANCELLED' ELSE 'SUBMITTED' END
    """)

    with op.batch_alter_table("cost_centers", schema=None) as batch_op:
        batch_op.alter_column("status", server_default=None)
        batch_op.drop_constraint("uq_cost_center_company_branch_name", type_="unique")
        batch_op.drop_index(batch_op.f("ix_cost_centers_name"))
        batch_op.drop_index(batch_op.f("ix_cost_centers_enabled"))
        batch_op.drop_index("ix_cost_center_company_branch")
        batch_op.create_unique_constraint("uq_cost_center_company_branch", ["company_id", "branch_id"])
        batch_op.create_index("ix_cost_centers_status", ["status"], unique=False)
        batch_op.drop_column("enabled")

    # assets / movements back to VARCHAR via USING ::text
    with op.batch_alter_table("assets", schema=None) as batch_op:
        batch_op.alter_column(
            "depreciation_start_date",
            existing_type=sa.DATE(),
            comment="The date depreciation calculation begins.",
            existing_nullable=True,
        )
        batch_op.alter_column(
            "expected_salvage_value",
            existing_type=sa.NUMERIC(precision=15, scale=4),
            comment="Residual value at the end of useful life.",
            existing_nullable=True,
        )
        batch_op.alter_column(
            "gross_purchase_amount",
            existing_type=sa.NUMERIC(precision=15, scale=4),
            comment="Original cost of the asset.",
            existing_nullable=True,
        )
        batch_op.alter_column(
            "item_id",
            existing_type=sa.BIGINT(),
            comment="The Item master from which this asset was purchased.",
            existing_nullable=True,
        )
        batch_op.alter_column(
            "asset_status",
            existing_type=ASSET_STATUS_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="asset_status::text",
        )
        batch_op.alter_column(
            "doc_status",
            existing_type=DOC_STATUS_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="doc_status::text",
        )

    with op.batch_alter_table("asset_movements", schema=None) as batch_op:
        batch_op.alter_column(
            "doc_status",
            existing_type=DOC_STATUS_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="doc_status::text",
        )

    with op.batch_alter_table("asset_finance_books", schema=None) as batch_op:
        batch_op.alter_column(
            "depreciation_method",
            existing_type=DEPRECIATION_METHOD_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="depreciation_method::text",
        )

    with op.batch_alter_table("asset_depreciation_entries", schema=None) as batch_op:
        batch_op.alter_column(
            "journal_entry_id",
            existing_type=sa.BIGINT(),
            comment="The link to the actual GL Journal Entry created by this record.",
            existing_nullable=True,
        )

    with op.batch_alter_table("asset_categories", schema=None) as batch_op:
        batch_op.alter_column(
            "depreciation_method",
            existing_type=DEPRECIATION_METHOD_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="depreciation_method::text",
            comment="e.g., Straight Line, Double Declining Balance.",
        )

    # accounts: restore status from enabled
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                DOC_STATUS_ENUM,
                nullable=False,
                server_default=sa.text("'SUBMITTED'"),
            )
        )

    op.execute("""
        UPDATE accounts
        SET status = CASE WHEN enabled = FALSE THEN 'CANCELLED' ELSE 'SUBMITTED' END
    """)

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column("status", server_default=None)
        batch_op.drop_index(batch_op.f("ix_accounts_enabled"))
        batch_op.drop_index("ix_account_enabled")
        batch_op.create_index("ix_accounts_status", ["status"], unique=False)
        batch_op.drop_column("enabled")

    # account_access_policies.role: ENUM -> VARCHAR
    with op.batch_alter_table("account_access_policies", schema=None) as batch_op:
        batch_op.alter_column(
            "role",
            existing_type=ACCOUNT_USE_ROLE_ENUM,
            type_=sa.VARCHAR(length=50),
            existing_nullable=False,
            postgresql_using="role::text",
        )

    # We keep ENUM types in DB to avoid breaking other objects; no DROP here.
