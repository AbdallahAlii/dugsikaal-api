# app/application_buying/receipt_repo.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set


# Project-specific imports (adjust paths as needed)
from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem
from app.application_nventory.inventory_models import Item, ItemTypeEnum, UnitOfMeasure, UOMConversion
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch

from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session, selectinload, aliased

from config.database import db
from app.common.models.base import StatusEnum


class PurchaseReceiptRepository:
    """Data Access Layer for Purchase Receipt documents."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Document Read Operations ---

    def get_by_id(self, pr_id: int, for_update: bool = False) -> Optional[PurchaseReceipt]:
        """
        Fetches a Purchase Receipt by its ID, with its items.
        Applies a pessimistic lock if `for_update` is True.
        """
        stmt = (
            select(PurchaseReceipt)
            .options(selectinload(PurchaseReceipt.items))
            .where(PurchaseReceipt.id == pr_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        """Checks if a document code already exists within a branch, case-insensitively."""
        stmt = select(exists().where(
            PurchaseReceipt.company_id == company_id,
            PurchaseReceipt.branch_id == branch_id,
            func.lower(PurchaseReceipt.code) == func.lower(code)
        ))
        if exclude_id:
            stmt = stmt.where(PurchaseReceipt.id != exclude_id)
        return self.s.execute(stmt).scalar()

    # --- Document Write Operations ---

    def save(self, pr: PurchaseReceipt) -> PurchaseReceipt:
        """Adds a new PR to the session or flushes changes for an existing one."""
        if pr not in self.s:
            self.s.add(pr)
        self.s.flush()
        return pr

    def sync_lines(self, pr: PurchaseReceipt, lines_data: List[Dict]) -> None:
        """Atomically synchronizes the item lines of a Purchase Receipt."""
        existing_lines_map = {line.id: line for line in pr.items}
        lines_to_keep_ids: Set[int] = set()

        for line_data in lines_data:
            line_id = line_data.get("id")
            if line_id and line_id in existing_lines_map:
                line = existing_lines_map[line_id]
                for key, value in line_data.items():
                    if hasattr(line, key):
                        setattr(line, key, value)
                lines_to_keep_ids.add(line_id)
            else:
                new_line = PurchaseReceiptItem(receipt_id=pr.id, **line_data)
                self.s.add(new_line)

        lines_to_delete_ids = set(existing_lines_map.keys()) - lines_to_keep_ids
        for line_id in lines_to_delete_ids:
            self.s.delete(existing_lines_map[line_id])

    # --- Master Data Validation Queries ---

    def get_valid_supplier_ids(self, company_id: int, supplier_ids: List[int]) -> Set[int]:
        """Returns the subset of supplier IDs that are valid and active."""
        if not supplier_ids: return set()
        stmt = select(Party.id).where(
            Party.id.in_(supplier_ids),
            Party.company_id == company_id,
            Party.role == PartyRoleEnum.SUPPLIER,
            Party.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        """
        Returns the subset of warehouse IDs that are valid, active, and not group warehouses (leaf nodes).
        """
        if not warehouse_ids:
            return set()

        # Alias a second copy for the child rows so we can correlate on parent -> child
        W_child = aliased(Warehouse)

        # TRUE if a child exists for the outer Warehouse row
        child_exists = exists(
            select(1).where(W_child.parent_warehouse_id == Warehouse.id)
        )

        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~child_exists,  # not a parent → i.e., leaf/transactional
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        """Fetches key details for a batch of items for validation."""
        if not item_ids: return {}
        stmt = select(Item.id, Item.status, Item.item_type, Item.base_uom_id).where(
            Item.id.in_(item_ids),
            Item.company_id == company_id
        )
        rows = self.s.execute(stmt).all()
        return {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id
            }
            for r in rows
        }

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        """Returns the subset of UOM IDs that exist and are active."""
        if not uom_ids: return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        """
        Return the company_id for a given branch, or None if not found.
        Used by resolve_company_branch_and_scope() to canonicalize scope.
        """
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()
    def get_compatible_uom_pairs(self, company_id: int, pairs: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        """Checks a batch of (item_id, uom_id) pairs for compatibility."""
        if not pairs: return set()
        item_ids = {p[0] for p in pairs}

        item_stmt = select(Item.id, Item.base_uom_id).where(Item.id.in_(item_ids))
        base_uom_map = dict(self.s.execute(item_stmt).all())

        conv_stmt = select(UOMConversion.item_id, UOMConversion.from_uom_id, UOMConversion.to_uom_id).where(
            UOMConversion.item_id.in_(item_ids)
        )
        conversions = {(c.item_id, c.from_uom_id, c.to_uom_id) for c in self.s.execute(conv_stmt).all()}

        compatible_pairs: Set[Tuple[int, int]] = set()
        for item_id, uom_id in pairs:
            base_uom_id = base_uom_map.get(item_id)
            if not base_uom_id: continue

            if uom_id == base_uom_id or \
               (item_id, base_uom_id, uom_id) in conversions or \
               (item_id, uom_id, base_uom_id) in conversions:
                compatible_pairs.add((item_id, uom_id))

        return compatible_pairs

