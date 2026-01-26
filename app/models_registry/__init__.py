# app/models/__init__.py
"""
CENTRAL MODEL REGISTRY - Explicit is better than implicit
PRODUCTION-GRADE ERP MODEL REGISTRY
"""
from __future__ import annotations

# ==============================================================================
# CORE FOUNDATION MODELS (Loaded First - Critical Dependencies)
# ==============================================================================

# Organization Structure
from app.application_org.models.company import Company, Branch, Department, City

# Authentication & Users
from app.auth.models.users import User, UserAffiliation, UserType

# RBAC & Permissions
from app.application_rbac.rbac_models import Role, Permission, UserRole



# ==============================================================================
# ACCOUNTING MODELS (Import before inventory since ItemGroup references Account)
# ==============================================================================

# Core Accounting
from app.application_accounting.chart_of_accounts.models import (
    Account, AccountTypeEnum, ReportTypeEnum, DebitOrCreditEnum, PeriodClosingVoucher,
    JournalEntry, JournalEntryItem, JournalEntryTypeEnum,
    GeneralLedgerEntry, FiscalYear, CostCenter,
    AccountBalance, PartyAccountBalance, PartyTypeEnum,
    GLEntryTemplate, GLTemplateItem,
)
# ==============================================================================
# DATA IMPORT MODELS (Add this section - Import after core models)
# ==============================================================================

from app.application_data_import.models import (
    DataImport, DataImportTemplateField, DataImportLog,
    ImportStatus, ImportType, FileType
)
# Assets & Fixed Assets

from app.application_accounting.chart_of_accounts.assets_model import (
    AssetCategory, Asset, AssetDepreciationEntry,
    FinanceBook, AssetFinanceBook,
    AssetMovement, AssetMovementItem,
    AssetStatusEnum, DepreciationMethodEnum,
)
# ==============================================================================
# INVENTORY & STOCK MODELS
# ==============================================================================

# Inventory Models (Items, Brands, UOM) - Import before stock models
from app.application_nventory.inventory_models import (
    Item, ItemGroup, Brand, UnitOfMeasure,
    UOMConversion, ItemTypeEnum, PriceList, ItemPrice
)

# Stock Models (Warehouse, Stock Entries, Ledger)
from app.application_stock.stock_models import (
    Warehouse, Bin, StockEntry, StockEntryItem,
    StockLedgerEntry, StockReconciliation, StockReconciliationItem,
    DocumentType, DocStatusEnum
)



# ==============================================================================
# BUSINESS DOMAIN MODELS
# ==============================================================================

# Parties
from app.application_parties.parties_models import (
    Party, PartyOrganizationDetail, PartyCommercialPolicy,
    PartyNatureEnum, PartyRoleEnum
)

# Buying Module
from app.application_buying.models import (
    PurchaseQuotation, PurchaseQuotationItem,
    PurchaseReceipt, PurchaseReceiptItem,
    PurchaseInvoice, PurchaseInvoiceItem
)

# Sales Module
from app.application_selling.models import SalesInvoice, SalesInvoiceItem

# HR Module
from app.application_hr.models.hr import(
    # Core HR
    Employee,
    EmployeeEmergencyContact,
    EmployeeAssignment,

    # Attendance & Time
    HolidayList,
    Holiday,
    ShiftType,
    ShiftAssignment,
    EmployeeCheckin,
    Attendance,

    # Payroll
    PayrollPeriod,
    SalaryStructure,
    EmployeeSalaryAssignment,
    SalarySlip,
    BiometricDevice,

    # Enums
    EmploymentTypeEnum,
    AttendanceStatusEnum,
    CheckinLogTypeEnum,
    CheckinSourceEnum,
    PaymentFrequencyEnum,
)

# ==============================================================================
# ACCOUNTING MODELS
# ==============================================================================



# Assets & Fixed Assets
from app.application_accounting.chart_of_accounts.assets_model import (
    AssetCategory, Asset, AssetDepreciationEntry
)
# PAYMENT & EXPENSE MODELS
from app.application_accounting.chart_of_accounts.finance_model import (
    PaymentEntry, PaymentItem, PaymentTypeEnum,    Expense, ExpenseItem, ExpenseType
)


# Accounting Policies & Rules
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, ModeOfPaymentAccount, AccountAccessPolicy,
    ModeOfPaymentTypeEnum, AccountUseRoleEnum
)
# ==============================================================================
# EDUCATION CORE MODELS
# ==============================================================================

from app.application_education.institution.academic_model import (
    EducationSettings,
    AcademicYear,
    AcademicTerm,
    AcademicStatusEnum,
)

# ==============================================================================
# EDUCATION – STUDENTS & GUARDIANS
# ==============================================================================

from app.application_education.student.models import (
    Student,
    Guardian,
    StudentGuardian,
    BloodGroupEnum,
    OrphanStatusEnum,
)
# ==============================================================================
# EDUCATION – PROGRAMS & COURSES
# ==============================================================================

from app.application_education.programs.models.program_models import (
    Program,
    Course,
    ProgramCourse,
    ProgramTypeEnum,
    CourseTypeEnum,
)
# ==============================================================================
# EDUCATION – ENROLLMENTS & PROGRESSION
# ==============================================================================

from app.application_education.enrollments.enrollment_model import (
    ProgramEnrollment,
    CourseEnrollment,
    ProgramProgressionRule,
    EnrollmentStatusEnum,
    EnrollmentResultEnum,
)
# ==============================================================================
# EDUCATION – GROUPS & COHORTS
# ==============================================================================

from app.application_education.groups.student_group_model import (
    Section,
    Batch,
    StudentCategory,
    StudentGroup,
    StudentGroupMembership,
    GroupBasedOnEnum,
)

# ==============================================================================
# EDUCATION – SCHEDULING & ATTENDANCE
# ==============================================================================

from app.application_education.timetable.model import (
    # Scheduling
    SchoolSession,
    TimeSlot,
    CourseAssignment,
    Classroom,
    CourseScheduleSlot,

    # Attendance
    StudentAttendance,
    StudentAttendanceRow,

    # Enums
    WeekdayEnum,
    StudentAttendanceSourceEnum,
    StudentAttendanceStatusEnum,
)
# ==============================================================================
# EDUCATION - ASSESSMENT / EXAMS V2  (REGISTER HERE)
# ==============================================================================
from app.application_education.assessment.exams_model import (
    # Enums
    AssessmentEventStatusEnum,
    AssessmentAttendanceStatusEnum,
    ResultHoldTypeEnum,
    GradeRecalcJobStatusEnum,

    # Grading
    GradingScale,
    GradingScaleBreakpoint,

    # Templates
    AssessmentScheme,
    AssessmentComponent,
    AssessmentComponentRule,

    # Events + Marks
    AssessmentEvent,
    AssessmentMark,
    AssessmentCriterion,
    AssessmentMarkItem,

    # Aggregates + Holds + Jobs
    StudentCourseGrade,
    StudentAnnualResult,
    StudentResultHold,
    GradeRecalcJob,
)
# ==============================================================================
# EDUCATION – FEES
# ==============================================================================

from app.application_education.fees.fees_model import (
    # Enums
    FeeScheduleStatusEnum,
    StudentFeeAdjustmentTypeEnum,

    # Masters
    FeeCategory,
    FeeStructure,
    FeeStructureComponent,

    # Schedules
    FeeSchedule,
    FeeScheduleComponent,

    # Adjustments
    StudentFeeAdjustment,
)

# ==============================================================================
# EXPLICIT MODEL REGISTRY FOR SQLALCHEMY
# ==============================================================================

__all__ = [
    # ==================== CORE FOUNDATION ====================
    'Company', 'Branch', 'Department', 'City',
    'User', 'UserAffiliation', 'UserType',
    'Role', 'Permission', 'UserRole',
    # ==================== DATA IMPORT MODELS ====================
    'DataImport', 'DataImportTemplateField', 'DataImportLog',
    'ImportStatus', 'ImportType', 'FileType',
    # ==================== EDUCATION ====================
    'EducationSettings',
    'AcademicYear',
    'AcademicTerm',

    # ==================== INVENTORY & STOCK ====================
    # Stock Models
    'Warehouse', 'Bin', 'StockEntry', 'StockEntryItem',
    'StockLedgerEntry', 'StockReconciliation', 'StockReconciliationItem',
    'DocumentType',

    # Inventory Models
    'Item', 'ItemGroup', 'Brand', 'UnitOfMeasure',
    'UOMConversion', 'ItemPrice','PriceList',

    # ==================== BUSINESS DOMAINS ====================
    # Parties
    'Party', 'PartyOrganizationDetail', 'PartyCommercialPolicy',

    # Buying
    'PurchaseQuotation', 'PurchaseQuotationItem',
    'PurchaseReceipt', 'PurchaseReceiptItem',
    'PurchaseInvoice', 'PurchaseInvoiceItem',

    # Sales
    'SalesInvoice', 'SalesInvoiceItem',

    # ==================== HR & PAYROLL ====================
    'Employee',
    'EmployeeEmergencyContact',
    'EmployeeAssignment',

    'HolidayList',
    'Holiday',

    'ShiftType',
    'ShiftAssignment',

    'EmployeeCheckin',
    'Attendance',

    'PayrollPeriod',
    'SalaryStructure',
    'EmployeeSalaryAssignment',
    'SalarySlip',
    'BiometricDevice',
    # ==================== EDUCATION ====================
    # Core
    'EducationSettings',
    'AcademicYear',
    'AcademicTerm',

    # Groups & Cohorts
    'Section',
    'Batch',
    'StudentCategory',
    'StudentGroup',
    'StudentGroupMembership',

    # Students & Guardians
    'Student',
    'Guardian',
    'StudentGuardian',

    # Programs & Courses
    'Program',
    'Course',
    'ProgramCourse',

    # Enrollments & Progression
    'ProgramEnrollment',
    'CourseEnrollment',
    'ProgramProgressionRule',
    # Scheduling & Attendance
    'SchoolSession',
    'TimeSlot',
    'CourseAssignment',
    'Classroom',
    'CourseScheduleSlot',
    'StudentAttendance',
    'StudentAttendanceRow',

    "GradingScale", "GradingScaleBreakpoint",
    "AssessmentScheme", "AssessmentComponent", "AssessmentComponentRule",
    "AssessmentEvent", "AssessmentMark", "AssessmentCriterion", "AssessmentMarkItem",
    "StudentCourseGrade", "StudentAnnualResult", "StudentResultHold", "GradeRecalcJob",

    'FeeCategory',
    'FeeStructure',
    'FeeStructureComponent',
    'FeeSchedule',
    'FeeScheduleComponent',
    'StudentFeeAdjustment',

    # ==================== ACCOUNTING ====================
    # Core Accounting
    'Account', 'JournalEntry', 'JournalEntryItem',
    'GeneralLedgerEntry', 'FiscalYear', 'CostCenter',
    'AccountBalance', 'PartyAccountBalance',
    'GLEntryTemplate', 'GLTemplateItem',

    # Assets
    'AssetCategory', 'Asset', 'AssetDepreciationEntry',
    'FinanceBook', 'AssetFinanceBook',
    'AssetMovement', 'AssetMovementItem',

    # Policies & Rules
    'ModeOfPayment', 'ModeOfPaymentAccount', 'AccountAccessPolicy',
    # PAYMENT & EXPENSE MODELS
    'PaymentEntry', 'PaymentItem', 'Expense', 'ExpenseItem', 'ExpenseType',
    # ==================== ENUMS ====================
    'DocStatusEnum', 'ItemTypeEnum',
    'AccountTypeEnum', 'ReportTypeEnum', 'DebitOrCreditEnum',
    'JournalEntryTypeEnum', 'PartyTypeEnum',
    'ModeOfPaymentTypeEnum', 'AccountUseRoleEnum',
    'PartyNatureEnum', 'PartyRoleEnum',
    'GenderEnum', 'PersonRelationshipEnum', 'PaymentTypeEnum',
    'AssetStatusEnum', 'DepreciationMethodEnum','AcademicStatusEnum',
    'EmploymentTypeEnum',
    'AttendanceStatusEnum',
    'CheckinLogTypeEnum',
    'CheckinSourceEnum',
    'PaymentFrequencyEnum',

    # Education enums
    'ProgramTypeEnum',
    'CourseTypeEnum',
    'EnrollmentStatusEnum',
    'EnrollmentResultEnum',
    'BloodGroupEnum',
    'OrphanStatusEnum',
    'GroupBasedOnEnum',
    # Scheduling & Attendance enums
    'WeekdayEnum',
    'StudentAttendanceSourceEnum',
    'StudentAttendanceStatusEnum',
    # Exams v2 Enums
    "AssessmentEventStatusEnum", "AssessmentAttendanceStatusEnum",
    "ResultHoldTypeEnum", "GradeRecalcJobStatusEnum",
    # EDUCATION – FEES
    'FeeScheduleStatusEnum',
    'StudentFeeAdjustmentTypeEnum',

]

from app.common.models.base import GenderEnum, PersonRelationshipEnum

# ==============================================================================
# OPTIONAL: Model count verification for production safety
# ==============================================================================
try:
    expected = set(__all__)
    present = {name for name in expected if name in globals()}
    missing = sorted(expected - present)

    if not missing:
        print(f"✅ MODEL REGISTRY: Successfully imported {len(present)}/{len(expected)} models")
    else:
        print(f"⚠️  MODEL REGISTRY: Imported {len(present)}/{len(expected)} models - missing: {missing}")
except Exception as e:
    print(f"❌ MODEL REGISTRY: Error during import verification: {e}")