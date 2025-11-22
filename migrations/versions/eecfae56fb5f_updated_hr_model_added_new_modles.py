"""updated hr model added new modles

Revision ID: eecfae56fb5f
Revises: 674695945af2
Create Date: 2025-11-22 08:20:55.577573

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "eecfae56fb5f"
down_revision = "674695945af2"
branch_labels = None
depends_on = None


def upgrade():
    """
    HR / Attendance / Payroll core models.

    Important points:
    - Reuse existing docstatusenum (from stock/accounting) for salary_slips
      without trying to re-create it.
    - Explicitly create employment_type_enum BEFORE adding the column to
      employees, because ALTER TABLE .. ADD COLUMN does NOT auto-create
      the enum type.
    - Enum values are aligned with the Python Enum values in app/hr/hr.py:
        * EmploymentTypeEnum      -> "Full-time", "Part-time", "Contract", "Intern"
        * AttendanceStatusEnum    -> "Present", "Absent", "Half Day", "On Leave", "Work From Home"
        * CheckinLogTypeEnum      -> "In", "Out"
        * CheckinSourceEnum       -> "Manual", "Device", "Mobile", "Other"
        * PaymentFrequencyEnum    -> "Monthly", "Weekly", "Bi-weekly"
    """

    # Reuse existing docstatusenum type; DO NOT create it again.
    docstatus_enum = postgresql.ENUM(
        "DRAFT",
        "SUBMITTED",
        "CANCELLED",
        "UNPAID",
        "PARTIALLY_PAID",
        "PAID",
        "OVERDUE",
        "RETURNED",
        name="docstatusenum",
        create_type=False,
    )

    # New enum type for Employee.employment_type
    employment_type_enum = postgresql.ENUM(
        "Full-time",
        "Part-time",
        "Contract",
        "Intern",
        name="employment_type_enum",
    )

    # ---------------------------------------------------------------------
    # biometric_devices
    # ---------------------------------------------------------------------
    op.create_table(
        "biometric_devices",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("password", sa.Integer(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column(
            "location",
            sa.String(length=255),
            nullable=True,
            comment="Physical location, e.g. HQ Main Gate",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "last_sync_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time the agent successfully pulled data from this device",
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Any future settings (punch mapping, shift id, etc.)",
        ),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_biometric_device_company_code"),
    )
    with op.batch_alter_table("biometric_devices", schema=None) as batch_op:
        batch_op.create_index(
            "ix_biometric_device_company_active", ["company_id", "is_active"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_biometric_devices_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_biometric_devices_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_biometric_devices_is_active"), ["is_active"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_biometric_devices_last_sync_at"), ["last_sync_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_biometric_devices_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # holiday_lists
    # ---------------------------------------------------------------------
    op.create_table(
        "holiday_lists",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_holiday_list_company_name"),
    )
    with op.batch_alter_table("holiday_lists", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_holiday_lists_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_holiday_lists_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_holiday_lists_is_default"), ["is_default"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_holiday_lists_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # payroll_periods
    # ---------------------------------------------------------------------
    op.create_table(
        "payroll_periods",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_payroll_period_company_name"),
    )
    with op.batch_alter_table("payroll_periods", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_payroll_periods_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_payroll_periods_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_payroll_periods_is_closed"), ["is_closed"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_payroll_periods_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # salary_structures
    # ---------------------------------------------------------------------
    op.create_table(
        "salary_structures",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column(
            "payment_frequency",
            sa.Enum(
                "Monthly",
                "Weekly",
                "Bi-weekly",
                name="payment_frequency_enum",
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_salary_structure_company_name"),
    )
    with op.batch_alter_table("salary_structures", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_salary_structures_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_structures_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_structures_is_active"), ["is_active"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_structures_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # holidays
    # ---------------------------------------------------------------------
    op.create_table(
        "holidays",
        sa.Column("holiday_list_id", sa.BigInteger(), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=140), nullable=True),
        sa.Column("is_full_day", sa.Boolean(), nullable=False),
        sa.Column("is_weekly_off", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["holiday_list_id"], ["holiday_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("holiday_list_id", "holiday_date", name="uq_holiday_per_list_date"),
    )
    with op.batch_alter_table("holidays", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_holidays_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_holidays_holiday_list_id"), ["holiday_list_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_holidays_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # shift_types
    # ---------------------------------------------------------------------
    op.create_table(
        "shift_types",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("enable_auto_attendance", sa.Boolean(), nullable=False),
        sa.Column("process_attendance_after", sa.Date(), nullable=True),
        sa.Column("is_night_shift", sa.Boolean(), nullable=False),
        sa.Column("holiday_list_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["holiday_list_id"], ["holiday_lists.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_shift_type_company_name"),
    )
    with op.batch_alter_table("shift_types", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_shift_types_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_types_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_types_enable_auto_attendance"),
            ["enable_auto_attendance"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_shift_types_holiday_list_id"), ["holiday_list_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_types_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # attendances
    # ---------------------------------------------------------------------
    op.create_table(
        "attendances",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=True),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "Present",
                "Absent",
                "Half Day",
                "On Leave",
                "Work From Home",
                name="attendance_status_enum",
            ),
            nullable=False,
        ),
        sa.Column("shift_type_id", sa.BigInteger(), nullable=True),
        sa.Column("in_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("out_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("working_hours", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("late_entry", sa.Boolean(), nullable=False),
        sa.Column("early_exit", sa.Boolean(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            comment="AUTO or MANUAL",
        ),
        sa.Column("remarks", sa.String(length=255), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shift_type_id"], ["shift_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "attendance_date", name="uq_attendance_emp_date"),
    )
    with op.batch_alter_table("attendances", schema=None) as batch_op:
        batch_op.create_index(
            "ix_attendance_company_date", ["company_id", "attendance_date"], unique=False
        )
        batch_op.create_index(
            "ix_attendance_status", ["company_id", "status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_attendance_date"), ["attendance_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_branch_id"), ["branch_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_employee_id"), ["employee_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_shift_type_id"), ["shift_type_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_status"), ["status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attendances_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # employee_checkins
    # ---------------------------------------------------------------------
    op.create_table(
        "employee_checkins",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("log_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "log_type",
            sa.Enum("In", "Out", name="checkin_log_type_enum"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "Manual",
                "Device",
                "Mobile",
                "Other",
                name="checkin_source_enum",
            ),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(length=100), nullable=True),
        sa.Column("skip_auto_attendance", sa.Boolean(), nullable=False),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Optional raw body from the device/API",
        ),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "log_time", name="uq_checkin_emp_time"),
    )
    with op.batch_alter_table("employee_checkins", schema=None) as batch_op:
        batch_op.create_index(
            "ix_checkin_company_time", ["company_id", "log_time"], unique=False
        )
        batch_op.create_index(
            "ix_checkin_emp_time", ["employee_id", "log_time"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_employee_id"), ["employee_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_log_time"), ["log_time"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_log_type"), ["log_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_skip_auto_attendance"),
            ["skip_auto_attendance"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_source"), ["source"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_employee_checkins_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # employee_salary_assignments
    # ---------------------------------------------------------------------
    op.create_table(
        "employee_salary_assignments",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("salary_structure_id", sa.BigInteger(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("base_salary", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["salary_structure_id"], ["salary_structures.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "from_date", name="uq_salary_assign_emp_from"),
    )
    with op.batch_alter_table("employee_salary_assignments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_employee_salary_assignments_company_id"),
            ["company_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employee_salary_assignments_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employee_salary_assignments_employee_id"),
            ["employee_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employee_salary_assignments_salary_structure_id"),
            ["salary_structure_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employee_salary_assignments_updated_at"),
            ["updated_at"],
            unique=False,
        )

    # ---------------------------------------------------------------------
    # salary_slips  (uses existing docstatusenum)
    # ---------------------------------------------------------------------
    op.create_table(
        "salary_slips",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("payroll_period_id", sa.BigInteger(), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("gross_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_deductions", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("net_pay", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("doc_status", docstatus_enum, nullable=False),
        sa.Column("remarks", sa.String(length=255), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Any computed breakdown or metadata you don't want in columns yet",
        ),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["payroll_period_id"], ["payroll_periods.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "payroll_period_id", name="uq_salary_slip_emp_period"),
    )
    with op.batch_alter_table("salary_slips", schema=None) as batch_op:
        batch_op.create_index(
            "ix_salary_slip_company_period", ["company_id", "payroll_period_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_doc_status"), ["doc_status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_employee_id"), ["employee_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_payroll_period_id"),
            ["payroll_period_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_salary_slips_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # shift_assignments
    # ---------------------------------------------------------------------
    op.create_table(
        "shift_assignments",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("shift_type_id", sa.BigInteger(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shift_type_id"], ["shift_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "shift_type_id", "from_date", name="uq_shift_emp_from"),
    )
    with op.batch_alter_table("shift_assignments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_shift_assign_company_date", ["company_id", "from_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_employee_id"), ["employee_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_is_active"), ["is_active"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_shift_type_id"), ["shift_type_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_shift_assignments_updated_at"), ["updated_at"], unique=False
        )

    # ---------------------------------------------------------------------
    # employees: add employment_type + biometric/holiday/shift fields
    # ---------------------------------------------------------------------
    bind = op.get_bind()
    # Make sure the enum type exists before we add a column using it
    employment_type_enum.create(bind, checkfirst=True)

    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("employment_type", employment_type_enum, nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "attendance_device_id",
                sa.String(length=64),
                nullable=True,
                comment="Biometric / RF Card / Device User ID",
            )
        )
        batch_op.add_column(sa.Column("holiday_list_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("default_shift_type_id", sa.BigInteger(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_employees_attendance_device_id"),
            ["attendance_device_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employees_default_shift_type_id"),
            ["default_shift_type_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employees_employment_type"),
            ["employment_type"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_employees_holiday_list_id"),
            ["holiday_list_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            None,
            "shift_types",
            ["default_shift_type_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            None,
            "holiday_lists",
            ["holiday_list_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    # IMPORTANT: Downgrade in reverse dependency order.

    # ------------------------------------------------------------------
    # employees: drop new columns + indexes, then enum type
    # ------------------------------------------------------------------
    employment_type_enum = postgresql.ENUM(
        "Full-time",
        "Part-time",
        "Contract",
        "Intern",
        name="employment_type_enum",
    )

    with op.batch_alter_table("employees", schema=None) as batch_op:
        batch_op.drop_constraint(None, type_="foreignkey")
        batch_op.drop_constraint(None, type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_employees_holiday_list_id"))
        batch_op.drop_index(batch_op.f("ix_employees_employment_type"))
        batch_op.drop_index(batch_op.f("ix_employees_default_shift_type_id"))
        batch_op.drop_index(batch_op.f("ix_employees_attendance_device_id"))
        batch_op.drop_column("default_shift_type_id")
        batch_op.drop_column("holiday_list_id")
        batch_op.drop_column("attendance_device_id")
        batch_op.drop_column("employment_type")

    # Drop the enum type (no longer used)
    employment_type_enum.drop(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # shift_assignments
    # ------------------------------------------------------------------
    with op.batch_alter_table("shift_assignments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shift_assignments_updated_at"))
        batch_op.drop_index(batch_op.f("ix_shift_assignments_shift_type_id"))
        batch_op.drop_index(batch_op.f("ix_shift_assignments_is_active"))
        batch_op.drop_index(batch_op.f("ix_shift_assignments_employee_id"))
        batch_op.drop_index(batch_op.f("ix_shift_assignments_created_at"))
        batch_op.drop_index(batch_op.f("ix_shift_assignments_company_id"))
        batch_op.drop_index("ix_shift_assign_company_date")

    op.drop_table("shift_assignments")

    # ------------------------------------------------------------------
    # salary_slips
    # ------------------------------------------------------------------
    with op.batch_alter_table("salary_slips", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_salary_slips_updated_at"))
        batch_op.drop_index(batch_op.f("ix_salary_slips_payroll_period_id"))
        batch_op.drop_index(batch_op.f("ix_salary_slips_employee_id"))
        batch_op.drop_index(batch_op.f("ix_salary_slips_doc_status"))
        batch_op.drop_index(batch_op.f("ix_salary_slips_created_at"))
        batch_op.drop_index(batch_op.f("ix_salary_slips_company_id"))
        batch_op.drop_index("ix_salary_slip_company_period")

    op.drop_table("salary_slips")

    # ------------------------------------------------------------------
    # employee_salary_assignments
    # ------------------------------------------------------------------
    with op.batch_alter_table("employee_salary_assignments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_employee_salary_assignments_updated_at"))
        batch_op.drop_index(
            batch_op.f("ix_employee_salary_assignments_salary_structure_id")
        )
        batch_op.drop_index(batch_op.f("ix_employee_salary_assignments_employee_id"))
        batch_op.drop_index(batch_op.f("ix_employee_salary_assignments_created_at"))
        batch_op.drop_index(batch_op.f("ix_employee_salary_assignments_company_id"))

    op.drop_table("employee_salary_assignments")

    # ------------------------------------------------------------------
    # employee_checkins
    # ------------------------------------------------------------------
    with op.batch_alter_table("employee_checkins", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_employee_checkins_updated_at"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_source"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_skip_auto_attendance"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_log_type"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_log_time"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_employee_id"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_created_at"))
        batch_op.drop_index(batch_op.f("ix_employee_checkins_company_id"))
        batch_op.drop_index("ix_checkin_emp_time")
        batch_op.drop_index("ix_checkin_company_time")

    op.drop_table("employee_checkins")

    # ------------------------------------------------------------------
    # attendances
    # ------------------------------------------------------------------
    with op.batch_alter_table("attendances", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attendances_updated_at"))
        batch_op.drop_index(batch_op.f("ix_attendances_status"))
        batch_op.drop_index(batch_op.f("ix_attendances_shift_type_id"))
        batch_op.drop_index(batch_op.f("ix_attendances_employee_id"))
        batch_op.drop_index(batch_op.f("ix_attendances_created_at"))
        batch_op.drop_index(batch_op.f("ix_attendances_company_id"))
        batch_op.drop_index(batch_op.f("ix_attendances_branch_id"))
        batch_op.drop_index(batch_op.f("ix_attendances_attendance_date"))
        batch_op.drop_index("ix_attendance_status")
        batch_op.drop_index("ix_attendance_company_date")

    op.drop_table("attendances")

    # ------------------------------------------------------------------
    # shift_types
    # ------------------------------------------------------------------
    with op.batch_alter_table("shift_types", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shift_types_updated_at"))
        batch_op.drop_index(batch_op.f("ix_shift_types_holiday_list_id"))
        batch_op.drop_index(batch_op.f("ix_shift_types_enable_auto_attendance"))
        batch_op.drop_index(batch_op.f("ix_shift_types_created_at"))
        batch_op.drop_index(batch_op.f("ix_shift_types_company_id"))

    op.drop_table("shift_types")

    # ------------------------------------------------------------------
    # holidays
    # ------------------------------------------------------------------
    with op.batch_alter_table("holidays", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_holidays_updated_at"))
        batch_op.drop_index(batch_op.f("ix_holidays_holiday_list_id"))
        batch_op.drop_index(batch_op.f("ix_holidays_created_at"))

    op.drop_table("holidays")

    # ------------------------------------------------------------------
    # salary_structures
    # ------------------------------------------------------------------
    with op.batch_alter_table("salary_structures", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_salary_structures_updated_at"))
        batch_op.drop_index(batch_op.f("ix_salary_structures_is_active"))
        batch_op.drop_index(batch_op.f("ix_salary_structures_created_at"))
        batch_op.drop_index(batch_op.f("ix_salary_structures_company_id"))

    op.drop_table("salary_structures")

    # ------------------------------------------------------------------
    # payroll_periods
    # ------------------------------------------------------------------
    with op.batch_alter_table("payroll_periods", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_payroll_periods_updated_at"))
        batch_op.drop_index(batch_op.f("ix_payroll_periods_is_closed"))
        batch_op.drop_index(batch_op.f("ix_payroll_periods_created_at"))
        batch_op.drop_index(batch_op.f("ix_payroll_periods_company_id"))

    op.drop_table("payroll_periods")

    # ------------------------------------------------------------------
    # holiday_lists
    # ------------------------------------------------------------------
    with op.batch_alter_table("holiday_lists", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_holiday_lists_updated_at"))
        batch_op.drop_index(batch_op.f("ix_holiday_lists_is_default"))
        batch_op.drop_index(batch_op.f("ix_holiday_lists_created_at"))
        batch_op.drop_index(batch_op.f("ix_holiday_lists_company_id"))

    op.drop_table("holiday_lists")

    # ------------------------------------------------------------------
    # biometric_devices
    # ------------------------------------------------------------------
    with op.batch_alter_table("biometric_devices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_biometric_devices_updated_at"))
        batch_op.drop_index(batch_op.f("ix_biometric_devices_last_sync_at"))
        batch_op.drop_index(batch_op.f("ix_biometric_devices_is_active"))
        batch_op.drop_index(batch_op.f("ix_biometric_devices_created_at"))
        batch_op.drop_index(batch_op.f("ix_biometric_devices_company_id"))
        batch_op.drop_index("ix_biometric_device_company_active")

    op.drop_table("biometric_devices")
