from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, validator

from app.common.models.base import StatusEnum


class CostCenterCreate(BaseModel):
    name: str = Field(..., description="Cost center name (e.g., 'Marketing', 'R&D', 'Production')")
    branch_id: Optional[int] = Field(None, description="Branch ID (optional, will use user's branch if not provided)")
    status: StatusEnum = StatusEnum.ACTIVE

    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Cost center name is required")
        if len(v.strip()) < 2:
            raise ValueError("Cost center name must be at least 2 characters")
        return v.strip()


class CostCenterUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[DocStatusEnum] = None

    @validator('name')
    def validate_name(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("Cost center name is required")
            if len(v.strip()) < 2:
                raise ValueError("Cost center name must be at least 2 characters")
        return v.strip() if v else None


class CostCenterOut(BaseModel):
    id: int
    company_id: int
    branch_id: int
    name: str
    status: str

    class Config:
        from_attributes = True