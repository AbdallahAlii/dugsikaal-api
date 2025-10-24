from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, validator, model_validator

from app.application_nventory.inventory_models import PriceListType
from app.common.date_utils import parse_date_flex


# ───────────────────────── Price List ─────────────────────────

class PriceListCreate(BaseModel):
    name: str = Field(..., description="e.g. Standard Selling")
    list_type: PriceListType = Field(..., description="Buying / Selling / Both")
    is_active: bool = True


class PriceListUpdate(BaseModel):
    name: Optional[str] = None
    list_type: Optional[PriceListType] = None
    is_active: Optional[bool] = None


class PriceListOut(BaseModel):
    id: int
    company_id: int
    name: str
    list_type: PriceListType
    is_active: bool

    class Config:
        from_attributes = True


# ───────────────────────── Item Price ─────────────────────────

class ItemPriceCreate(BaseModel):
    price_list_id: int
    item_id: int
    rate: float

    # Optional
    code: Optional[str] = None
    uom_id: Optional[int] = None
    branch_id: Optional[int] = None
    valid_from: Optional[str] = None
    valid_upto: Optional[str] = None

    @validator("rate")
    def _rate_positive(cls, v: float):
        if v is None or float(v) <= 0:
            raise ValueError("Rate must be greater than 0")
        return float(v)

    @validator("valid_from", "valid_upto")
    def _parse_date(cls, v):
        if v in (None, "", "null"):
            return None
        d = parse_date_flex(str(v))
        if not d:
            raise ValueError("Invalid date")
        return d

    @model_validator(mode="after")
    def _check_date_order(self):
        vf: Optional[date] = self.valid_from
        vu: Optional[date] = self.valid_upto
        if vf and vu and vu < vf:
            raise ValueError("Valid Upto must be on or after Valid From")
        return self


class ItemPriceUpdate(BaseModel):
    rate: Optional[float] = Field(None, gt=0)
    uom_id: Optional[int] = None
    branch_id: Optional[int] = None
    valid_from: Optional[str] = None
    valid_upto: Optional[str] = None

    @validator("valid_from", "valid_upto")
    def _parse_date(cls, v):
        if v in (None, "", "null"):
            return None
        d = parse_date_flex(str(v))
        if not d:
            raise ValueError("Invalid date")
        return d


class ItemPriceOut(BaseModel):
    id: int
    company_id: int
    price_list_id: int
    item_id: int
    code: str
    uom_id: Optional[int]
    branch_id: Optional[int]
    rate: float
    valid_from: Optional[datetime]
    valid_upto: Optional[datetime]

    class Config:
        from_attributes = True
