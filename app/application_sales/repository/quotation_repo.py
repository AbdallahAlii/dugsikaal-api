# app/application_sales/repository/quotation_repo.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set
from sqlalchemy import select, func, exists
from sqlalchemy.orm import Session, selectinload

from app.application_sales.models import SalesQuotation, SalesQuotationItem
from app.application_stock.stock_models import DocStatusEnum
from config.database import db

class SalesQuotationRepository:
    """Data Access Layer for Sales Quotation documents."""
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_by_id(self, sq_id: int, for_update: bool = False) -> Optional[SalesQuotation]:
        stmt = (
            select(SalesQuotation)
            .options(selectinload(SalesQuotation.items))
            .where(SalesQuotation.id == sq_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            SalesQuotation.company_id == company_id,
            SalesQuotation.branch_id == branch_id,
            func.lower(SalesQuotation.code) == func.lower(code)
        ))
        if exclude_id:
            stmt = stmt.where(SalesQuotation.id != exclude_id)
        return self.s.execute(stmt).scalar()

    def save(self, sq: SalesQuotation) -> SalesQuotation:
        if sq not in self.s:
            self.s.add(sq)
        self.s.flush()
        return sq

    def sync_lines(self, sq: SalesQuotation, lines_data: List[Dict]) -> None:
        existing_lines_map = {line.id: line for line in sq.items}
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
                new_line = SalesQuotationItem(quotation_id=sq.id, **line_data)
                self.s.add(new_line)
        lines_to_delete_ids = set(existing_lines_map.keys()) - lines_to_keep_ids
        for line_id in lines_to_delete_ids:
            self.s.delete(existing_lines_map[line_id])