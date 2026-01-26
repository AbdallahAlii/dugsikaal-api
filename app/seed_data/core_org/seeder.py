
from __future__ import annotations
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.models.base import StatusEnum
from app.common.timezone.service import now_in_company_tz, get_company_timezone
from app.application_accounting.chart_of_accounts.models import (
    Account,
    FiscalYear,
    FiscalYearStatusEnum,
    CostCenter,
)
from app.application_nventory.inventory_models import (
    Brand,
    UnitOfMeasure,
    ItemGroup,
    PriceList,
)
from app.application_stock.stock_models import Warehouse
from app.application_parties.parties_models import (
    Party,
    PartyNatureEnum,
    PartyRoleEnum,
)
from app.application_org.models.company import Company, Branch
from app.application_hr.models.hr import HolidayList, Holiday, ShiftType
from .data import (
    DEFAULT_UOMS,
    DEFAULT_BRANDS,
    DEFAULT_ITEM_GROUPS,
    DEFAULT_PRICE_LISTS,
    DEFAULT_CASH_PARTIES,
    FISCAL_YEAR_NAME_TEMPLATE,
    DEFAULT_HOLIDAY_LIST_BASE_NAME,
    DEFAULT_WEEKLY_OFF_DAYS,
    HOLIDAY_WEEKLY_OFF_DESCRIPTION_TEMPLATE,
    DEFAULT_SHIFT_TYPES,
    DEFAULT_COST_CENTER_NAME_TEMPLATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters):
    """
    Small helper used during seeding.

    IMPORTANT:
      - We DO NOT call db.rollback() here.
      - If an IntegrityError occurs, we raise it so the outer service
        can rollback the *entire* company/branch creation and return
        a proper error to the API caller.

    This avoids the previous behaviour where a rollback here wiped the
    newly created Company/Branch, but seeding code continued and the
    service still returned "success".
    """
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False

    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    try:
        db.flush([obj])
        return obj, True
    except IntegrityError:
        # Let the caller (OrgService) handle rollback and error reporting.
        logger.exception(
            "IntegrityError in _get_or_create for %s with filters=%s",
            getattr(model, "__name__", str(model)),
            filters,
        )
        raise


def _acct_index(db: Session, company_id: int) -> Dict[str, Account]:
    rows = db.scalars(
        select(Account).where(Account.company_id == company_id)
    ).all()
    return {a.code: a for a in rows}


# ---------------------------------------------------------------------------
# UOMs
# ---------------------------------------------------------------------------
def _seed_uoms(db: Session, company_id: int) -> None:
    created = 0
    for row in DEFAULT_UOMS:
        name = row["name"]
        symbol = row["symbol"]
        _, was_created = _get_or_create(
            db,
            UnitOfMeasure,
            company_id=company_id,
            name=name,
            defaults=dict(
                symbol=symbol,
                status=StatusEnum.ACTIVE,
            ),
        )
        if was_created:
            created += 1
    logger.info("CoreOrg: UOMs seeded for company_id=%s (created=%d)", company_id, created)


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
def _seed_brands(db: Session, company_id: int) -> None:
    created = 0
    for row in DEFAULT_BRANDS:
        name = row["name"]
        _, was_created = _get_or_create(
            db,
            Brand,
            company_id=company_id,
            name=name,
            defaults=dict(status=StatusEnum.ACTIVE),
        )
        if was_created:
            created += 1
    logger.info("CoreOrg: Brands seeded for company_id=%s (created=%d)", company_id, created)


# ---------------------------------------------------------------------------
# Item Groups (with default accounts)
# ---------------------------------------------------------------------------
def _seed_item_groups(db: Session, company_id: int) -> None:
    """
    Seed a small, useful Item Group tree with default accounts resolved from COA.
    """
    logger.info("CoreOrg: Seeding ItemGroups for company_id=%s", company_id)

    acct_idx = _acct_index(db, company_id)
    logger.debug("CoreOrg: COA accounts loaded for company_id=%s count=%d", company_id, len(acct_idx))

    existing = db.scalars(
        select(ItemGroup).where(ItemGroup.company_id == company_id)
    ).all()
    code_to_group: Dict[str, ItemGroup] = {g.code: g for g in existing}

    logger.debug(
        "CoreOrg: Existing ItemGroups for company_id=%s count=%d codes=%s",
        company_id, len(existing), sorted(list(code_to_group.keys()))
    )

    created = 0
    updated = 0

    remaining: List[dict] = list(DEFAULT_ITEM_GROUPS)
    logger.debug(
        "CoreOrg: DEFAULT_ITEM_GROUPS rows=%d codes=%s",
        len(remaining), [r.get("code") for r in remaining]
    )

    safety_guard = 0

    while remaining and safety_guard < 20:
        safety_guard += 1
        logger.debug("CoreOrg: ItemGroup seed pass=%d remaining=%d", safety_guard, len(remaining))

        still_pending: List[dict] = []

        for row in remaining:
            code = row["code"]
            parent_code = row.get("parent_code")
            is_group = bool(row.get("is_group", False))
            name = row["name"]

            default_expense_code = row.get("default_expense_code")
            default_income_code = row.get("default_income_code")
            default_inventory_code = row.get("default_inventory_code")

            # Resolve parent
            parent_id: Optional[int] = None
            if parent_code:
                parent = code_to_group.get(parent_code)
                if not parent:
                    logger.debug(
                        "CoreOrg: PENDING ItemGroup code=%s because parent_code=%s not created yet",
                        code, parent_code
                    )
                    still_pending.append(row)
                    continue
                parent_id = int(parent.id)

            # Resolve default accounts from COA (best-effort)
            def _acct_id(code_: Optional[str]) -> Optional[int]:
                if not code_:
                    return None
                acct = acct_idx.get(code_)
                if not acct:
                    logger.warning(
                        "CoreOrg: Account code %r not found for ItemGroup %r (company_id=%s)",
                        code_, code, company_id,
                    )
                    return None
                return int(acct.id)

            default_expense_id = _acct_id(default_expense_code)
            default_income_id = _acct_id(default_income_code)
            default_inventory_id = _acct_id(default_inventory_code)

            logger.debug(
                "CoreOrg: Processing ItemGroup code=%s name=%s parent_code=%s parent_id=%s is_group=%s "
                "expense_code=%s income_code=%s inventory_code=%s",
                code, name, parent_code, parent_id, is_group,
                default_expense_code, default_income_code, default_inventory_code
            )

            grp = code_to_group.get(code)
            if not grp:
                grp = ItemGroup(
                    company_id=company_id,
                    code=code,
                    name=name,
                    is_group=is_group,
                    parent_item_group_id=parent_id,
                    default_expense_account_id=default_expense_id,
                    default_income_account_id=default_income_id,
                    default_inventory_account_id=default_inventory_id,
                )
                db.add(grp)
                db.flush([grp])
                code_to_group[code] = grp
                created += 1
                logger.debug("CoreOrg: CREATED ItemGroup code=%s id=%s", code, grp.id)
            else:
                changed = False
                if grp.name != name:
                    grp.name = name
                    changed = True
                if grp.is_group != is_group:
                    grp.is_group = is_group
                    changed = True
                if grp.parent_item_group_id != parent_id:
                    grp.parent_item_group_id = parent_id
                    changed = True
                if grp.default_expense_account_id != default_expense_id:
                    grp.default_expense_account_id = default_expense_id
                    changed = True
                if grp.default_income_account_id != default_income_id:
                    grp.default_income_account_id = default_income_id
                    changed = True
                if grp.default_inventory_account_id != default_inventory_id:
                    grp.default_inventory_account_id = default_inventory_id
                    changed = True

                if changed:
                    updated += 1
                    logger.debug("CoreOrg: UPDATED ItemGroup code=%s id=%s", code, grp.id)

        # stuck guard
        if len(still_pending) == len(remaining):
            logger.error(
                "CoreOrg: ItemGroup seeding STUCK company_id=%s pending_codes=%s",
                company_id, [r.get("code") for r in still_pending]
            )
            break

        remaining = still_pending

    if remaining:
        logger.error(
            "CoreOrg: Some Item Groups could not be seeded for company_id=%s pending=%s",
            company_id, [r.get("code") for r in remaining]
        )

    total_after = db.scalar(
        select(func.count(ItemGroup.id)).where(ItemGroup.company_id == company_id)
    ) or 0

    logger.info(
        "CoreOrg: ItemGroups seeded for company_id=%s (created=%d, updated=%d, total_now=%d)",
        company_id, created, updated, int(total_after)
    )


# ---------------------------------------------------------------------------
# Price Lists
# ---------------------------------------------------------------------------
def _seed_price_lists(db: Session, company_id: int) -> None:
    from app.application_nventory.inventory_models import PriceListType  # local import to avoid cycles

    created = 0
    updated = 0
    for row in DEFAULT_PRICE_LISTS:
        name = row["name"]
        list_type_str = row["list_type"]
        list_type = PriceListType[list_type_str]  # "BUYING" | "SELLING" | "BOTH"

        pl, was_created = _get_or_create(
            db,
            PriceList,
            company_id=company_id,
            name=name,
            defaults=dict(
                list_type=list_type,
                price_not_uom_dependent=bool(row.get("price_not_uom_dependent", True)),
                is_active=bool(row.get("is_active", True)),
            ),
        )
        if was_created:
            created += 1
        else:
            changed = False
            if pl.list_type != list_type:
                pl.list_type = list_type
                changed = True
            if pl.price_not_uom_dependent != bool(row.get("price_not_uom_dependent", True)):
                pl.price_not_uom_dependent = bool(row.get("price_not_uom_dependent", True))
                changed = True
            if pl.is_active != bool(row.get("is_active", True)):
                pl.is_active = bool(row.get("is_active", True))
                changed = True
            if changed:
                updated += 1

    logger.info(
        "CoreOrg: PriceLists seeded for company_id=%s (created=%d, updated=%d)",
        company_id,
        created,
        updated,
    )


# ---------------------------------------------------------------------------
# Cash Parties
# ---------------------------------------------------------------------------
def _existing_cash_party(db: Session, company_id: int, role: PartyRoleEnum) -> Optional[Party]:
    return db.scalar(
        select(Party).where(
            Party.company_id == company_id,
            Party.role == role,
            Party.is_cash_party.is_(True),
        )
    )


def _seed_cash_parties(db: Session, company_id: int) -> None:
    created = 0
    for row in DEFAULT_CASH_PARTIES:
        code = row["code"]
        name = row["name"]

        role = PartyRoleEnum[row["role"]]
        nature = PartyNatureEnum[row["nature"]]

        # One cash party per (company, role)
        if _existing_cash_party(db, company_id, role):
            logger.info(
                "CoreOrg: Cash %s party already exists for company_id=%s; skipping.",
                role.value,
                company_id,
            )
            continue

        # Avoid duplicate code too
        existing_by_code = db.scalar(
            select(Party).where(
                Party.company_id == company_id,
                Party.code == code,
            )
        )
        if existing_by_code:
            logger.info(
                "CoreOrg: Party with code %s already exists for company_id=%s; skipping.",
                code,
                company_id,
            )
            continue

        p = Party(
            company_id=company_id,
            branch_id=None,
            code=code,
            name=name,
            nature=nature,
            role=role,
            email=None,
            phone=None,
            address_line1=None,
            city_id=None,
            is_cash_party=True,
            notes=None,
            img_key=None,
            status=StatusEnum.ACTIVE,
        )
        db.add(p)
        db.flush([p])
        created += 1

    logger.info(
        "CoreOrg: Cash Parties seeded for company_id=%s (created=%d)",
        company_id,
        created,
    )


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------
def _next_warehouse_code(db: Session, company_id: int) -> str:
    """
    Generate next warehouse code for a company in the format:

        WH-001, WH-002, WH-003, ...

    For a brand new company (no warehouses yet), this returns WH-001.
    """
    max_n = 0
    rows = db.scalars(
        select(Warehouse.code).where(Warehouse.company_id == company_id)
    ).all()

    for code in rows:
        if not code:
            continue
        code = code.strip()
        if not code.startswith("WH-"):
            continue
        suffix = code[3:]
        if not suffix.isdigit():
            continue
        try:
            n = int(suffix)
        except ValueError:
            continue
        if n > max_n:
            max_n = n

    return f"WH-{max_n + 1:03d}"


def _ensure_root_warehouse(db: Session, company_id: int) -> Warehouse:
    """
    Ensure the company-level root warehouse group exists.

    - Root has name 'All Warehouses'
    - parent_warehouse_id = NULL
    - is_group = True
    - Code is WH-001 for a fresh company, otherwise next free WH-xxx.
    """
    root = db.scalar(
        select(Warehouse)
        .where(
            Warehouse.company_id == company_id,
            Warehouse.parent_warehouse_id.is_(None),
            Warehouse.is_group.is_(True),
        )
        .order_by(Warehouse.id)
    )
    if root:
        return root

    code = _next_warehouse_code(db, company_id)
    root, _ = _get_or_create(
        db,
        Warehouse,
        company_id=company_id,
        branch_id=None,
        name="All Warehouses",
        defaults=dict(
            code=code,
            description=None,
            is_group=True,
            parent_warehouse_id=None,
            status=StatusEnum.ACTIVE,
        ),
    )
    return root


def _seed_warehouses(db: Session, company_id: int) -> None:
    """
    Seed warehouse tree:

    - Company root group: 'All Warehouses' (company-level, no branch)
    - If branches exist:
        For the first branch:
          - Group: '<Branch Name> Warehouses'
          - Leaf: 'Main Store'
          - Leaf: 'Goods in Transit'
    """
    root = _ensure_root_warehouse(db, company_id)

    # Try to attach a basic subtree to the first branch (if any)
    branch = db.scalar(
        select(Branch)
        .where(Branch.company_id == company_id)
        .order_by(Branch.id)
    )
    if not branch:
        logger.info(
            "CoreOrg: No branches yet for company_id=%s; only root warehouse group created.",
            company_id,
        )
        return

    seed_warehouses_for_branch(db, company_id=company_id, branch_id=branch.id)


def seed_warehouses_for_branch(db: Session, company_id: int, branch_id: int) -> None:
    """
    Idempotently seed warehouse structure for a specific branch:

      - Ensure company root 'All Warehouses' exists.
      - Create branch group '<Branch Name> Warehouses' under root.
      - Create leaf 'Main Store'.
      - Create leaf 'Goods in Transit'.

    All warehouse codes use WH-001 / WH-002 / WH-003 ... per company.
    Safe to call multiple times for the same branch.
    """
    root = _ensure_root_warehouse(db, company_id)

    # Load branch
    branch = db.scalar(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.company_id == company_id,
        )
    )
    if not branch:
        logger.warning(
            "CoreOrg: seed_warehouses_for_branch called with unknown branch_id=%s company_id=%s",
            branch_id,
            company_id,
        )
        return

    # Branch group under root
    branch_group, _ = _get_or_create(
        db,
        Warehouse,
        company_id=company_id,
        branch_id=branch.id,
        name=f"{branch.name} Warehouses",
        defaults=dict(
            code=_next_warehouse_code(db, company_id),
            description=None,
            is_group=True,
            parent_warehouse_id=root.id,
            status=StatusEnum.ACTIVE,
        ),
    )

    # Leaf: Main Store
    _get_or_create(
        db,
        Warehouse,
        company_id=company_id,
        branch_id=branch.id,
        name="Main Store",
        defaults=dict(
            code=_next_warehouse_code(db, company_id),
            description="Primary stock location",
            is_group=False,
            parent_warehouse_id=branch_group.id,
            status=StatusEnum.ACTIVE,
        ),
    )

    # Leaf: Goods in Transit
    _get_or_create(
        db,
        Warehouse,
        company_id=company_id,
        branch_id=branch.id,
        name="Goods in Transit",
        defaults=dict(
            code=_next_warehouse_code(db, company_id),
            description="In-transit / in-transfer goods",
            is_group=False,
            parent_warehouse_id=branch_group.id,
            status=StatusEnum.ACTIVE,
        ),
    )

    logger.info(
        "CoreOrg: Warehouses seeded for company_id=%s, branch_id=%s (group + Main + GIT)",
        company_id,
        branch.id,
    )


# ---------------------------------------------------------------------------
# Fiscal Year + Holiday List + Shift Types
# ---------------------------------------------------------------------------
def _seed_fiscal_year(db: Session, company_id: int) -> FiscalYear:
    """
    Ensure the company has at least one fiscal year.
    We create a current-year FY if none exist:

        name:  'FY YYYY'
        start: YYYY-01-01 00:00 (company tz)
        end:   YYYY-12-31 23:59:59 (company tz)
    """
    existing = db.scalar(
        select(FiscalYear)
        .where(FiscalYear.company_id == company_id)
        .order_by(FiscalYear.start_date)
    )
    if existing:
        return existing

    # Use company timezone helper
    now = now_in_company_tz(db, company_id)
    tz = get_company_timezone(db, company_id)
    year = now.year

    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(year, 12, 31, 23, 59, 59, tzinfo=tz)

    fy_name = FISCAL_YEAR_NAME_TEMPLATE.format(year=year)

    fy = FiscalYear(
        company_id=company_id,
        name=fy_name,
        start_date=start,
        end_date=end,
        status=FiscalYearStatusEnum.OPEN,
        is_short_year=False,
    )
    db.add(fy)
    db.flush([fy])

    logger.info(
        "CoreOrg: FiscalYear seeded for company_id=%s name=%s",
        company_id,
        fy.name,
    )
    return fy


def _seed_holiday_list(db: Session, company_id: int, fiscal_year: FiscalYear) -> HolidayList:
    """
    Ensure a default holiday list exists for the company.
    Also auto-create weekly off holidays for configured weekdays.
    """
    hl = db.scalar(
        select(HolidayList).where(
            HolidayList.company_id == company_id,
            HolidayList.is_default.is_(True),
        )
    )
    if hl:
        return hl

    year = fiscal_year.start_date.year
    hl_name = f"{DEFAULT_HOLIDAY_LIST_BASE_NAME} {year}"

    hl = HolidayList(
        company_id=company_id,
        name=hl_name,
        from_date=fiscal_year.start_date.date(),
        to_date=fiscal_year.end_date.date(),
        is_default=True,
    )
    db.add(hl)
    db.flush([hl])

    # Auto-create weekly off holidays (Thursday + Friday for Somalia, by default)
    d: date = hl.from_date
    while d <= hl.to_date:
        if d.weekday() in DEFAULT_WEEKLY_OFF_DAYS:
            # ensure not already present
            existing = db.scalar(
                select(Holiday).where(
                    Holiday.holiday_list_id == hl.id,
                    Holiday.holiday_date == d,
                )
            )
            if not existing:
                desc = HOLIDAY_WEEKLY_OFF_DESCRIPTION_TEMPLATE.format(
                    weekday_name=d.strftime("%A")
                )
                h = Holiday(
                    holiday_list_id=hl.id,
                    holiday_date=d,
                    description=desc,
                    is_full_day=True,
                    is_weekly_off=True,
                )
                db.add(h)
        d += timedelta(days=1)

    logger.info(
        "CoreOrg: HolidayList seeded for company_id=%s name=%s with weekly offs",
        company_id,
        hl.name,
    )
    return hl


def _seed_shift_types(db: Session, company_id: int, holiday_list: Optional[HolidayList]) -> None:
    """
    Seed basic shift types for a company (e.g. 'Day Shift').
    Uses DEFAULT_SHIFT_TYPES config and links them to the default holiday list.
    """
    created = 0
    for row in DEFAULT_SHIFT_TYPES:
        name = row["name"]

        existing = db.scalar(
            select(ShiftType).where(
                ShiftType.company_id == company_id,
                ShiftType.name == name,
            )
        )
        if existing:
            continue

        st = ShiftType(
            company_id=company_id,
            name=name,
            start_time=row["start_time"],
            end_time=row["end_time"],
            enable_auto_attendance=row.get("enable_auto_attendance", False),
            is_night_shift=row.get("is_night_shift", False),
            holiday_list_id=holiday_list.id if holiday_list else None,
        )
        db.add(st)
        db.flush([st])
        created += 1

    if created:
        logger.info(
            "CoreOrg: ShiftTypes seeded for company_id=%s (created=%d)",
            company_id,
            created,
        )


def seed_company_fiscal_and_hr_defaults(db: Session, company_id: int) -> None:
    """
    Seed Fiscal Year, default Holiday List, and default Shift Types
    for a company, ERP-style.

    NOTE: Does not commit; caller must commit/rollback.

    If the company does not exist, this is treated as a HARD error and
    should cause the outer transaction to rollback.
    """
    logger.info("CoreOrg: Seeding fiscal and HR defaults for company_id=%s", company_id)

    company = db.scalar(select(Company).where(Company.id == company_id))
    if not company:
        # Previously this was only a warning, which hid the fact that
        # the company had been rolled back earlier in the transaction.
        logger.error(
            "CoreOrg: seed_company_fiscal_and_hr_defaults called for unknown company_id=%s",
            company_id,
        )
        raise ValueError(f"Company id={company_id} not found while seeding fiscal/HR defaults")

    fy = _seed_fiscal_year(db, company_id)
    hl = _seed_holiday_list(db, company_id, fy)
    _seed_shift_types(db, company_id, hl)

    logger.info("CoreOrg: Finished seeding fiscal/HR defaults for company_id=%s", company_id)


# ---------------------------------------------------------------------------
# Cost Center per branch
# ---------------------------------------------------------------------------
def seed_cost_center_for_branch(db: Session, company_id: int, branch_id: int) -> None:
    """
    Create one Cost Center per (company, branch) if it doesn't exist:

        name: '<Branch Name> Cost Center'
    """
    existing = db.scalar(
        select(CostCenter).where(
            CostCenter.company_id == company_id,
            CostCenter.branch_id == branch_id,
        )
    )
    if existing:
        logger.info(
            "CoreOrg: CostCenter already exists for company_id=%s, branch_id=%s; skipping.",
            company_id,
            branch_id,
        )
        return

    branch = db.scalar(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.company_id == company_id,
        )
    )
    if not branch:
        logger.warning(
            "CoreOrg: seed_cost_center_for_branch called with unknown branch_id=%s company_id=%s",
            branch_id,
            company_id,
        )
        return

    name = DEFAULT_COST_CENTER_NAME_TEMPLATE.format(branch_name=branch.name)
    cc = CostCenter(
        company_id=company_id,
        branch_id=branch.id,
        name=name,
        enabled=True,
    )
    db.add(cc)
    db.flush([cc])

    logger.info(
        "CoreOrg: CostCenter seeded for company_id=%s, branch_id=%s name=%s",
        company_id,
        branch.id,
        name,
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def seed_core_org_masters(db: Session, company_id: int) -> None:
    """
    Seed minimal core master data for a company, ERP-style:

    - UOMs (Nos, Box, Pieces, Kg)
    - Brand: "No Brand"
    - Item Group tree (All Item Groups / Products / Raw Material / Services / Fixed Asset)
      with default accounting accounts tied to your COA.
    - Price Lists: Standard Selling / Standard Buying
    - Cash Customer & Cash Supplier (CUST-0001 / SUP-0001, cash parties)
    - Warehouses:
        * Company root "All Warehouses"
        * If branches exist: branch group + Main Store + Goods in Transit

    NOTE: This function DOES NOT commit.
          Caller is responsible for commit/rollback.
    """
    logger.info("CoreOrg: Seeding core masters for company_id=%s", company_id)

    _seed_uoms(db, company_id)
    _seed_brands(db, company_id)
    _seed_item_groups(db, company_id)
    _seed_price_lists(db, company_id)
    _seed_cash_parties(db, company_id)
    _seed_warehouses(db, company_id)

    logger.info("CoreOrg: Finished seeding core masters for company_id=%s", company_id)
