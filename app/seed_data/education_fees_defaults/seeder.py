# # app/seed_data/education_fees_defaults/seeder.py

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.application_education.programs.models.program_models import Program

from .data import (
    FEE_ITEM_GROUP_PARENT,
    FEE_ITEM_GROUPS,
    FEE_SERVICE_ITEMS,
    SELLING_PRICE_LISTS,
    GRADE_TIER_PRICE_LIST,
    TUITION_PRICES,
    FEE_CATEGORIES,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Safe imports
# -------------------------------------------------------------------
def _import_account_model():
    from app.application_accounting.chart_of_accounts.models import Account
    return Account


def _import_inventory_models():
    # keep your module name as-is
    from app.application_nventory.inventory_models import (
        ItemGroup,
        Item,
        PriceList,
        ItemPrice,
        PriceListType,
        ItemTypeEnum,
    )
    return ItemGroup, Item, PriceList, ItemPrice, PriceListType, ItemTypeEnum


def _import_education_fee_models():
    # NOTE: your file name in messages varies (fees_model vs models)
    # keep the one that works in your project.
    from app.application_education.fees.fees_model import (
        FeeCategory,
        FeeStructure,
        FeeStructureComponent,
    )
    return FeeCategory, FeeStructure, FeeStructureComponent


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _get_or_create(db: Session, model, *, defaults: Optional[dict] = None, **filters):
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj, False

    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    try:
        db.flush([obj])
        return obj, True
    except IntegrityError:
        logger.exception("IntegrityError creating %s %s", model.__name__, filters)
        raise


def _get_account_id_by_code(db: Session, company_id: int, code: Optional[str]) -> Optional[int]:
    if not code:
        return None
    Account = _import_account_model()
    acc = db.scalar(select(Account).where(Account.company_id == company_id, Account.code == code))
    return int(acc.id) if acc else None


def _get_item_group_by_code(db: Session, company_id: int, code: str):
    ItemGroup, *_ = _import_inventory_models()
    return db.scalar(select(ItemGroup).where(ItemGroup.company_id == company_id, ItemGroup.code == code))


def _get_item_by_sku(db: Session, company_id: int, sku: str):
    _, Item, *_ = _import_inventory_models()
    return db.scalar(select(Item).where(Item.company_id == company_id, Item.sku == sku))


def _get_price_list_by_name(db: Session, company_id: int, name: str):
    _, _, PriceList, *_ = _import_inventory_models()
    return db.scalar(select(PriceList).where(PriceList.company_id == company_id, PriceList.name == name))


def _safe_price_list_id(db: Session, company_id: int, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    pl = _get_price_list_by_name(db, company_id, name)
    return int(pl.id) if pl else None


def _make_item_price_code(*, company_id: int, item_id: int, price_list_id: int) -> str:
    # Deterministic & short; works well with unique(code) or unique(company_id, code)
    return f"IP-{company_id}-{item_id}-{price_list_id}"


# -------------------------------------------------------------------
# Seed steps
# -------------------------------------------------------------------
def _ensure_fee_item_groups(db: Session, company_id: int) -> None:
    ItemGroup, *_ = _import_inventory_models()

    root = _get_item_group_by_code(db, company_id, "ALL-ITEMS")
    if not root:
        root, _ = _get_or_create(
            db,
            ItemGroup,
            company_id=company_id,
            code="ALL-ITEMS",
            defaults=dict(name="All Item Groups", is_group=True),
        )

    parent = _get_item_group_by_code(db, company_id, FEE_ITEM_GROUP_PARENT["code"])
    if not parent:
        parent = ItemGroup(
            company_id=company_id,
            code=FEE_ITEM_GROUP_PARENT["code"],
            name=FEE_ITEM_GROUP_PARENT["name"],
            is_group=True,
            parent_item_group_id=int(root.id),
        )
        db.add(parent)
        db.flush([parent])

    for row in FEE_ITEM_GROUPS:
        ig = _get_item_group_by_code(db, company_id, row["code"])
        if ig:
            continue

        ig = ItemGroup(
            company_id=company_id,
            code=row["code"],
            name=row["name"],
            is_group=bool(row["is_group"]),
            parent_item_group_id=int(parent.id),
            default_income_account_id=_get_account_id_by_code(db, company_id, row.get("default_income_code")),
            default_expense_account_id=_get_account_id_by_code(db, company_id, row.get("default_expense_code")),
            default_inventory_account_id=_get_account_id_by_code(db, company_id, row.get("default_inventory_code")),
        )
        db.add(ig)
        db.flush([ig])


def _ensure_fee_service_items(db: Session, company_id: int) -> None:
    _, Item, _, _, _, ItemTypeEnum = _import_inventory_models()

    for row in FEE_SERVICE_ITEMS:
        if _get_item_by_sku(db, company_id, row["sku"]):
            continue

        ig = _get_item_group_by_code(db, company_id, row["item_group_code"])
        if not ig:
            raise RuntimeError(f"Fee ItemGroup missing code={row['item_group_code']} company_id={company_id}")

        item = Item(
            company_id=company_id,
            item_group_id=int(ig.id),
            name=row["name"],
            sku=row["sku"],
            item_type=ItemTypeEnum.SERVICE,
            is_fixed_asset=False,
        )
        db.add(item)
        db.flush([item])


def _ensure_selling_price_lists(db: Session, company_id: int) -> None:
    _, _, PriceList, _, PriceListType, _ = _import_inventory_models()

    for row in SELLING_PRICE_LISTS:
        if _get_price_list_by_name(db, company_id, row["name"]):
            continue

        pl = PriceList(
            company_id=company_id,
            name=row["name"],
            list_type=PriceListType.SELLING,
            is_active=True,
            is_default=bool(row.get("is_default", False)),
            price_not_uom_dependent=True,
        )
        db.add(pl)
        db.flush([pl])


def _ensure_tuition_item_prices(db: Session, company_id: int) -> None:
    _, Item, _, ItemPrice, _, _ = _import_inventory_models()

    tuition = _get_item_by_sku(db, company_id, "TUITION")
    if not tuition:
        raise RuntimeError("TUITION item missing (sku=TUITION). Fee prices cannot be seeded.")

    for pl_name, rate in TUITION_PRICES.items():
        pl_id = _safe_price_list_id(db, company_id, pl_name)
        if not pl_id:
            # price list not created (data mismatch) -> skip safely
            continue

        # Strong idempotency: match the exact “base row” we seed (no branch/uom/validity)
        exists = db.scalar(
            select(ItemPrice).where(
                ItemPrice.company_id == company_id,
                ItemPrice.item_id == tuition.id,
                ItemPrice.price_list_id == pl_id,
                ItemPrice.branch_id.is_(None),
                ItemPrice.uom_id.is_(None),
                ItemPrice.valid_from.is_(None),
                ItemPrice.valid_upto.is_(None),
            )
        )
        if exists:
            # Also backfill code if an old bad row existed (defensive)
            if getattr(exists, "code", None) in (None, ""):
                exists.code = _make_item_price_code(
                    company_id=company_id,
                    item_id=int(tuition.id),
                    price_list_id=int(pl_id),
                )
                db.flush([exists])
            continue

        ip = ItemPrice(
            code=_make_item_price_code(company_id=company_id, item_id=int(tuition.id), price_list_id=int(pl_id)),
            company_id=company_id,
            item_id=int(tuition.id),
            price_list_id=int(pl_id),
            branch_id=None,
            uom_id=None,
            rate=rate,
            valid_from=None,
            valid_upto=None,
        )
        db.add(ip)
        db.flush([ip])


def _ensure_fee_categories(db: Session, company_id: int) -> None:
    FeeCategory, _, _ = _import_education_fee_models()

    for row in FEE_CATEGORIES:
        item = _get_item_by_sku(db, company_id, row["item_sku"])
        if not item:
            raise RuntimeError(f"Item for FeeCategory missing sku={row['item_sku']} company_id={company_id}")

        fc = db.scalar(select(FeeCategory).where(FeeCategory.company_id == company_id, FeeCategory.name == row["name"]))
        if fc:
            if getattr(fc, "item_id", None) is None:
                fc.item_id = int(item.id)
                db.flush([fc])
            continue

        fc = FeeCategory(
            company_id=company_id,
            name=row["name"],
            is_enabled=True,
            item_id=int(item.id),
        )
        db.add(fc)
        db.flush([fc])


def _ensure_fee_structures(
    db: Session,
    *,
    company_id: int,
    program_ids: Optional[List[int]] = None,
) -> None:
    FeeCategory, FeeStructure, FeeStructureComponent = _import_education_fee_models()

    tuition = db.scalar(select(FeeCategory).where(FeeCategory.company_id == company_id, FeeCategory.name == "Tuition"))
    if not tuition:
        raise RuntimeError("FeeCategory 'Tuition' missing; cannot seed fee structures.")

    if program_ids:
        programs = db.execute(
            select(Program.id, Program.name).where(
                Program.company_id == company_id,
                Program.id.in_(program_ids),
            )
        ).all()
    else:
        programs = db.execute(select(Program.id, Program.name).where(Program.company_id == company_id)).all()

    name_by_id = {int(pid): str(name) for pid, name in programs}

    for grade in range(1, 13):
        pname = f"Grade {grade}"
        pid = next((pid for pid, name in name_by_id.items() if name == pname), None)
        if not pid:
            continue

        pl_name = GRADE_TIER_PRICE_LIST.get(grade)
        pl_id = _safe_price_list_id(db, company_id, pl_name)

        fs = db.scalar(
            select(FeeStructure).where(
                FeeStructure.company_id == company_id,
                FeeStructure.program_id == pid,
                FeeStructure.version_no == 1,
            )
        )
        if not fs:
            fs = FeeStructure(
                company_id=company_id,
                name=f"{pname} Fee Structure",
                program_id=int(pid),
                version_no=1,
                is_enabled=True,
                selling_price_list_id=pl_id,
                remarks="Seeded default structure (Tuition). You can add other categories later.",
            )
            db.add(fs)
            db.flush([fs])
        else:
            if getattr(fs, "selling_price_list_id", None) is None and pl_id is not None:
                fs.selling_price_list_id = int(pl_id)
                db.flush([fs])

        if not pl_name or pl_name not in TUITION_PRICES:
            continue

        amount = Decimal(TUITION_PRICES[pl_name])

        comp = db.scalar(
            select(FeeStructureComponent).where(
                FeeStructureComponent.fee_structure_id == fs.id,
                FeeStructureComponent.fee_category_id == tuition.id,
            )
        )
        if comp:
            continue

        comp = FeeStructureComponent(
            company_id=company_id,
            fee_structure_id=int(fs.id),
            fee_category_id=int(tuition.id),
            item_id=tuition.item_id,
            amount=amount,
            is_optional=False,
            sequence_no=1,
            description="Tuition",
        )
        db.add(comp)
        db.flush([comp])


# -------------------------------------------------------------------
# PUBLIC ENTRYPOINT
# -------------------------------------------------------------------
def seed_education_fees_billing_defaults(
    db: Session,
    *,
    company_id: int,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Idempotent. No commit. Safe to call during create_company.

    context (optional) can include:
      - program_ids: list[int]
      - academic_year_id: int (not needed here yet)
    """
    logger.info("EduFeesBillingDefaults: start company_id=%s", company_id)

    program_ids: Optional[List[int]] = None
    if isinstance(context, dict):
        v = context.get("program_ids")
        if isinstance(v, list) and all(isinstance(x, int) for x in v):
            program_ids = v

    program_count = db.scalar(select(func.count()).select_from(Program).where(Program.company_id == company_id))
    if int(program_count or 0) == 0:
        raise RuntimeError("Programs must exist before seeding fees (education_defaults must run first).")

    _ensure_fee_item_groups(db, company_id)
    _ensure_fee_service_items(db, company_id)
    _ensure_selling_price_lists(db, company_id)
    _ensure_tuition_item_prices(db, company_id)   # ✅ now inserts ItemPrice.code
    _ensure_fee_categories(db, company_id)
    _ensure_fee_structures(db, company_id=company_id, program_ids=program_ids)

    logger.info("EduFeesBillingDefaults: done company_id=%s", company_id)
