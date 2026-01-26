from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

from app.common.models.base import StatusEnum


class WarehouseCreate(BaseModel):
    company_id: Optional[int] = None
    branch_id: Optional[int] = None
    parent_warehouse_id: Optional[int] = None

    name: str = Field(..., max_length=150)
    code: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    is_group: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Name is required.")
        return v.strip()

    @field_validator("code")
    @classmethod
    def _code_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        vv = v.strip()
        return vv or None


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    description: Optional[str] = None
    parent_warehouse_id: Optional[int] = None
    status: Optional[StatusEnum] = None

    @field_validator("name")
    @classmethod
    def _name_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        vv = v.strip()
        return vv or None

    @field_validator("parent_warehouse_id")
    @classmethod
    def _parent_id_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if v <= 0:
            raise ValueError("parent_warehouse_id must be a positive integer.")
        return v


class WarehouseBulkDelete(BaseModel):
    ids: List[int] = Field(..., min_length=1)


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
