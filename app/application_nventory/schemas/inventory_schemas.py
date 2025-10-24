
# app/application_nventory/inventory_schemas.py
from __future__ import annotations

from datetime import datetime
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
    class Config:
        extra = "forbid"

    name: str
    sku: Optional[str] = None
    item_type: ItemTypeEnum
    description: Optional[str] = None
    item_group_id: int
    brand_id: Optional[int] = None
    base_uom_id: Optional[int] = None
    is_fixed_asset: bool = False
    asset_category_id: Optional[int] = None
    status: StatusEnum = StatusEnum.ACTIVE

    @validator('base_uom_id')
    def validate_base_uom_for_stock_item(cls, v, values):
        if values.get('item_type') == ItemTypeEnum.STOCK_ITEM and not v:
            raise ValueError("Base UOM is required for a Stock Item.")
        return v

    @validator('asset_category_id', always=True)
    def validate_fixed_asset_requires_category(cls, v, values):
        if values.get('is_fixed_asset') and not v:
            raise ValueError("Please select an Asset Category.")
        return v





class ItemMinimalOut(BaseModel):
    id: int
    sku: str
    name: str
    item_type: ItemTypeEnum
    brand_id: Optional[int] = None
    base_uom_id: Optional[int] = None
    status: StatusEnum
    is_fixed_asset: bool
    asset_category_id: Optional[int] = None

    class Config:
        from_attributes = True


# --- Pricing Schemas ---
class PriceLookupRequest(BaseModel):
    item_id: int
    txn_uom_id: int
    qty: Optional[float] = Field(None, ge=0)
    posting_date: Optional[datetime] = None
    price_list_id: Optional[int] = None


class PriceLookupOut(BaseModel):
    item_id: int
    txn_uom_id: int
    rate: float
    stock_factor: float
    used_price_list_id: int
    used_branch_id: Optional[int] = None
    line_amount: Optional[float] = None
    stock_qty_change: Optional[float] = None


class PriceBatchItemIn(BaseModel):
    item_id: int
    txn_uom_id: int
    qty: Optional[float] = Field(None, ge=0)


class PriceBatchLookupRequest(BaseModel):
    items: List[PriceBatchItemIn] = Field(..., min_items=1)
    posting_date: Optional[datetime] = None
    price_list_id: Optional[int] = None


class PriceBatchLookupOut(BaseModel):
    results: List[PriceLookupOut]



class UOMConvChange(BaseModel):
    uom_id: int
    conversion_factor: Optional[float] = None     # no gt=0 here
    is_active: Optional[bool] = None

    @validator('conversion_factor')
    def conversion_factor_must_be_positive(cls, v):
        if v is not None and v <= 0:
            # short, ERP-style message
            raise ValueError("Conversion factor must be greater than 0.")
        return v

class ItemUpdate(BaseModel):
    # allowed fields (all optional)
    name: Optional[str] = None
    brand_id: Optional[int] = None
    status: Optional[StatusEnum] = None
    item_group_id: Optional[int] = None
    base_uom_id: Optional[int] = None

    # batch UOM conversion changes (upsert / toggle / delete)
    uom_conversions: Optional[List[UOMConvChange]] = None