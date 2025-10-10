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

# Assets & Fixed Assets
from app.application_accounting.chart_of_accounts.assets_model import (
    AssetCategory, Asset, AssetDepreciationEntry
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
from app.application_sales.models import SalesInvoice, SalesInvoiceItem

# HR Module
from app.application_hr.models.hr import (
    Employee, EmployeeEmergencyContact, EmployeeAssignment,
    GenderEnum, PersonRelationshipEnum
)

# ==============================================================================
# ACCOUNTING MODELS
# ==============================================================================



# Assets & Fixed Assets
from app.application_accounting.chart_of_accounts.assets_model import (
    AssetCategory, Asset, AssetDepreciationEntry
)

# Accounting Policies & Rules
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, AccountSelectionRule,
    ModeOfPaymentTypeEnum, AccountUseRoleEnum, AccountRuleTypeEnum
)

# ==============================================================================
# EXPLICIT MODEL REGISTRY FOR SQLALCHEMY
# ==============================================================================

__all__ = [
    # ==================== CORE FOUNDATION ====================
    'Company', 'Branch', 'Department', 'City',
    'User', 'UserAffiliation', 'UserType',
    'Role', 'Permission', 'UserRole',

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

    # HR
    'Employee', 'EmployeeEmergencyContact', 'EmployeeAssignment',

    # ==================== ACCOUNTING ====================
    # Core Accounting
    'Account', 'JournalEntry', 'JournalEntryItem',
    'GeneralLedgerEntry', 'FiscalYear', 'CostCenter',
    'AccountBalance', 'PartyAccountBalance',
    'GLEntryTemplate', 'GLTemplateItem',

    # Assets
    'AssetCategory', 'Asset', 'AssetDepreciationEntry',

    # Policies & Rules
    'ModeOfPayment', 'AccountSelectionRule',

    # ==================== ENUMS ====================
    'DocStatusEnum', 'ItemTypeEnum',
    'AccountTypeEnum', 'ReportTypeEnum', 'DebitOrCreditEnum',
    'JournalEntryTypeEnum', 'PartyTypeEnum',
    'ModeOfPaymentTypeEnum', 'AccountUseRoleEnum', 'AccountRuleTypeEnum',
    'PartyNatureEnum', 'PartyRoleEnum',
    'GenderEnum', 'PersonRelationshipEnum'
]

# ==============================================================================
# OPTIONAL: Model count verification for production safety
# ==============================================================================
try:
    expected_models = len(__all__)
    imported_models = len([name for name in globals() if not name.startswith('_') and name in __all__])

    if imported_models == expected_models:
        print(f"✅ MODEL REGISTRY: Successfully imported {imported_models}/{expected_models} models")
    else:
        print(f"⚠️  MODEL REGISTRY: Imported {imported_models}/{expected_models} models - check for missing imports")

except Exception as e:
    print(f"❌ MODEL REGISTRY: Error during import verification: {e}")