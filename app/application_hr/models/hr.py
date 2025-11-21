# app/hr/hr.py
from __future__ import annotations

from typing import Optional
from datetime import date, datetime, time
import enum
from app.application_stock.stock_models import DocStatusEnum
from sqlalchemy import UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from config.database import db
from app.common.models.base import (
    BaseModel,
    StatusEnum,
    GenderEnum,
    PersonRelationshipEnum,

)


# ----------------------------------------------------
# ENUMS (lean + human-friendly values)
# ----------------------------------------------------


class EmploymentTypeEnum(str, enum.Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT = "Contract"
    INTERN = "Intern"


class AttendanceStatusEnum(str, enum.Enum):
    PRESENT = "Present"
    ABSENT = "Absent"
    HALF_DAY = "Half Day"
    ON_LEAVE = "On Leave"
    WORK_FROM_HOME = "Work From Home"


class CheckinLogTypeEnum(str, enum.Enum):
    IN = "In"
    OUT = "Out"


class CheckinSourceEnum(str, enum.Enum):
    MANUAL = "Manual"
    DEVICE = "Device"
    MOBILE = "Mobile"
    OTHER = "Other"


class PaymentFrequencyEnum(str, enum.Enum):
    MONTHLY = "Monthly"
    WEEKLY = "Weekly"
    BIWEEKLY = "Bi-weekly"


# -------------------------
# Employee
# -------------------------


class Employee(BaseModel):
    __tablename__ = "employees"

    # tenant
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # identity / contact
    code: Mapped[str] = mapped_column(db.String(100), nullable=False)  # unique per company
    full_name: Mapped[str] = mapped_column(db.String(255), nullable=False, index=True)
    personal_email: Mapped[Optional[str]] = mapped_column(db.String(255))
    phone_number: Mapped[Optional[str]] = mapped_column(db.String(50))
    img_key: Mapped[Optional[str]] = mapped_column(
        db.String(512),
        nullable=True,
        comment="Object-storage key/path for the encrypted image",
        index=True,
    )

    # basic HR fields
    dob: Mapped[Optional[date]] = mapped_column(db.Date)
    date_of_joining: Mapped[Optional[date]] = mapped_column(db.Date)
    sex: Mapped[Optional[GenderEnum]] = mapped_column(
        db.Enum(GenderEnum, name="gender_enum"),
        nullable=True,
    )

    # employment type (like ERPNext Employment Type)
    employment_type: Mapped[Optional[EmploymentTypeEnum]] = mapped_column(
        db.Enum(EmploymentTypeEnum, name="employment_type_enum"),
        nullable=True,
        index=True,
    )
    # ---- NEW: Biometric / RF card ID like ERPNext field ----
    # This must match the "user_id" stored in the ZK device (or whatever device).
    attendance_device_id: Mapped[Optional[str]] = mapped_column(
        db.String(64),
        nullable=True,
        index=True,
        comment="Biometric / RF Card / Device User ID",
    )

    # link to holiday list (like Employee.holiday_list in ERPNext)
    holiday_list_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("holiday_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # default shift type for employee (morning, night, etc.)
    default_shift_type_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("shift_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # optional login user
    user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # lifecycle
    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="employee_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_employee_code_per_company"),
        Index("ix_employees_company", "company_id"),
    )

    # relationships
    company = db.relationship("Company", lazy="joined")
    user = db.relationship("User", backref=db.backref("employee", uselist=False), lazy="selectin")

    holiday_list = db.relationship("HolidayList", lazy="joined")
    default_shift_type = db.relationship("ShiftType", lazy="joined")

    # convenient access to assignments (most-recent first)
    assignments = db.relationship(
        "EmployeeAssignment",
        back_populates="employee",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="desc(EmployeeAssignment.from_date)",
    )

    # per-employee shift assignments (separate from branch/department assignments)
    shift_assignments = db.relationship(
        "ShiftAssignment",
        back_populates="employee",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="desc(ShiftAssignment.from_date)",
    )

    attendances = db.relationship(
        "Attendance",
        back_populates="employee",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    checkins = db.relationship(
        "EmployeeCheckin",
        back_populates="employee",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def primary_assignment(self) -> Optional["EmployeeAssignment"]:
        # prefer an active primary; else fallback to the most recent row
        for a in self.assignments:
            if a.is_primary and a.to_date is None:
                return a
        return self.assignments[0] if self.assignments else None

    @property
    def primary_branch_id(self) -> Optional[int]:
        pa = self.primary_assignment
        return pa.branch_id if pa else None

    def __repr__(self) -> str:
        return f"<Employee id={self.id} code={self.code!r} name={self.full_name!r}>"


# ------------------------------------
# EmployeeEmergencyContact (unchanged)
# ------------------------------------


class EmployeeEmergencyContact(BaseModel):
    __tablename__ = "employee_emergency_contacts"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    relationship_type: Mapped[PersonRelationshipEnum] = mapped_column(
        db.Enum(PersonRelationshipEnum, name="person_relationship_enum"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(db.String(50), nullable=False)

    __table_args__ = (
        Index("ix_emp_ec_employee_rel", "employee_id", "relationship_type"),
    )

    employee = db.relationship(
        "Employee",
        backref=db.backref("emergency_contacts", cascade="all, delete-orphan", lazy="selectin"),
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<EmployeeEmergencyContact id={self.id} employee_id={self.employee_id} name={self.full_name!r}>"


# -------------------------------------------------
# EmployeeAssignment (branch/department + history)
# -------------------------------------------------


class EmployeeAssignment(BaseModel):
    """
    Branch/Department placement with history.
    Keep Employee.company_id as the canonical tenant; we mirror it here for fast filters.
    """
    __tablename__ = "employee_assignments"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(  # mirror for quick queries
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    job_title: Mapped[Optional[str]] = mapped_column(db.String(120))

    from_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    to_date:   Mapped[Optional[date]] = mapped_column(db.Date)

    is_primary: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="emp_assignment_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    # any per-posting extras (printer id, cost center note, extension, etc.)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("employee_id", "branch_id", "from_date", name="uq_emp_branch_from"),
        Index("ix_emp_assign_company_branch", "company_id", "branch_id"),
        Index(
            "uq_emp_primary_assignment",
            "employee_id",
            unique=True,
            postgresql_where=text("is_primary = true AND to_date IS NULL"),
        ),
    )

    employee   = db.relationship("Employee", lazy="joined", back_populates="assignments")
    company    = db.relationship("Company",  lazy="joined")
    branch     = db.relationship("Branch",   lazy="joined")
    department = db.relationship("Department", lazy="joined")

    def __repr__(self) -> str:
        return f"<EmployeeAssignment emp={self.employee_id} branch={self.branch_id} primary={self.is_primary}>"


# -------------------------
# Holiday List + Holidays
# -------------------------


class HolidayList(BaseModel):
    __tablename__ = "holiday_lists"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    from_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    to_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    is_default: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_holiday_list_company_name"),
    )

    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return f"<HolidayList id={self.id} name={self.name!r} company_id={self.company_id}>"


class Holiday(BaseModel):
    __tablename__ = "holidays"

    holiday_list_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("holiday_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    holiday_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.String(140))
    is_full_day: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    is_weekly_off: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("holiday_list_id", "holiday_date", name="uq_holiday_per_list_date"),
    )

    holiday_list = db.relationship(
        "HolidayList",
        backref=db.backref("holidays", lazy="selectin", cascade="all, delete-orphan"),
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Holiday id={self.id} list={self.holiday_list_id} date={self.holiday_date}>"


# -------------------------
# Shift Type + Assignment
# -------------------------


class ShiftType(BaseModel):
    """
    Defines a work shift and auto-attendance rules (like ERPNext Shift Type),
    but kept minimal.
    """
    __tablename__ = "shift_types"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(db.String(140), nullable=False)
    start_time: Mapped[time] = mapped_column(db.Time, nullable=False)
    end_time: Mapped[time] = mapped_column(db.Time, nullable=False)

    enable_auto_attendance: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, index=True
    )
    process_attendance_after: Mapped[Optional[date]] = mapped_column(db.Date)

    is_night_shift: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    # optional override holiday list just for this shift
    holiday_list_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("holiday_lists.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_shift_type_company_name"),
    )

    company = db.relationship("Company", lazy="joined")
    holiday_list = db.relationship("HolidayList", lazy="joined")

    def __repr__(self) -> str:
        return f"<ShiftType id={self.id} name={self.name!r} company_id={self.company_id}>"


class ShiftAssignment(BaseModel):
    """
    Assigns a shift to an employee for a date range (like ERPNext Shift Assignment).
    """
    __tablename__ = "shift_assignments"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shift_type_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("shift_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    from_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    to_date: Mapped[Optional[date]] = mapped_column(db.Date)

    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        UniqueConstraint("employee_id", "shift_type_id", "from_date", name="uq_shift_emp_from"),
        Index("ix_shift_assign_company_date", "company_id", "from_date"),
    )

    employee = db.relationship("Employee", lazy="joined", back_populates="shift_assignments")
    company = db.relationship("Company", lazy="joined")
    shift_type = db.relationship("ShiftType", lazy="joined")

    def __repr__(self) -> str:
        return f"<ShiftAssignment emp={self.employee_id} shift={self.shift_type_id} from={self.from_date}>"


# -------------------------
# Employee Checkin
# -------------------------


class EmployeeCheckin(BaseModel):
    """
    Raw IN/OUT logs from biometric device or app.
    Used by auto-attendance.
    """
    __tablename__ = "employee_checkins"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    log_time: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    log_type: Mapped[CheckinLogTypeEnum] = mapped_column(
        db.Enum(CheckinLogTypeEnum, name="checkin_log_type_enum"),
        nullable=False,
        index=True,
    )

    source: Mapped[CheckinSourceEnum] = mapped_column(
        db.Enum(CheckinSourceEnum, name="checkin_source_enum"),
        nullable=False,
        default=CheckinSourceEnum.DEVICE,  # 👈 default from device
        index=True,
    )

    device_id: Mapped[Optional[str]] = mapped_column(db.String(100))
    skip_auto_attendance: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, index=True
    )

    raw_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Optional raw body from the device/API",
    )

    __table_args__ = (
        Index("ix_checkin_company_time", "company_id", "log_time"),
        Index("ix_checkin_emp_time", "employee_id", "log_time"),
        # optional, but very useful:
        UniqueConstraint("employee_id", "log_time", name="uq_checkin_emp_time"),
    )
    employee = db.relationship("Employee", lazy="joined", back_populates="checkins")
    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<EmployeeCheckin emp={self.employee_id} time={self.log_time} "
            f"type={self.log_type.value} source={self.source.value}>"
        )


# -------------------------
# Attendance
# -------------------------


class Attendance(BaseModel):
    """
    Final per-day attendance row (one per employee per date).
    Created either manually or by auto-attendance.
    """
    __tablename__ = "attendances"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    attendance_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)

    status: Mapped[AttendanceStatusEnum] = mapped_column(
        db.Enum(AttendanceStatusEnum, name="attendance_status_enum"),
        nullable=False,
        index=True,
    )

    shift_type_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("shift_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    in_time: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))
    out_time: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))

    working_hours: Mapped[float] = mapped_column(
        db.Numeric(5, 2), nullable=False, default=0
    )

    late_entry: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    early_exit: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    # "AUTO" (from checkins) vs "MANUAL" from HR
    source: Mapped[str] = mapped_column(
        db.String(20),
        nullable=False,
        default="AUTO",
        comment="AUTO or MANUAL",
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))

    __table_args__ = (
        UniqueConstraint("employee_id", "attendance_date", name="uq_attendance_emp_date"),
        Index("ix_attendance_company_date", "company_id", "attendance_date"),
        Index("ix_attendance_status", "company_id", "status"),
    )

    employee = db.relationship("Employee", lazy="joined", back_populates="attendances")
    company = db.relationship("Company", lazy="joined")
    branch = db.relationship("Branch", lazy="joined")
    shift_type = db.relationship("ShiftType", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<Attendance emp={self.employee_id} date={self.attendance_date} "
            f"status={self.status.value}>"
        )


# -------------------------
# Payroll Core
# -------------------------


class PayrollPeriod(BaseModel):
    """
    Simple payroll period (e.g. November 2025 for a company).
    """
    __tablename__ = "payroll_periods"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(db.String(140), nullable=False)
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(db.Date, nullable=False)

    # close period once slips are finalized
    is_closed: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False, index=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_payroll_period_company_name"),
    )

    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return f"<PayrollPeriod id={self.id} name={self.name!r} company_id={self.company_id}>"


class SalaryStructure(BaseModel):
    """
    Minimal salary structure (like ERPNext Salary Structure but very lean).
    """
    __tablename__ = "salary_structures"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(db.String(140), nullable=False)

    payment_frequency: Mapped[PaymentFrequencyEnum] = mapped_column(
        db.Enum(PaymentFrequencyEnum, name="payment_frequency_enum"),
        nullable=False,
        default=PaymentFrequencyEnum.MONTHLY,
    )

    currency: Mapped[Optional[str]] = mapped_column(db.String(10))

    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_salary_structure_company_name"),
    )

    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return f"<SalaryStructure id={self.id} name={self.name!r} company_id={self.company_id}>"


class EmployeeSalaryAssignment(BaseModel):
    """
    Assigns a salary structure to an employee from a given date.
    You can change structure over time.
    """
    __tablename__ = "employee_salary_assignments"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    salary_structure_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("salary_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    from_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    to_date: Mapped[Optional[date]] = mapped_column(db.Date)

    # basic gross amount (you can later break into components if needed)
    base_salary: Mapped[float] = mapped_column(db.Numeric(12, 2), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("employee_id", "from_date", name="uq_salary_assign_emp_from"),
    )

    employee = db.relationship("Employee", lazy="joined")
    company = db.relationship("Company", lazy="joined")
    salary_structure = db.relationship("SalaryStructure", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<EmployeeSalaryAssignment emp={self.employee_id} "
            f"struct={self.salary_structure_id} from={self.from_date}>"
        )


class SalarySlip(BaseModel):
    """
    One salary slip per employee per payroll period.
    This is what you post to Accounts / GL later.
    """
    __tablename__ = "salary_slips"

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payroll_period_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    posting_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    start_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(db.Date, nullable=False)

    gross_pay: Mapped[float] = mapped_column(db.Numeric(12, 2), nullable=False, default=0)
    total_deductions: Mapped[float] = mapped_column(db.Numeric(12, 2), nullable=False, default=0)
    net_pay: Mapped[float] = mapped_column(db.Numeric(12, 2), nullable=False, default=0)

    # use central DocStatusEnum instead of custom payroll status
    doc_status: Mapped[DocStatusEnum] = mapped_column(
        db.Enum(DocStatusEnum),
        nullable=False,
        default=DocStatusEnum.DRAFT,
        index=True,
    )

    remarks: Mapped[Optional[str]] = mapped_column(db.String(255))
    extra: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Any computed breakdown or metadata you don't want in columns yet",
    )

    __table_args__ = (
        UniqueConstraint("employee_id", "payroll_period_id", name="uq_salary_slip_emp_period"),
        Index("ix_salary_slip_company_period", "company_id", "payroll_period_id"),
    )

    employee = db.relationship("Employee", lazy="joined")
    company = db.relationship("Company", lazy="joined")
    payroll_period = db.relationship("PayrollPeriod", lazy="joined")

    def __repr__(self) -> str:
        return f"<SalarySlip emp={self.employee_id} period={self.payroll_period_id} net={self.net_pay}>"


class BiometricDevice(BaseModel):
    """
    Physical biometric device (ZKTeco, etc.) registered for a company.
    Used by the sync agent to know IP/port and by HR to manage devices.
    """
    __tablename__ = "biometric_devices"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human-readable name (for UI)
    name: Mapped[str] = mapped_column(db.String(140), nullable=False)

    # Short code / ID, used also by the agent & EmployeeCheckin.device_id
    code: Mapped[str] = mapped_column(db.String(64), nullable=False)

    # Network configuration
    ip_address: Mapped[str] = mapped_column(db.String(64), nullable=False)
    port: Mapped[int] = mapped_column(db.Integer, nullable=False, default=4370)
    password: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    timeout: Mapped[int] = mapped_column(db.Integer, nullable=False, default=30)

    # Optional metadata
    location: Mapped[Optional[str]] = mapped_column(
        db.String(255),
        nullable=True,
        comment="Physical location, e.g. HQ Main Gate",
    )

    is_active: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Last time the agent successfully pulled data from this device",
    )

    extra: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Any future settings (punch mapping, shift id, etc.)",
    )

    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_biometric_device_company_code"),
        Index("ix_biometric_device_company_active", "company_id", "is_active"),
    )

    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return (
            f"<BiometricDevice id={self.id} code={self.code!r} "
            f"company_id={self.company_id} ip={self.ip_address}:{self.port}>"
        )
