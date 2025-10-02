# app/application_parties/dropdown_builders/parties_dropdown.py
from __future__ import annotations
from sqlalchemy import select, case
from sqlalchemy.orm import Session
from typing import Mapping, Any

from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_org.models.company import Branch, Company
from app.security.rbac_effective import AffiliationContext


# --- Common scoping helpers ---
def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)


def _is_super_admin(ctx: AffiliationContext) -> bool:
    """Check if user is a super admin (has Super Admin role)"""
    roles = getattr(ctx, "roles", []) or []
    return "Super Admin" in roles


def _is_company_owner(ctx: AffiliationContext) -> bool:
    """Check if user is a company owner (has primary affiliation with branch_id null)"""
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    """Check if user has company-wide access (system admin, super admin, or company owner)"""
    return getattr(ctx, "is_system_admin", False) or _is_super_admin(ctx) or _is_company_owner(ctx)


def _get_user_branch_ids(ctx: AffiliationContext) -> list[int]:
    """Get list of branch IDs the user has access to"""
    return list(getattr(ctx, "branch_ids", []) or [])


# Suppliers Dropdown (role = SUPPLIER)
def build_suppliers_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for suppliers with ERP-style presentation
    - Super Admins & Company Owners: ALL suppliers in company
    - Regular users: suppliers from their branches + company-wide suppliers
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Party.id.label("value")).where(Party.id == -1)

    # Build location display
    location_display = case(
        (Party.branch_id.is_(None), "Company Wide"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            Party.email.label("email"),
            Party.phone.label("phone"),
            location_display,
            Party.branch_id.label("branch_id"),
        )
        .select_from(Party)
        .join(Company, Company.id == Party.company_id)
        .outerjoin(Branch, Branch.id == Party.branch_id)
        .where(
            Party.company_id == co_id,
            Party.role == PartyRoleEnum.SUPPLIER,
            Party.status == "Active"  # Only active parties
        )
        .order_by(
            # Company-wide first, then by branch
            case((Party.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Party.name.asc()
        )
    )

    # Apply branch restrictions for non-company-wide users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: company-wide suppliers + suppliers from their branches
            q = q.where(
                (Party.branch_id.is_(None)) |  # Company-wide suppliers
                (Party.branch_id.in_(branch_ids))  # Suppliers from their branches
            )
        else:
            # Users with no branch access: only company-wide suppliers
            q = q.where(Party.branch_id.is_(None))

    return q


# Customers Dropdown (role = CUSTOMER)
def build_customers_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for customers with ERP-style presentation
    - Super Admins & Company Owners: ALL customers in company
    - Regular users: customers from their branches + company-wide customers
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Party.id.label("value")).where(Party.id == -1)

    # Build location display
    location_display = case(
        (Party.branch_id.is_(None), "Company Wide"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            Party.email.label("email"),
            Party.phone.label("phone"),
            location_display,
            Party.branch_id.label("branch_id"),
        )
        .select_from(Party)
        .join(Company, Company.id == Party.company_id)
        .outerjoin(Branch, Branch.id == Party.branch_id)
        .where(
            Party.company_id == co_id,
            Party.role == PartyRoleEnum.CUSTOMER,
            Party.status == "Active"  # Only active parties
        )
        .order_by(
            # Company-wide first, then by branch
            case((Party.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Party.name.asc()
        )
    )

    # Apply branch restrictions for non-company-wide users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: company-wide customers + customers from their branches
            q = q.where(
                (Party.branch_id.is_(None)) |  # Company-wide customers
                (Party.branch_id.in_(branch_ids))  # Customers from their branches
            )
        else:
            # Users with no branch access: only company-wide customers
            q = q.where(Party.branch_id.is_(None))

    return q


# All Parties Dropdown (both suppliers and customers)
def build_all_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for all parties with ERP-style presentation
    - Super Admins & Company Owners: ALL parties in company
    - Regular users: parties from their branches + company-wide parties
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Party.id.label("value")).where(Party.id == -1)

    # Build location display and type indicator
    location_display = case(
        (Party.branch_id.is_(None), "Company Wide"),
        else_=Branch.name
    ).label("location")

    role_display = case(
        (Party.role == PartyRoleEnum.SUPPLIER, "Supplier"),
        else_="Customer"
    ).label("type")

    q = (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            Party.email.label("email"),
            Party.phone.label("phone"),
            location_display,
            role_display,
            Party.branch_id.label("branch_id"),
            Party.role.label("role"),
        )
        .select_from(Party)
        .join(Company, Company.id == Party.company_id)
        .outerjoin(Branch, Branch.id == Party.branch_id)
        .where(
            Party.company_id == co_id,
            Party.status == "Active"  # Only active parties
        )
        .order_by(
            # Suppliers first, then customers
            case((Party.role == PartyRoleEnum.SUPPLIER, 0), else_=1),
            # Company-wide first, then by branch
            case((Party.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Party.name.asc()
        )
    )

    # Apply branch restrictions for non-company-wide users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: company-wide parties + parties from their branches
            q = q.where(
                (Party.branch_id.is_(None)) |  # Company-wide parties
                (Party.branch_id.in_(branch_ids))  # Parties from their branches
            )
        else:
            # Users with no branch access: only company-wide parties
            q = q.where(Party.branch_id.is_(None))

    return q


# Cash Parties Dropdown (is_cash_party = True)
def build_cash_parties_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Dropdown for cash parties (is_cash_party = True)
    - Typically used for walk-in customers or cash transactions
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Party.id.label("value")).where(Party.id == -1)

    # Build location display
    location_display = case(
        (Party.branch_id.is_(None), "Company Wide"),
        else_=Branch.name
    ).label("location")

    q = (
        select(
            Party.id.label("value"),
            Party.name.label("label"),
            Party.code.label("code"),
            location_display,
            Party.branch_id.label("branch_id"),
            Party.role.label("role"),
        )
        .select_from(Party)
        .join(Company, Company.id == Party.company_id)
        .outerjoin(Branch, Branch.id == Party.branch_id)
        .where(
            Party.company_id == co_id,
            Party.is_cash_party.is_(True),
            Party.status == "Active"
        )
        .order_by(
            # Company-wide first, then by branch
            case((Party.branch_id.is_(None), 0), else_=1),
            Branch.name.asc(),
            Party.name.asc()
        )
    )

    # Apply branch restrictions for non-company-wide users
    if not _has_company_wide_access(ctx):
        branch_ids = _get_user_branch_ids(ctx)
        if branch_ids:
            # Regular users: company-wide cash parties + cash parties from their branches
            q = q.where(
                (Party.branch_id.is_(None)) |  # Company-wide cash parties
                (Party.branch_id.in_(branch_ids))  # Cash parties from their branches
            )
        else:
            # Users with no branch access: only company-wide cash parties
            q = q.where(Party.branch_id.is_(None))

    return q