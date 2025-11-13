# app/application_items/import_handlers.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional, Iterable, Set
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, BadRequest

from app.application_nventory.inventory_services import InventoryService
from config.database import db
from app.security.rbac_effective import AffiliationContext



# domain models
from app.application_nventory.inventory_models import Item, ItemGroup, UnitOfMeasure, Brand  # keep your module spelling
from app.application_accounting.chart_of_accounts.assets_model import AssetCategory

from app.application_data_import.config.base_config import RowProcessor

from app.application_nventory.inventory_models import Item, ItemGroup, UnitOfMeasure, Brand
from app.application_accounting.chart_of_accounts.assets_model import AssetCategory

try:
    from app.application_nventory.schemas.inventory_schemas import ItemCreate, ItemUpdate  # noqa
    HAS_SCHEMAS = True
except Exception:
    HAS_SCHEMAS = False

class ItemImportHandler(RowProcessor):
    def __init__(self, *, company_id: int, branch_id: Optional[int], context: AffiliationContext):
        self.company_id = company_id
        self.branch_id = branch_id
        self.context = context
        self.s: Session = db.session
        self.svc = InventoryService(session=self.s)

        self._item_group_by_name: Dict[str, int] = {}
        self._uom_by_name: Dict[str, int] = {}
        self._brand_by_name: Dict[str, int] = {}
        self._asset_cat_by_name: Dict[str, int] = {}
        self._item_by_sku: Dict[str, int] = {}
        self._item_by_name: Dict[str, int] = {}

    def prefetch(self, rows: List[Dict[str, Any]]) -> None:
        def _collect(key: str) -> Set[str]:
            return {str(r.get(key)).strip() for r in rows if r.get(key) not in (None, "")}

        grp_names = _collect("item_group")
        uom_names = _collect("base_uom")
        brand_names = _collect("brand")
        asset_names = _collect("asset_category")
        sku_keys = _collect("update_by_sku") | {str(r.get("sku")).strip() for r in rows if r.get("sku")}
        item_names = _collect("update_by_name") | _collect("name")

        if grp_names:
            stmt = select(ItemGroup.id, ItemGroup.name, ItemGroup.code).where(
                ItemGroup.company_id == self.company_id,
                (ItemGroup.name.in_(grp_names) | ItemGroup.code.in_(grp_names))
            )
            for rid, name, code in self.s.execute(stmt).all():
                self._item_group_by_name[name] = rid
                self._item_group_by_name[code] = rid

        if uom_names:
            stmt = select(UnitOfMeasure.id, UnitOfMeasure.name).where(
                UnitOfMeasure.company_id == self.company_id,
                UnitOfMeasure.name.in_(uom_names)
            )
            for rid, name in self.s.execute(stmt).all():
                self._uom_by_name[name] = rid

        if brand_names:
            stmt = select(Brand.id, Brand.name).where(
                Brand.company_id == self.company_id,
                Brand.name.in_(brand_names)
            )
            for rid, name in self.s.execute(stmt).all():
                self._brand_by_name[name] = rid

        if asset_names:
            stmt = select(AssetCategory.id, AssetCategory.name).where(
                AssetCategory.company_id == self.company_id,
                AssetCategory.name.in_(asset_names)
            )
            for rid, name in self.s.execute(stmt).all():
                self._asset_cat_by_name[name] = rid

        if sku_keys:
            stmt = select(Item.id, Item.sku).where(
                Item.company_id == self.company_id,
                Item.sku.in_({s for s in sku_keys if s})
            )
            for rid, sku in self.s.execute(stmt).all():
                self._item_by_sku[sku] = rid

        if item_names:
            stmt = select(Item.id, Item.name).where(
                Item.company_id == self.company_id,
                Item.name.in_(item_names)
            )
            for rid, nm in self.s.execute(stmt).all():
                self._item_by_name[nm] = rid

    def _resolve_required(self, row: Dict[str, Any], key: str, mapping: Dict[str, int], human: str) -> int:
        raw = (row.get(key) or "").strip()
        if not raw:
            raise BadRequest(f"{human} is required.")
        rid = mapping.get(raw)
        if not rid:
            raise NotFound(f"{human} not found: {raw}")
        return int(rid)

    def _resolve_optional(self, row: Dict[str, Any], key: str, mapping: Dict[str, int]) -> Optional[int]:
        raw = row.get(key)
        if raw is None or str(raw).strip() == "":
            return None
        rid = mapping.get(str(raw).strip())
        if not rid:
            raise NotFound(f"{key} not found: {raw}")
        return int(rid)

    def _normalize_item_type(self, v: Optional[str]) -> str:
        if not v: return "Stock"
        s = str(v).strip().capitalize()
        if s not in {"Stock", "Service"}:
            raise BadRequest("item_type must be 'Stock' or 'Service'.")
        return s

    def insert(self, row: Dict[str, Any]) -> Tuple[bool, List[str]]:
        try:
            payload = {
                "name": row.get("name"),
                "description": row.get("description") or None,
                "item_group_id": self._resolve_required(row, "item_group", self._item_group_by_name, "Item Group"),
                "brand_id": self._resolve_optional(row, "brand", self._brand_by_name),
                "base_uom_id": self._resolve_optional(row, "base_uom", self._uom_by_name),
                "item_type": self._normalize_item_type(row.get("item_type")),
                "is_fixed_asset": bool(row.get("is_fixed_asset") or False),
                "asset_category_id": self._resolve_optional(row, "asset_category", self._asset_cat_by_name),
            }
            manual_sku = (row.get("sku") or "").strip() or None
            payload_out = payload.copy()
            if manual_sku:
                payload_out["sku"] = manual_sku

            if HAS_SCHEMAS:
                from app.application_nventory.schemas.inventory_schemas import ItemCreate
                model = ItemCreate(**payload_out)
                self.svc.create_item(model, self.context)
            else:
                class _Obj:
                    def __init__(self, d): self._d = d
                    def model_dump(self, **_): return self._d
                    def __getattr__(self, k): return self._d.get(k)
                self.svc.create_item(_Obj(payload_out), self.context)

            return True, ["Inserted"]
        except Exception as e:
            return False, [str(e)]

    def update(self, row: Dict[str, Any]) -> Tuple[bool, List[str]]:
        try:
            target_id: Optional[int] = None
            by_sku = (row.get("update_by_sku") or "").strip()
            by_name = (row.get("update_by_name") or "").strip()
            if by_sku:
                target_id = self._item_by_sku.get(by_sku)
            if not target_id and by_name:
                target_id = self._item_by_name.get(by_name)
            if not target_id:
                return False, ["Target not found (provide Update By SKU or Update By Name)."]

            patch: Dict[str, Any] = {}
            if row.get("name") not in (None, ""): patch["name"] = row["name"]
            if row.get("description") not in (None, ""): patch["description"] = row["description"]
            if row.get("item_group") not in (None, ""):
                patch["item_group_id"] = self._resolve_required(row, "item_group", self._item_group_by_name, "Item Group")
            if row.get("brand") not in (None, ""):
                patch["brand_id"] = self._resolve_optional(row, "brand", self._brand_by_name)
            if row.get("base_uom") not in (None, ""):
                patch["base_uom_id"] = self._resolve_optional(row, "base_uom", self._uom_by_name)
            if row.get("item_type") not in (None, ""):
                patch["item_type"] = self._normalize_item_type(row.get("item_type"))
            if row.get("is_fixed_asset") not in (None, ""):
                patch["is_fixed_asset"] = bool(row.get("is_fixed_asset"))
            if row.get("asset_category") not in (None, ""):
                patch["asset_category_id"] = self._resolve_optional(row, "asset_category", self._asset_cat_by_name)

            if HAS_SCHEMAS:
                from app.application_nventory.schemas.inventory_schemas import ItemUpdate
                model = ItemUpdate(**patch)
                self.svc.update_item(target_id, model, self.context)
            else:
                class _Obj:
                    def __init__(self, d): self._d = d
                    def model_dump(self, **_): return self._d
                    def __getattr__(self, k): return self._d.get(k)
                self.svc.update_item(target_id, _Obj(patch), self.context)

            return True, ["Updated"]
        except Exception as e:
            return False, [str(e)]

def build_item_handler(company_id: int, branch_id: Optional[int], context: AffiliationContext) -> ItemImportHandler:
    return ItemImportHandler(company_id=company_id, branch_id=branch_id, context=context)
