from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

class PriceListCreate(BaseModel):
    # accept both "price_list_name" and "name"
    model_config = {"populate_by_name": True}
    name: str = Field(..., alias="price_list_name")
    list_type: str = Field(..., description="Buying | Selling | Both")
    price_not_uom_dependent: bool = Field(default=True)
    is_active: bool = Field(default=True)

    @field_validator("list_type")
    @classmethod
    def _lt(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in {"buying", "selling", "both"}:
            raise ValueError("Price List must be applicable for Buying or Selling.")
        return s.capitalize()

class PriceListUpdate(BaseModel):
    model_config = {"populate_by_name": True}
    price_list_name: Optional[str] = None
    list_type: Optional[str] = None
    price_not_uom_dependent: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("list_type")
    @classmethod
    def _lt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip().lower()
        if s not in {"buying", "selling", "both"}:
            raise ValueError("Price List must be applicable for Buying or Selling.")
        return s.capitalize()

class ItemPriceCreate(BaseModel):
    # code is intentionally NOT accepted; always auto-generated server-side
    item_id: int | str
    price_list_id: int | str
    rate: float
    uom_id: Optional[int | str] = None
    branch_id: Optional[int | str] = None
    valid_from: Optional[datetime] = None
    valid_upto: Optional[datetime] = None

class ItemPriceUpdate(BaseModel):
    # only rate and validity are updatable
    rate: Optional[float] = None
    valid_from: Optional[datetime] = None
    valid_upto: Optional[datetime] = None
