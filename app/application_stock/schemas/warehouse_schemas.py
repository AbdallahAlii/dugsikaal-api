from __future__ import annotations
from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from app.common.models.base import StatusEnum

# ---------- Create / Update payloads ----------

class WarehouseCreate(BaseModel):
    """
    Create:
      - Company Root:  is_group=True, parent_warehouse_id=None, branch_id=None
      - Branch Group:  is_group=True, parent_warehouse_id=<company_root_id>, branch_id=...
      - Leaf:          is_group=False, parent_warehouse_id=<branch_group_id>, branch_id=...
    """
    company_id: Optional[int] = None
    branch_id:  Optional[int] = None
    parent_warehouse_id: Optional[int] = None

    name: str = Field(..., max_length=150)
    code: Optional[str] = Field(None, max_length=100, description="Manual code; auto-generated if omitted.")
    description: Optional[str] = None
    is_group: bool = True

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Name is required.")
        return v.strip()


class WarehouseUpdate(BaseModel):
    """
    Update metadata and/or reparent.
    - is_group / code / company_id / branch_id are immutable here to keep flows simple.
    """
    name: Optional[str] = Field(None, max_length=150)
    description: Optional[str] = None
    parent_warehouse_id: Optional[int] = None
    status: Optional[StatusEnum] = None


# ---------- API outputs ----------

class WarehouseOut(BaseModel):
    id: int
    code: str
    company_id: int
    branch_id: Optional[int]
    parent_warehouse_id: Optional[int]
    is_group: bool
    name: str
    description: Optional[str]
    status: StatusEnum

    class Config:
        from_attributes = True
class IdCode(BaseModel):
    id: int
    code: str