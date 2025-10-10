# app/inventory/services.py

from __future__ import annotations
import logging
import secrets
from typing import Optional, List, Dict
import re
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Unauthorized, Forbidden, NotFound

from app.application_nventory.inventory_models import Brand, UnitOfMeasure, Item, UOMConversion, \
    ItemTypeEnum
from app.application_nventory.repo import InventoryRepository
from app.application_nventory.schemas import BrandCreate, BrandOut, UOMCreate, ItemCreate, UOMOut, ItemMinimalOut, \
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

        # Name duplicate (per company)
        if self.repo.get_item_by_name(context.company_id, payload.name):
            raise DuplicateRecordError("Item with this name already exists.")

        # Validate cross-company FKs early
        if payload.brand_id:
            self._ensure_brand_belongs_to_company(payload.brand_id, context.company_id)
        if payload.base_uom_id:
            self._ensure_uom_belongs_to_company(payload.base_uom_id, context.company_id)

        # Decide final SKU
        manual_sku = (payload.sku or "").strip()
        if manual_sku:
            final_sku = self._normalize_manual_sku(manual_sku)
            if self.repo.get_item_by_sku(context.company_id, final_sku):
                raise DuplicateRecordError("Item with this SKU already exists.")
            data = payload.model_dump(exclude={"sku"})
            item = Item(company_id=context.company_id, sku=final_sku, **data)
            try:
                self.repo.create_item(item)
                self.s.commit()

                # ✅ USE THE HELPER FUNCTION
                bump_list_cache_company("inventory", "items", context.company_id)
                bump_inventory_dropdowns("inventory", "items", context.company_id)

                return ItemMinimalOut.model_validate(item)
            except IntegrityError:
                self.s.rollback()
                raise DuplicateRecordError("Item with this SKU already exists.")
        else:
            # Auto-generate + retry to be safe under concurrency
            attempts = 10
            data = payload.model_dump(exclude={"sku"})
            log.info("Starting auto-SKU generation: attempts=%d, name='%s'", attempts, payload.name)

            for i in range(attempts):
                gen_sku = self._generate_sku(payload.name, payload.item_type)
                log.info("Attempt %d/%d: generated SKU='%s'", i + 1, attempts, gen_sku)
                item = Item(company_id=context.company_id, sku=gen_sku, **data)
                try:
                    self.repo.create_item(item)
                    self.s.commit()

                    # ✅ INVALIDATE BOTH LIST AND DROPDOWN CACHES
                    # ✅ USE THE HELPER FUNCTION
                    bump_list_cache_company("inventory", "items", context.company_id)
                    bump_inventory_dropdowns("inventory", "items", context.company_id)

                    return ItemMinimalOut.model_validate(item)
                except IntegrityError:
                    self.s.rollback()
                    if i == attempts - 1:
                        raise DuplicateRecordError("Could not allocate a unique SKU. Please retry.")

    def update_item(self, item_id: int, payload: ItemUpdate, context: AffiliationContext) -> ItemMinimalOut:
        # Rule 1: Permission check
        if not MASTER_DATA_CREATOR_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to update an item.")

        item = self.repo.get_item_by_id(item_id)
        if not item:
            raise NotFound("Item not found.")

        # Rule 2: Scope check - The user must belong to the same company as the item.
        ensure_scope_by_ids(context=context, target_company_id=item.company_id)

        try:
            updates = payload.model_dump(exclude_unset=True)
            if updates.get('brand_id'):
                self._ensure_brand_belongs_to_company(updates['brand_id'], item.company_id)
            if updates.get('base_uom_id'):
                self._ensure_uom_belongs_to_company(updates['base_uom_id'], item.company_id)

            self.repo.update_item(item, updates)
            self.s.commit()

            # ✅ INVALIDATE BOTH LIST AND DROPDOWN CACHES
            bump_list_cache_company("inventory", "items", context.company_id)
            bump_dropdown_company("inventory", "items", context.company_id)  # ADD THIS LINE
            bump_dropdown_company("inventory", "active_items", context.company_id)  # ADD THIS LINE

            return ItemMinimalOut.model_validate(item)
        except IntegrityError:
            self.s.rollback()
            raise DuplicateRecordError("Update would result in a duplicate record.")

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
