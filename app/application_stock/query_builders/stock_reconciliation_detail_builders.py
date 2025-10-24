from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime
from decimal import Decimal
import pytz

from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, func

from app.application_stock.stock_models import StockReconciliation, StockReconciliationItem
from app.application_org.models.company import Branch, Company
from app.auth.models.users import User
from app.application_nventory.inventory_models import Item
from app.application_stock.stock_models import Warehouse
from app.application_accounting.chart_of_accounts.models import Account
from app.security.rbac_effective import AffiliationContext
from werkzeug.exceptions import NotFound

# Default fallback timezone (Somalia - GMT+3)
DEFAULT_TZ = pytz.timezone('Africa/Mogadishu')


def _first_or_404(session: Session, stmt, entity_name: str) -> Dict[str, Any]:
    """Get first result or raise 404."""
    result = session.execute(stmt).mappings().first()
    if not result:
        raise NotFound(f"{entity_name} not found.")
    return dict(result)


def _get_company_timezone(session: Session, company_id: int) -> pytz.timezone:
    """Get company timezone or fallback to Somalia timezone."""
    stmt = select(Company.timezone).where(Company.id == company_id)
    result = session.execute(stmt).scalar()

    if result and result.strip():
        try:
            return pytz.timezone(result.strip())
        except pytz.UnknownTimeZoneError:
            return DEFAULT_TZ
    else:
        return DEFAULT_TZ


def resolve_stock_reconciliation_by_code(session: Session, context: AffiliationContext, code: str) -> Optional[int]:
    """Resolve stock reconciliation by code with RBAC check."""
    stmt = (
        select(StockReconciliation.id)
        .where(
            StockReconciliation.code == code,
            StockReconciliation.company_id == context.company_id
        )
    )

    # Apply branch filtering for non-admin users
    if not getattr(context, "is_system_admin", False):
        roles = getattr(context, "roles", []) or []
        has_company_wide_access = any(role in ["Owner", "Super Admin"] for role in roles)

        if not has_company_wide_access:
            branch_ids = list(getattr(context, "branch_ids", []) or [])
            if branch_ids:
                stmt = stmt.where(StockReconciliation.branch_id.in_(branch_ids))
            else:
                return None

    result = session.execute(stmt).scalar()
    return result


def resolve_stock_reconciliation_id_strict(session: Session, context: AffiliationContext, id_str: str) -> Optional[int]:
    """Resolve stock reconciliation by ID with RBAC check."""
    try:
        recon_id = int(id_str)
    except (ValueError, TypeError):
        return None

    stmt = (
        select(StockReconciliation.id)
        .where(
            StockReconciliation.id == recon_id,
            StockReconciliation.company_id == context.company_id
        )
    )

    # Apply branch filtering for non-admin users
    if not getattr(context, "is_system_admin", False):
        roles = getattr(context, "roles", []) or []
        has_company_wide_access = any(role in ["Owner", "Super Admin"] for role in roles)

        if not has_company_wide_access:
            branch_ids = list(getattr(context, "branch_ids", []) or [])
            if branch_ids:
                stmt = stmt.where(StockReconciliation.branch_id.in_(branch_ids))
            else:
                return None

    result = session.execute(stmt).scalar()
    return result


def load_stock_reconciliation_detail(session: Session, context: AffiliationContext, recon_id: int) -> Dict[str, Any]:
    """
    Load stock reconciliation detail with Frappe/ERPNext style structure.
    Uses database functions for date formatting in list, Python formatting in detail.
    """
    SR, SRI = StockReconciliation, StockReconciliationItem

    # Decimal formatter
    def _format_decimal(value: Optional[Decimal]) -> Optional[float]:
        return float(value) if value is not None else None

    # Enum value extractor
    def _enum_value(x) -> str:
        return getattr(x, "value", str(x))

    # Aliases for better readability
    DIFF_ACC = aliased(Account)

    # ---------- Header ----------
    header_stmt = (
        select(
            # Core document info
            SR.id, SR.code, SR.doc_status, SR.purpose,
            SR.posting_date, SR.notes,
            SR.company_id, SR.branch_id, SR.created_by_id,
            SR.difference_account_id,

            # Names and relationships
            Branch.name.label("branch_name"),
            Company.name.label("company_name"),
            Company.timezone.label("company_timezone"),
            User.username.label("created_by_name"),
            DIFF_ACC.name.label("difference_account_name"),

            # Formatted dates using database functions
            func.to_char(SR.posting_date, 'MM/DD/YYYY').label("posting_date_formatted"),
            func.to_char(SR.posting_date, 'HH12:MI AM').label("posting_time_formatted"),
        )
        .select_from(SR)
        .join(Company, Company.id == SR.company_id)
        .join(Branch, Branch.id == SR.branch_id)
        .join(User, User.id == SR.created_by_id)
        .outerjoin(DIFF_ACC, DIFF_ACC.id == SR.difference_account_id)
        .where(SR.id == recon_id)
    )
    hdr = _first_or_404(session, header_stmt, "Stock Reconciliation")

    # Security check
    from app.security.rbac_guards import ensure_scope_by_ids
    ensure_scope_by_ids(
        context=context,
        target_company_id=hdr["company_id"],
        target_branch_id=hdr["branch_id"]
    )

    # ---------- Items ----------
    items_stmt = (
        select(
            SRI.id, SRI.item_id, SRI.warehouse_id,
            Item.name.label("item_name"),
            Warehouse.name.label("warehouse_name"),

            # User input fields
            SRI.quantity, SRI.valuation_rate,

            # System calculated fields
            SRI.current_qty, SRI.current_valuation_rate,

            # Difference calculations
            SRI.qty_difference, SRI.amount_difference,

            # Additional info
            SRI.reconciliation_id
        )
        .select_from(SRI)
        .join(Item, Item.id == SRI.item_id)
        .join(Warehouse, Warehouse.id == SRI.warehouse_id)
        .where(SRI.reconciliation_id == recon_id)
        .order_by(SRI.id.asc())
    )
    rows = session.execute(items_stmt).mappings().all()

    # Process items with formatted values
    items = []
    total_qty_difference = Decimal('0')
    total_amount_difference = Decimal('0')

    for row in rows:
        item_data = dict(row)

        # Format decimal values
        item_data["quantity"] = _format_decimal(item_data["quantity"])
        item_data["valuation_rate"] = _format_decimal(item_data["valuation_rate"])
        item_data["current_qty"] = _format_decimal(item_data["current_qty"])
        item_data["current_valuation_rate"] = _format_decimal(item_data["current_valuation_rate"])
        item_data["qty_difference"] = _format_decimal(item_data["qty_difference"])
        item_data["amount_difference"] = _format_decimal(item_data["amount_difference"])

        # Calculate totals
        if item_data["qty_difference"]:
            total_qty_difference += Decimal(str(item_data["qty_difference"]))
        if item_data["amount_difference"]:
            total_amount_difference += Decimal(str(item_data["amount_difference"]))

        items.append(item_data)

    # Build the structured response (Frappe/ERPNext style)
    data: Dict[str, Any] = {
        # ===== Basic Document Info =====
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "doc_status": _enum_value(hdr["doc_status"]),
            "purpose": _enum_value(hdr["purpose"]),
            "posting_date": hdr["posting_date_formatted"],  # Use database-formatted date
            "posting_time": hdr["posting_time_formatted"],  # Use database-formatted time
            "notes": hdr["notes"],
        },

        # ===== Company & Branch Context =====
        "company_context": {
            "company_id": hdr["company_id"],
            "company_name": hdr["company_name"],
            "company_timezone": hdr.get("company_timezone") or "Africa/Mogadishu",
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
        },

        # ===== Created By Info =====
        "created_by": {
            "user_id": hdr["created_by_id"],
            "username": hdr["created_by_name"],
        },

        # ===== Accounting Configuration =====
        "accounting_config": {
            "difference_account": {
                "id": hdr.get("difference_account_id"),
                "name": hdr.get("difference_account_name"),
            }
        },

        # ===== Reconciliation Summary =====
        "reconciliation_summary": {
            "total_items": len(items),
            "total_qty_difference": float(total_qty_difference),
            "total_amount_difference": float(total_amount_difference),
            "items_with_differences": sum(1 for item in items if item.get("qty_difference", 0) != 0),
        },

        # ===== Items Grid =====
        "items": items,

        # ===== Meta Information =====
        "meta": {
            "notes": hdr["notes"],
        },
    }

    return data