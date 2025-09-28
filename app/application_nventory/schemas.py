# app/inventory/schemas.py

from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, validator

from app.application_nventory.inventory_models import ItemTypeEnum
from app.common.models.base import StatusEnum


# --- General Schemas ---
class SuccessResponse(BaseModel):
    message: str = "Success."
    data: dict = Field(default_factory=dict)


class DeletedResponse(SuccessResponse):
    deleted_count: int


# --- Brand Schemas ---
class BrandCreate(BaseModel):
    name: str


class BrandOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# --- UnitOfMeasure Schemas ---
class UOMCreate(BaseModel):
    name: str
    symbol: str


class UOMOut(BaseModel):
    id: int
    name: str
    symbol: str

    class Config:
        from_attributes = True


# --- UOM Conversion Schemas ---
class UOMConversionCreate(BaseModel):
    item_id: int
    from_uom_id: int
    # to_uom_id: int
    conversion_factor: float = Field(..., gt=0)


class UOMConversionOut(BaseModel):
    id: int
    from_uom_id: int
    to_uom_id: int
    conversion_factor: float

    class Config:
        from_attributes = True


# --- Branch Item Pricing Schemas ---
class BranchItemPricingCreate(BaseModel):
    item_id: int
    branch_id: int
    standard_rate: float = Field(..., gt=0)
    cost: float = Field(..., ge=0)


class BranchItemPricingUpdate(BaseModel):
    standard_rate: Optional[float] = Field(None, gt=0)
    cost: Optional[float] = Field(None, ge=0)


class BranchItemPricingOut(BaseModel):
    id: int
    item_id: int
    branch_id: int
    standard_rate: float
    cost: float

    class Config:
        from_attributes = True


# --- Item Schemas ---
class ItemCreate(BaseModel):
    name: str
    sku: Optional[str] = None
    item_type: ItemTypeEnum
    description: Optional[str] = None
    brand_id: Optional[int] = None
    base_uom_id: Optional[int] = None
    status: StatusEnum = StatusEnum.ACTIVE

    @validator('base_uom_id')
    def validate_base_uom_for_stock_item(cls, v, values):
        if 'item_type' in values and values['item_type'] == ItemTypeEnum.STOCK_ITEM and not v:
            raise ValueError("base_uom_id is required for a Stock Item.")
        return v


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    brand_id: Optional[int] = None
    status: Optional[StatusEnum] = None
    base_uom_id: Optional[int] = None


class ItemMinimalOut(BaseModel):
    id: int
    sku: str
    name: str
    item_type: ItemTypeEnum
    brand_id: Optional[int] = None
    base_uom_id: Optional[int] = None
    status: StatusEnum

    class Config:
        from_attributes = True