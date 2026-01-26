from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Any, Union

from pydantic import BaseModel, Field, field_validator

from app.common.date_utils import parse_date_flex


def _parse_dt_or_date(v: Any) -> Optional[Union[datetime, date]]:
    if v is None or v == "":
        return None
    if isinstance(v, (datetime, date)):
        return v

    s = str(v).strip()
    if not s:
        return None

    # ISO datetime (supports Z)
    try:
        ss = s[:-1] + "+00:00" if s.endswith("Z") else s
        return datetime.fromisoformat(ss)
    except Exception:
        pass

    # Fallback: flexible date parser (date only)
    d = parse_date_flex(s)
    if d is not None:
        return d

    # Let pydantic raise if invalid
    return v


class PriceListCreate(BaseModel):
    company_id: Optional[int] = None
    name: Optional[str] = Field(default=None, alias="price_list_name")
    list_type: Optional[str] = None
    price_not_uom_dependent: bool = True
    is_active: bool = True
    is_default: bool = False

    model_config = {"populate_by_name": True}


class PriceListUpdate(BaseModel):
    company_id: Optional[int] = None
    name: Optional[str] = Field(default=None, alias="price_list_name")
    list_type: Optional[str] = None
    price_not_uom_dependent: Optional[bool] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None

    model_config = {"populate_by_name": True}


class ItemPriceCreate(BaseModel):
    company_id: Optional[int] = None
    item_id: Optional[int] = None
    price_list_id: Optional[int] = None
    rate: Optional[float] = None
    uom_id: Optional[int] = None
    branch_id: Optional[int] = None
    valid_from: Optional[Union[datetime, date]] = None
    valid_upto: Optional[Union[datetime, date]] = None

    @field_validator("valid_from", mode="before")
    @classmethod
    def _vf(cls, v: Any):
        return _parse_dt_or_date(v)

    @field_validator("valid_upto", mode="before")
    @classmethod
    def _vu(cls, v: Any):
        return _parse_dt_or_date(v)


class ItemPriceUpdate(BaseModel):
    rate: Optional[float] = None
    valid_from: Optional[Union[datetime, date]] = None
    valid_upto: Optional[Union[datetime, date]] = None

    @field_validator("valid_from", mode="before")
    @classmethod
    def _vf(cls, v: Any):
        return _parse_dt_or_date(v)

    @field_validator("valid_upto", mode="before")
    @classmethod
    def _vu(cls, v: Any):
        return _parse_dt_or_date(v)
