from __future__ import annotations
from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
import logging

from app.application_accounting.chart_of_accounts.models import CostCenter
from app.application_stock.stock_models import DocStatusEnum
from config.database import db

log = logging.getLogger(__name__)


class CostCenterRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_cost_center_by_id(self, cost_center_id: int) -> Optional[CostCenter]:
        return self.s.get(CostCenter, cost_center_id)

    def get_cost_center_by_name(self, company_id: int, branch_id: int, name: str) -> Optional[CostCenter]:
        return self.s.scalar(
            select(CostCenter).where(
                CostCenter.company_id == company_id,
                CostCenter.branch_id == branch_id,
                CostCenter.name == name
            )
        )

    def get_cost_centers_by_company_branch(self, company_id: int, branch_id: int) -> List[CostCenter]:
        return list(self.s.scalars(
            select(CostCenter).where(
                CostCenter.company_id == company_id,
                CostCenter.branch_id == branch_id
            ).order_by(CostCenter.name)
        ))

    def get_active_cost_centers(self, company_id: int, branch_id: int) -> List[CostCenter]:
        return list(self.s.scalars(
            select(CostCenter).where(
                CostCenter.company_id == company_id,
                CostCenter.branch_id == branch_id,
                CostCenter.status == DocStatusEnum.ACTIVE
            ).order_by(CostCenter.name)
        ))

    def create_cost_center(self, cost_center: CostCenter) -> CostCenter:
        self.s.add(cost_center)
        self.s.flush()
        return cost_center

    def update_cost_center(self, cost_center: CostCenter, updates: dict) -> None:
        for key, value in updates.items():
            setattr(cost_center, key, value)
        self.s.flush([cost_center])

    def flush_model(self, model):
        self.s.flush([model])