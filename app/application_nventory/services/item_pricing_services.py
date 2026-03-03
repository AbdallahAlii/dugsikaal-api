# app/application_nventory/services/pricing_admin_service.py
from __future__ import annotations

import logging
import re
from uuid import uuid4
from typing import Optional, Dict, Any, List
from datetime import datetime as dt_datetime, time as dt_time

from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from config.database import db
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_guards import ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext

from app.common.cache.invalidation import (
    bump_company_list,
    bump_dropdown_for_context,
    bump_detail,
)

from app.application_org.models.company import Branch
from app.application_nventory.inventory_models import Item, UnitOfMeasure, PriceList, ItemPrice
from app.application_nventory.repo.pricing_repo import PricingRepository
from app.application_nventory.schemas.pricing_schemas import (
    PriceListCreate,
    PriceListUpdate,
    PriceListOut,
    ItemPriceCreate,
    ItemPriceUpdate,
    ItemPriceOut,
)
from app.application_nventory.validators.pricing_validators import (
    PriceListValidator,
    ItemPriceValidator,
)

log = logging.getLogger(__name__)


def _sanitize_code(raw: str) -> str:
    """
    Keep it UI-friendly: uppercase, allow A-Z 0-9 - _ only, collapse spaces to '-'.
    Limit to 100 chars (model constraint).
    """
    s = (raw or "").strip().upper().replace(" ", "-")
    s = re.sub(r"[^A-Z0-9\-\_]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    return s[:100]


class PricingAdminService:
    def __init__(self, repo: Optional[PricingRepository] = None, session=None):
        self.repo = repo or PricingRepository(session or db.session)
        self.s = self.repo.s

    # ---------------- Price List ----------------
    def create_price_list(self, payload: PriceListCreate, context: AffiliationContext) -> PriceListOut:
        company_id = int(context.company_id or 0)
        if not company_id:
            raise BizValidationError("Company context is required.")

        ensure_scope_by_ids(context=context, target_company_id=company_id)

        PriceListValidator.validate_name_and_type(
            payload.name,
            payload.list_type.value if payload.list_type else None,
        )

        if self.repo.get_price_list_by_name(company_id, payload.name):
            # Short ERP toast
            raise BizValidationError(f"Price List {payload.name} already exists")

        try:
            pl = PriceList(
                company_id=company_id,
                name=payload.name.strip(),
                list_type=payload.list_type,
                is_active=bool(payload.is_active),
            )
            self.repo.create_price_list(pl)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("inventory", "price_lists", context, company_id)
                bump_detail("inventory:price_lists", int(pl.id))
                bump_dropdown_for_context("inventory", "price_lists", context, params={"company_id": company_id})
            except Exception:
                log.exception("[cache] failed to bump price_list caches after create")

            return PriceListOut.model_validate(pl)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError(f"Price List {payload.name} already exists")
        except Exception as e:
            self.s.rollback()
            log.exception("Create Price List failed: %s", str(e))
            raise BizValidationError("Failed to create Price List")

    def update_price_list(self, price_list_id: int, payload: PriceListUpdate, context: AffiliationContext) -> PriceListOut:
        pl = self.repo.get_price_list_by_id(price_list_id)
        if not pl:
            raise NotFound("Price List not found")

        ensure_scope_by_ids(context=context, target_company_id=int(pl.company_id))

        updates: dict = {}

        if payload.name is not None:
            name = payload.name.strip()
            if name and name != pl.name:
                if self.repo.get_price_list_by_name(pl.company_id, name):
                    raise BizValidationError(f"Price List {name} already exists")
                updates["name"] = name

        if payload.list_type is not None:
            updates["list_type"] = payload.list_type

        if payload.is_active is not None:
            updates["is_active"] = bool(payload.is_active)

        if not updates:
            raise BizValidationError("No changes provided")

        try:
            self.repo.update_price_list(pl, updates)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                company_id = int(pl.company_id)
                bump_company_list("inventory", "price_lists", context, company_id)
                bump_detail("inventory:price_lists", int(pl.id))
                bump_dropdown_for_context("inventory", "price_lists", context, params={"company_id": company_id})
            except Exception:
                log.exception("[cache] failed to bump price_list caches after update")

            return PriceListOut.model_validate(pl)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Duplicate Price List")
        except Exception as e:
            self.s.rollback()
            log.exception("Update Price List failed: %s", str(e))
            raise BizValidationError("Failed to update Price List")

    # ---------------- Item Price ----------------
    def _resolve_company_from_price_list(self, price_list_id: int) -> int:
        pl = self.repo.get_price_list_by_id(price_list_id)
        if not pl:
            raise NotFound("Price List not found")
        return int(pl.company_id)

    def _ensure_same_company(self, company_id: int, item_id: int, uom_id: Optional[int], branch_id: Optional[int]) -> None:
        it = self.s.get(Item, item_id)
        if not it or int(it.company_id) != int(company_id):
            raise NotFound("Item not found")

        if uom_id:
            uom = self.s.get(UnitOfMeasure, uom_id)
            if not uom or int(uom.company_id) != int(company_id):
                raise NotFound("UOM not found")

        if branch_id:
            br = self.s.get(Branch, branch_id)
            if not br or int(br.company_id) != int(company_id):
                raise NotFound("Branch not found")

    def _make_item_price_code(self, company_id: int) -> str:
        # Try short, readable codes first; fall back to full UUID if collisions
        for _ in range(6):
            code = uuid4().hex[:12].upper()
            if not self.repo.item_price_code_exists(company_id, code):
                return code
        # Fallback: practically unique
        code = uuid4().hex.upper()
        return code if not self.repo.item_price_code_exists(company_id, code) else f"{code}-{uuid4().hex[:6].upper()}"

    def create_item_price(self, payload: ItemPriceCreate, context: AffiliationContext) -> ItemPriceOut:
        ItemPriceValidator.validate_mandatory(payload.price_list_id, payload.item_id, payload.rate)
        ItemPriceValidator.validate_rate(payload.rate)

        company_id = self._resolve_company_from_price_list(payload.price_list_id)
        ensure_scope_by_ids(context=context, target_company_id=company_id)

        pl = self.repo.get_price_list_by_id(payload.price_list_id)
        if not pl:
            raise NotFound("Price List not found")
        if not pl.is_active:
            raise BizValidationError("Price List is disabled")

        self._ensure_same_company(company_id, payload.item_id, payload.uom_id, payload.branch_id)

        # Dates
        vf_dt = dt_datetime.combine(payload.valid_from, dt_time.min) if payload.valid_from else None
        vu_dt = dt_datetime.combine(payload.valid_upto, dt_time.min) if payload.valid_upto else None
        ItemPriceValidator.validate_validity(vf_dt, vu_dt)

        # Duplicate (PL + item + uom + branch)
        dup = self.repo.find_duplicate_item_price(
            price_list_id=payload.price_list_id,
            item_id=payload.item_id,
            uom_id=payload.uom_id,
            branch_id=payload.branch_id,
        )
        if dup:
            raise BizValidationError("Item Price already exists")

        # Code (optional, sanitize + ensure unique in this company)
        final_code = _sanitize_code(payload.code) if payload.code else None
        if final_code:
            if self.repo.item_price_code_exists(company_id, final_code):
                raise BizValidationError("Code already exists")
        else:
            final_code = self._make_item_price_code(company_id)

        try:
            ip = ItemPrice(
                company_id=company_id,
                code=final_code,
                price_list_id=payload.price_list_id,
                item_id=payload.item_id,
                uom_id=payload.uom_id,
                branch_id=payload.branch_id,
                rate=float(payload.rate),
                valid_from=vf_dt,
                valid_upto=vu_dt,
            )
            self.repo.create_item_price(ip)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("inventory", "item_prices", context, company_id)
                bump_detail("inventory:item_prices", int(ip.id))
                bump_dropdown_for_context("inventory", "item_prices", context, params={"company_id": company_id})
            except Exception:
                log.exception("[cache] failed to bump item_price caches after create")

            return ItemPriceOut.model_validate(ip)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Item Price already exists")
        except Exception as e:
            self.s.rollback()
            log.exception("Create Item Price failed: %s", str(e))
            raise BizValidationError("Failed to create Item Price")

    def update_item_price(self, item_price_id: int, payload: ItemPriceUpdate, context: AffiliationContext) -> ItemPriceOut:
        ip = self.repo.get_item_price_by_id(item_price_id)
        if not ip:
            raise NotFound("Item Price not found")

        pl = self.repo.get_price_list_by_id(ip.price_list_id)
        if not pl:
            raise NotFound("Price List not found")

        company_id = int(pl.company_id)
        ensure_scope_by_ids(context=context, target_company_id=company_id)

        updates: dict = {}

        if payload.rate is not None:
            ItemPriceValidator.validate_rate(payload.rate)
            updates["rate"] = float(payload.rate)

        new_uom_id = ip.uom_id if payload.uom_id is None else payload.uom_id
        new_branch_id = ip.branch_id if payload.branch_id is None else payload.branch_id

        if payload.uom_id is not None or payload.branch_id is not None:
            self._ensure_same_company(company_id, ip.item_id, new_uom_id, new_branch_id)
            dup = self.repo.find_duplicate_item_price(
                price_list_id=ip.price_list_id,
                item_id=ip.item_id,
                uom_id=new_uom_id,
                branch_id=new_branch_id,
                exclude_id=ip.id,
            )
            if dup:
                raise BizValidationError("Item Price already exists")
            updates["uom_id"] = new_uom_id
            updates["branch_id"] = new_branch_id

        if payload.valid_from is not None or payload.valid_upto is not None:
            vf_dt = dt_datetime.combine(payload.valid_from, dt_time.min) if payload.valid_from else ip.valid_from
            vu_dt = dt_datetime.combine(payload.valid_upto, dt_time.min) if payload.valid_upto else ip.valid_upto
            ItemPriceValidator.validate_validity(vf_dt, vu_dt)
            updates["valid_from"] = vf_dt
            updates["valid_upto"] = vu_dt

        if not updates:
            raise BizValidationError("No changes provided")

        try:
            self.repo.update_item_price(ip, updates)
            self.s.commit()

            # ---- Cache bumps (best effort) ----
            try:
                bump_company_list("inventory", "item_prices", context, company_id)
                bump_detail("inventory:item_prices", int(ip.id))
                bump_dropdown_for_context("inventory", "item_prices", context, params={"company_id": company_id})
            except Exception:
                log.exception("[cache] failed to bump item_price caches after update")

            return ItemPriceOut.model_validate(ip)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Item Price already exists")
        except Exception as e:
            self.s.rollback()
            log.exception("Update Item Price failed: %s", str(e))
            raise BizValidationError("Failed to update Item Price")

    def delete_price_lists_bulk(self, ids: List[int], context: AffiliationContext) -> Dict[str, Any]:
        deleted: List[int] = []
        blocked: List[Dict[str, Any]] = []
        touched_companies: set[int] = set()

        unique_ids = sorted(set(int(x) for x in (ids or [])))

        for pl_id in unique_ids:
            with self.s.begin_nested():
                try:
                    pl = self.repo.get_price_list_by_id(pl_id)
                    if not pl:
                        raise NotFound("Price List not found.")

                    ensure_scope_by_ids(context=context, target_company_id=int(pl.company_id))

                    link = self.repo.find_first_linked_document_price_list(int(pl.company_id), int(pl_id))
                    if link:
                        # ERP-ish message
                        code = str(link.get("code", "") or "").strip()
                        doctype = str(link.get("doctype", "Document") or "Document").strip()
                        if code:
                            raise BizValidationError(f"Cannot delete: linked with {doctype} {code}.")
                        raise BizValidationError(f"Cannot delete: linked with {doctype}.")

                    self.repo.delete_price_list(pl)
                    deleted.append(pl_id)
                    touched_companies.add(int(pl.company_id))

                except Exception as e:
                    blocked.append({"id": pl_id, "reason": str(e)})

        self.s.commit()

        # ---- Cache bumps (best effort) ----
        try:
            for cid in touched_companies:
                bump_company_list("inventory", "price_lists", context, int(cid))
                bump_dropdown_for_context("inventory", "price_lists", context, params={"company_id": int(cid)})
        except Exception:
            log.exception("[cache] failed to bump price_list caches after bulk  b ")

        return {"deleted": deleted, "blocked": blocked}