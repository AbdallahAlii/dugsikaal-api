# app/application_org/repository/branch_repo.py
from __future__ import annotations
from typing import Optional
from sqlalchemy import select

from app.application_org.models.company import Branch
from config.database import db


def get_branch_company_id(branch_id: int) -> Optional[int]:
    return db.session.execute(
        select(Branch.company_id).where(Branch.id == branch_id)
    ).scalar_one_or_none()
