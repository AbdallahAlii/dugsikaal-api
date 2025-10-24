# app/inventory/services.py

from __future__ import annotations
import logging
import secrets
from typing import Optional, List, Dict
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Unauthorized, Forbidden, NotFound

from app.application_accounting.chart_of_accounts.assets_model import AssetCategory
from app.application_nventory.inventory_models import Brand, UnitOfMeasure, Item, UOMConversion, \
    ItemTypeEnum, ItemGroup
from app.application_nventory.repo.inventory_repo import InventoryRepository
from app.application_nventory.schemas.inventory_schemas import BrandCreate, BrandOut, UOMCreate, ItemCreate, UOMOut, ItemMinimalOut, \
    UOMConversionCreate, UOMConversionOut, BranchItemPricingCreate, BranchItemPricingOut, BranchItemPricingUpdate, \
    ItemUpdate
from app.common.cache.cache_invalidator import bump_list_cache_company, bump_list_cache_branch, bump_inventory_dropdowns
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.common.cache.cache_invalidator import (
    bump_list_cache_company,
    bump_list_cache_branch,
    bump_dropdown_company  # ADD THIS IMPORT
)
log = logging.getLogger(__name__)


# REFACTORED: Define custom exceptions for cleaner error handling
class InventoryLogicError(BadRequest):
    """Base exception for inventory-related business logic errors."""
    pass


class DuplicateRecordError(InventoryLogicError):
    """Raised when a unique constraint is violated."""
    pass


# Define roles that can create master data
MASTER_DATA_CREATOR_ROLES = {"Super Admin", "Operations Manager", "Purchase Manager"}


class InventoryService:
    def __init__(self, repo: Optional[InventoryRepository] = None, session: Optional[Session] = None):
        self.repo = repo or InventoryRepository(session or db.session)
        self.s = self.repo.s

    def _ensure_brand_belongs_to_company(self, brand_id: int, company_id: int):
        """Helper to ensure a brand exists and belongs to the specified company."""
        brand = self.repo.get_brand_by_id(brand_id)
        # REVISED: Simpler, more direct error message.
        if not brand or brand.company_id != company_id:
            raise NotFound("Invalid brand selected.")

    def _ensure_uom_belongs_to_company(self, uom_id: int, company_id: int):
        """Helper to ensure a UOM exists and belongs to the specified company."""
        uom = self.repo.get_uom_by_id(uom_id)
        # REVISED: Simpler, more direct error message.
        if not uom or uom.company_id != company_id:
            raise NotFound("Invalid unit of measure selected.")
    # --- Brand Service ---
    def create_brand(self, payload: BrandCreate, context: AffiliationContext) -> BrandOut:
        # Rule 1: Permission check
        if not MASTER_DATA_CREATOR_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to create a brand.")

        # Rule 2: Scope check - The user can only create a brand within their company context
        ensure_scope_by_ids(context=context, target_company_id=context.company_id)

        if self.repo.get_brand_by_name(context.company_id, payload.name):
            raise DuplicateRecordError("Brand with this name already exists.")

        try:
            brand = Brand(company_id=context.company_id, name=payload.name)
            self.repo.create_brand(brand)
            self.s.commit()
            # ✅ INVALIDATE BOTH LIST AND DROPDOWN CACHES
            bump_list_cache_company("inventory", "items", context.company_id)
            bump_inventory_dropdowns("inventory", "items", context.company_id)

            return BrandOut.model_validate(brand)
        except IntegrityError:
            self.s.rollback()
            raise DuplicateRecordError("Brand with this name already exists.")

    # --- UnitOfMeasure Service ---
    def create_uom(self, payload: UOMCreate, context: AffiliationContext) -> UOMOut:
        # Rule 1: Permission check
        if not MASTER_DATA_CREATOR_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to create a unit of measure.")

        # Rule 2: Scope check
        ensure_scope_by_ids(context=context, target_company_id=context.company_id)

        if self.repo.get_uom_by_name(context.company_id, payload.name):
            raise DuplicateRecordError("Unit of measure with this name already exists.")

        try:
            uom = UnitOfMeasure(company_id=context.company_id, name=payload.name, symbol=payload.symbol)
            self.repo.create_uom(uom)
            self.s.commit()
            # ✅ INVALIDATE BOTH LIST AND DROPDOWN CACHES
            bump_list_cache_company("inventory", "items", context.company_id)
            bump_inventory_dropdowns("inventory", "items", context.company_id)

            return UOMOut.model_validate(uom)
        except IntegrityError:
            self.s.rollback()
            raise DuplicateRecordError("Unit of measure with this name already exists.")

    @staticmethod
    def _sku_type_prefix(item_type: ItemTypeEnum) -> str:
        mapping: Dict[ItemTypeEnum, str] = {
            ItemTypeEnum.STOCK_ITEM: "ST",
            ItemTypeEnum.SERVICE: "SE",
        }
        return mapping.get(item_type, "IT")

    @staticmethod
    def _initials(name: str, max_letters: int = 4) -> str:
        words = [w for w in re.split(r"\s+", name.strip()) if w]
        letters = "".join(w[0] for w in words[:max_letters])
        if not letters:
            letters = re.sub(r"[^A-Za-z0-9]+", "", name)[:max_letters]
        letters = letters.upper() or "UNK"
        return letters

    @staticmethod
    def _random_tail(n_bytes: int = 3) -> str:
        return secrets.token_hex(n_bytes).upper()

    @staticmethod
    def _sanitize_sku(s: str, max_len: int = 32) -> str:
        s = s.upper()
        s = re.sub(r"[^A-Z0-9\-]+", "-", s)
        s = re.sub(r"-{2,}", "-", s).strip("-")
        return s[:max_len] or "SKU"

    def _generate_sku(self, item_name: str, item_type: ItemTypeEnum) -> str:
        t = self._sku_type_prefix(item_type)
        ini = self._initials(item_name)
        tail = self._random_tail(3)
        sku = self._sanitize_sku(f"{t}-{ini}-{tail}")

        # ADDED: Log the SKU generation details
        log.info(
            "Generated SKU: name='%s', type=%s, prefix=%s, initials=%s, tail=%s, final_sku=%s",
            item_name, item_type, t, ini, tail, sku
        )
        return self._sanitize_sku(f"{t}-{ini}-{tail}")

    def _normalize_manual_sku(self, raw: str) -> str:
        normalized = self._sanitize_sku(raw, max_len=32)
        log.info("Normalized manual SKU: raw='%s', normalized='%s'", raw, normalized)
        return normalized
    def _ensure_item_group_belongs_to_company(self, item_group_id: int, company_id: int):
        row = self.s.execute(
            select(ItemGroup.id, ItemGroup.company_id).where(ItemGroup.id == item_group_id)
        ).first()
        if not row or int(row.company_id) != int(company_id):
            raise NotFound("Invalid item group selected.")

    def _ensure_asset_category_belongs_to_company(self, asset_category_id: int, company_id: int):
        row = self.s.execute(
            select(AssetCategory.id, AssetCategory.company_id).where(AssetCategory.id == asset_category_id)
        ).first()
        if not row or int(row.company_id) != int(company_id):
            raise NotFound("Invalid asset category selected.")

    # --- Item Service ---
    def create_item(self, payload: ItemCreate, context: AffiliationContext) -> ItemMinimalOut:
        log.info(
            "Starting item creation: name='%s', type=%s, company_id=%d, manual_sku='%s'",
            payload.name, payload.item_type, context.company_id, payload.sku
        )

        # Permission
        if not MASTER_DATA_CREATOR_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to create an item.")

        # Company scope
        ensure_scope_by_ids(context=context, target_company_id=context.company_id)

        # Mandatory: item_group_id
        if not getattr(payload, "item_group_id", None):
            raise InventoryLogicError("Item group is required.")

        # Name duplicate (per company)
        if self.repo.get_item_by_name(context.company_id, payload.name):
            raise DuplicateRecordError("Item with this name already exists.")

        # Cross-company FK validation
        self._ensure_item_group_belongs_to_company(payload.item_group_id, context.company_id)

        if payload.brand_id:
            self._ensure_brand_belongs_to_company(payload.brand_id, context.company_id)

        if payload.base_uom_id:
            self._ensure_uom_belongs_to_company(payload.base_uom_id, context.company_id)

        # Fixed-asset rules:
        #  - if explicitly marked fixed asset, category is required
        #  - if category provided but is_fixed_asset not provided, auto-enable is_fixed_asset
        is_fixed_asset = bool(getattr(payload, "is_fixed_asset", False))
        asset_category_id = getattr(payload, "asset_category_id", None)

        if is_fixed_asset and not asset_category_id:
            raise InventoryLogicError("Fixed Asset items require an asset_category_id.")

        if asset_category_id:
            self._ensure_asset_category_belongs_to_company(asset_category_id, context.company_id)
            # convenience: if caller forgot to set is_fixed_asset, switch it on
            if not is_fixed_asset:
                is_fixed_asset = True

        # Decide final SKU
        manual_sku = (payload.sku or "").strip()
        data = payload.model_dump(exclude={"sku"}, exclude_unset=True)

        # overwrite the possibly missing/derived flags safely
        data["is_fixed_asset"] = is_fixed_asset
        if asset_category_id is not None:
            data["asset_category_id"] = asset_category_id

        if manual_sku:
            final_sku = self._normalize_manual_sku(manual_sku)
            if self.repo.get_item_by_sku(context.company_id, final_sku):
                raise DuplicateRecordError("Item with this SKU already exists.")

            item = Item(company_id=context.company_id, sku=final_sku, **data)
            try:
                self.repo.create_item(item)
                self.s.commit()
                bump_list_cache_company("inventory", "items", context.company_id)
                bump_inventory_dropdowns("inventory", "items", context.company_id)
                return ItemMinimalOut.model_validate(item)
            except IntegrityError:
                self.s.rollback()
                raise DuplicateRecordError("Item with this SKU already exists.")
        else:
            # Auto-generate + retry for uniqueness
            attempts = 10
            log.info("Starting auto-SKU generation: attempts=%d, name='%s'", attempts, payload.name)
            for i in range(attempts):
                gen_sku = self._generate_sku(payload.name, payload.item_type)
                log.info("Attempt %d/%d: generated SKU='%s'", i + 1, attempts, gen_sku)
                item = Item(company_id=context.company_id, sku=gen_sku, **data)
                try:
                    self.repo.create_item(item)
                    self.s.commit()
                    bump_list_cache_company("inventory", "items", context.company_id)
                    bump_inventory_dropdowns("inventory", "items", context.company_id)
                    return ItemMinimalOut.model_validate(item)
                except IntegrityError:
                    self.s.rollback()
                    if i == attempts - 1:
                        raise DuplicateRecordError("Could not allocate a unique SKU. Please retry.")

    def update_item(self, item_id: int, payload: ItemUpdate, context: AffiliationContext) -> ItemMinimalOut:
        # Permission
        if not MASTER_DATA_CREATOR_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to update an item.")

        item = self.repo.get_item_by_id(item_id)
        if not item:
            raise NotFound("Item not found.")

        # Scope
        ensure_scope_by_ids(context=context, target_company_id=item.company_id)

        incoming: Dict = payload.model_dump(exclude_unset=True)
        conv_changes = incoming.pop("uom_conversions", None)

        # Basic FK sanity
        if "brand_id" in incoming and incoming["brand_id"] is not None:
            self._ensure_brand_belongs_to_company(incoming["brand_id"], item.company_id)
        if "base_uom_id" in incoming and incoming["base_uom_id"] is not None:
            self._ensure_uom_belongs_to_company(incoming["base_uom_id"], item.company_id)
        if "item_group_id" in incoming and incoming["item_group_id"] is not None:
            self._ensure_item_group_belongs_to_company(incoming["item_group_id"], item.company_id)

        # Unique name check
        if "name" in incoming and incoming["name"]:
            exists = self.repo.get_item_by_name_excluding_id(item.company_id, incoming["name"], item.id)
            if exists:
                raise DuplicateRecordError("Another item with this name already exists.")

        # Apply item field updates
        if incoming:
            self.repo.update_item(item, incoming)

        # Handle UOM conversions with inferred intent
        if conv_changes is not None:
            for c in conv_changes:
                uom_id = c["uom_id"]
                factor = c.get("conversion_factor")
                is_active = c.get("is_active")

                # validate same-company UOM
                self._ensure_uom_belongs_to_company(uom_id, item.company_id)

                # CASE 1: UPSERT when factor provided (>0)
                if factor is not None:
                    try:
                        f = float(factor)
                    except Exception:
                        raise InventoryLogicError("Conversion factor must be a number.")
                    if f <= 0:
                        raise InventoryLogicError("Conversion factor must be > 0.")
                    self.repo.upsert_uom_conversion(
                        item_id=item.id,
                        uom_id=uom_id,
                        factor=f,
                        is_active=True if is_active is None else bool(is_active),
                    )
                    continue

                # CASE 2: Toggle is_active (must exist)
                if is_active is not None:
                    conv = self.repo.get_uom_conversion(item.id, uom_id)
                    if not conv:
                        raise NotFound("UOM conversion not found.")
                    conv.is_active = bool(is_active)
                    self.repo.flush_model(conv)
                    continue

                # CASE 3: Neither factor nor is_active → DELETE
                deleted = self.repo.delete_uom_conversion(item.id, uom_id)
                if deleted == 0:
                    raise NotFound("UOM conversion not found.")

        # Commit
        try:
            self.s.commit()
        except IntegrityError:
            self.s.rollback()
            raise DuplicateRecordError("Update would result in a duplicate record.")

        # Cache bumps
        bump_list_cache_company("inventory", "items", context.company_id)
        bump_dropdown_company("inventory", "items", context.company_id)
        bump_dropdown_company("inventory", "active_items", context.company_id)
        if conv_changes is not None:
            bump_list_cache_company("inventory", "uom_conversions", context.company_id)

        return ItemMinimalOut.model_validate(item)
    # --- UOM Conversion Service ---
    def create_uom_conversion(self, payload: UOMConversionCreate, context: AffiliationContext) -> UOMConversionOut:
        # No change in permission check, it's not a master data role.

        # Rule 1: Validate item existence and user's scope.
        item = self.repo.get_item_by_id(payload.item_id)
        if not item:
            raise NotFound("Item not found.")
        ensure_scope_by_ids(context=context, target_company_id=item.company_id)

        # Rule 2: Automatic to_uom_id assignment.
        # We no longer rely on the user to provide to_uom_id.
        if not item.base_uom_id:
            raise InventoryLogicError("Cannot create a UOM conversion for an item without a base UOM.")
        final_to_uom_id = item.base_uom_id

        # Rule 3: Validate existence of from_uom and the determined to_uom.
        from_uom = self.repo.get_uom_by_id(payload.from_uom_id)
        to_uom = self.repo.get_uom_by_id(final_to_uom_id)
        if not from_uom or not to_uom:
            raise NotFound("One or both units of measure not found.")

        # Rule 4: Prevent duplicate conversions
        if self.repo.get_uom_conversion_by_ids(payload.item_id, payload.from_uom_id, final_to_uom_id):
            raise DuplicateRecordError("A conversion for this item and units already exists.")

        try:
            # We now pass the automatically determined to_uom_id to the model.
            conversion = UOMConversion(
                company_id=item.company_id,
                item_id=payload.item_id,
                from_uom_id=payload.from_uom_id,
                to_uom_id=final_to_uom_id,
                conversion_factor=payload.conversion_factor
            )
            self.repo.create_uom_conversion(conversion)
            self.s.commit()
            bump_list_cache_company("inventory", "uom_conversions", conversion.company_id)
            return UOMConversionOut.model_validate(conversion)
        except IntegrityError:
            self.s.rollback()
            raise DuplicateRecordError("A conversion for this item and units already exists.")

    # --- Branch Item Pricing Service ---
