from __future__ import annotations

from typing import Optional, Iterable
from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session

from config.database import db
from app.application_nventory.inventory_models import ItemGroup

ROOT_ITEM_GROUP_NAME = "All Item Groups"
ROOT_ITEM_GROUP_CODE = "ALL-ITEMS"


class ItemGroupRepository:
    """Simple, working repository without complex batch queries."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def save(self, obj: ItemGroup) -> ItemGroup:
        """Save item group."""
        if obj not in self.s:
            self.s.add(obj)
        self.s.flush([obj])
        return obj

    # -----------------------
    # Basic getters
    # -----------------------
    def get_item_group_by_id(self, *, company_id: int, item_group_id: int) -> Optional[ItemGroup]:
        """Get item group by ID."""
        return self.s.scalar(
            select(ItemGroup).where(
                ItemGroup.company_id == int(company_id),
                ItemGroup.id == int(item_group_id),
            )
        )

    def item_group_code_exists(self, *, company_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        """Check if item group code exists."""
        cd = (code or "").strip()
        if not cd:
            return False

        q = exists().where(
            ItemGroup.company_id == int(company_id),
            func.lower(ItemGroup.code) == func.lower(cd),
        )
        if exclude_id:
            q = q.where(ItemGroup.id != int(exclude_id))

        return bool(self.s.scalar(select(q)))

    def item_group_name_exists(self, *, company_id: int, name: str, exclude_id: Optional[int] = None) -> bool:
        """Check if item group name already exists in company."""
        q = exists().where(
            ItemGroup.company_id == int(company_id),
            func.lower(ItemGroup.name) == func.lower(name.strip()),
        )
        if exclude_id:
            q = q.where(ItemGroup.id != int(exclude_id))

        return bool(self.s.scalar(select(q)))

    def get_root_item_group_id(self, *, company_id: int) -> Optional[int]:
        """Get root item group ID."""
        return self.s.scalar(
            select(ItemGroup.id).where(
                ItemGroup.company_id == int(company_id),
                ItemGroup.code == ROOT_ITEM_GROUP_CODE,
            ).limit(1)
        )

    def create_root_item_group(self, *, company_id: int) -> ItemGroup:
        """Create root item group."""
        root = ItemGroup(
            company_id=int(company_id),
            parent_item_group_id=None,
            name=ROOT_ITEM_GROUP_NAME,
            code=ROOT_ITEM_GROUP_CODE,
            is_group=True,
        )
        self.save(root)
        return root

    def parent_is_group(self, *, company_id: int, parent_id: int) -> Optional[bool]:
        """Check if parent is a group."""
        return self.s.scalar(
            select(ItemGroup.is_group).where(
                ItemGroup.company_id == int(company_id),
                ItemGroup.id == int(parent_id),
            )
        )

    def child_group_exists(self, *, company_id: int, parent_id: int) -> bool:
        """Check if item group has child groups."""
        q = exists().where(
            ItemGroup.company_id == int(company_id),
            ItemGroup.parent_item_group_id == int(parent_id),
        )
        return bool(self.s.scalar(select(q)))

    # -----------------------
    # Cycle check
    # -----------------------
    def would_create_cycle(self, *, company_id: int, group_id: int, new_parent_id: int) -> bool:
        """Check if setting parent would create a cycle."""
        company_id = int(company_id)
        group_id = int(group_id)
        new_parent_id = int(new_parent_id)

        # Early exit for self-reference
        if group_id == new_parent_id:
            return True

        # Check if new_parent is already a descendant
        hierarchy = (
            select(ItemGroup.id, ItemGroup.parent_item_group_id)
            .where(ItemGroup.company_id == company_id, ItemGroup.id == new_parent_id)
            .cte(name="anc", recursive=True)
        )

        parent = select(ItemGroup.id, ItemGroup.parent_item_group_id).where(
            ItemGroup.company_id == company_id,
            ItemGroup.id == hierarchy.c.parent_item_group_id,
        )

        anc = hierarchy.union_all(parent)

        q = exists().where(anc.c.id == group_id)
        return bool(self.s.scalar(select(q)))

    # -----------------------
    # Account validation - FIXED IMPORT
    # -----------------------

    def missing_account_ids(self, *, company_id: int, account_ids: Iterable[int]) -> set[int]:
        """Check which account IDs don't exist or are disabled in the user's company."""
        ids = {int(x) for x in account_ids if x is not None}
        if not ids:
            return set()

        # CORRECTED import statement
        try:
            # Ensure this path matches your project structure
            from app.application_accounting.chart_of_accounts.models import Account

            rows = self.s.execute(
                select(Account.id).where(
                    Account.company_id == int(company_id),
                    Account.enabled.is_(True),
                    Account.id.in_(ids),
                )
            ).scalars().all()

            found = {int(x) for x in rows}
            return ids - found

        except ImportError as e:
            # Consider making this an error (raise) instead of a warning in production
            import logging
            logging.getLogger(__name__).error(
                "CRITICAL: Failed to import Account model. Account validation is broken. Error: %s", e
            )
            # For safety, treat missing models as validation failure
            # Return all IDs as "missing" to prevent invalid data
            return ids