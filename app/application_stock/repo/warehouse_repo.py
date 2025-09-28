from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select, func, exists, and_
from sqlalchemy.orm import Session, selectinload

from app.application_org.models.company import Branch
from config.database import db
from app.application_stock.stock_models import Warehouse
from app.common.models.base import StatusEnum

# Optional: if you want to check stock before delete
try:
    from app.application_stock.stock_models import Bin  # if defined
    HAS_BIN = True
except Exception:
    HAS_BIN = False


class Decimal:
    pass


class WarehouseRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # ---------- lookups ----------
    def get_by_id(self, wid: int, *, for_update: bool = False) -> Optional[Warehouse]:
        stmt = select(Warehouse).where(Warehouse.id == wid)
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def get_company_root(self, company_id: int) -> Optional[Warehouse]:
        stmt = select(Warehouse).where(
            Warehouse.company_id == company_id,
            Warehouse.branch_id.is_(None),
            Warehouse.parent_warehouse_id.is_(None),
            Warehouse.is_group.is_(True),
        )
        return self.s.execute(stmt).scalar_one_or_none()

    def company_root_exists(self, company_id: int) -> bool:
        stmt = select(exists().where(
            Warehouse.company_id == company_id,
            Warehouse.branch_id.is_(None),
            Warehouse.parent_warehouse_id.is_(None),
            Warehouse.is_group.is_(True),
        ))
        return bool(self.s.execute(stmt).scalar())

    def get_branch_group(self, company_id: int, branch_id: int) -> Optional[Warehouse]:
        stmt = select(Warehouse).where(
            Warehouse.company_id == company_id,
            Warehouse.branch_id == branch_id,
            Warehouse.is_group.is_(True),
        ).order_by(Warehouse.id.asc())
        # (There should be only one; DB uniqueness is enforced by (company, branch, name) anyway)
        return self.s.execute(stmt).scalar_one_or_none()

    def branch_group_exists(self, company_id: int, branch_id: int) -> bool:
        stmt = select(exists().where(
            Warehouse.company_id == company_id,
            Warehouse.branch_id == branch_id,
            Warehouse.is_group.is_(True),
        ))
        return bool(self.s.execute(stmt).scalar())

    def code_exists_global(self, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(func.lower(Warehouse.code) == func.lower(code)))
        if exclude_id:
            stmt = stmt.where(Warehouse.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    def name_exists_in_branch(self, company_id: int, branch_id: Optional[int], name: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            Warehouse.company_id == company_id,
            (Warehouse.branch_id.is_(None) if branch_id is None else Warehouse.branch_id == branch_id),
            func.lower(Warehouse.name) == func.lower(name),
        ))
        if exclude_id:
            stmt = stmt.where(Warehouse.id != exclude_id)
        return bool(self.s.execute(stmt).scalar())

    def has_children(self, wid: int) -> bool:
        stmt = select(exists().where(Warehouse.parent_warehouse_id == wid, Warehouse.status == StatusEnum.ACTIVE))
        return bool(self.s.execute(stmt).scalar())

    def parent_info(self, parent_id: int) -> Optional[tuple[int, Optional[int], bool]]:
        """Return (company_id, branch_id, is_group) for a parent warehouse."""
        stmt = select(Warehouse.company_id, Warehouse.branch_id, Warehouse.is_group).where(Warehouse.id == parent_id)
        row = self.s.execute(stmt).first()
        if not row:
            return None
        return (row[0], row[1], row[2])

    # Optional stock guard (if Bin exists)
    def sum_stock_qty(self, company_id: int, warehouse_id: int) -> Optional[Decimal]:
        if not HAS_BIN:
            return None
        from decimal import Decimal
        stmt = select(func.coalesce(func.sum(Bin.actual_qty), 0)).where(
            Bin.company_id == company_id, Bin.warehouse_id == warehouse_id
        )
        return Decimal(str(self.s.execute(stmt).scalar() or 0))

    # ---------- writes ----------
    def create(self, wh: Warehouse) -> Warehouse:
        self.s.add(wh)
        self.s.flush([wh])
        return wh

    def save(self, wh: Warehouse) -> Warehouse:
        self.s.flush([wh])
        return wh

    def delete(self, wh: Warehouse) -> None:
        self.s.delete(wh)
        self.s.flush([wh])
    def get_branch_company_id(self, branch_id: int) -> int | None:
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()