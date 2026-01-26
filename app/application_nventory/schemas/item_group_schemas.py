from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ItemGroupCreate(BaseModel):
    """Create schema - only name required, everything else optional."""

    name: str = Field(..., min_length=1, max_length=200, alias="item_group_name")

    # Note: company_id is not needed from payload - it comes from user context
    parent_item_group_id: Optional[int] = Field(
        default=None,
        description="If not provided, defaults to root item group"
    )

    code: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Auto-generated if not provided"
    )

    is_group: bool = Field(
        default=True,
        description="Defaults to True (group) like ERPNext"
    )

    default_expense_account_id: Optional[int] = Field(
        default=None,
        description="Must belong to the user's company"
    )
    default_income_account_id: Optional[int] = Field(
        default=None,
        description="Must belong to the user's company"
    )
    default_inventory_account_id: Optional[int] = Field(
        default=None,
        description="Must belong to the user's company"
    )

    @field_validator('name')
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Item Group Name cannot be empty")
        return v

    model_config = {
        "populate_by_name": True,
        "extra": "forbid",
        "json_schema_extra": {
            "example": {
                "name": "Products",
                "parent_item_group_id": None,
                "code": "PROD",
                "is_group": True,
                "default_expense_account_id": 123,
                "default_income_account_id": 124,
                "default_inventory_account_id": 125
            }
        }
    }


class ItemGroupUpdate(BaseModel):
    """Update schema - all fields optional."""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        alias="item_group_name"
    )

    parent_item_group_id: Optional[int] = None
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    is_group: Optional[bool] = None

    default_expense_account_id: Optional[int] = None
    default_income_account_id: Optional[int] = None
    default_inventory_account_id: Optional[int] = None

    @field_validator('name')
    @classmethod
    def validate_name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Item Group Name cannot be empty")
        return v

    model_config = {
        "populate_by_name": True,
        "extra": "forbid"
    }


class ItemGroupOut(BaseModel):
    """Output schema with essential fields only."""

    id: int
    name: str
    code: str
    is_group: bool
    parent_item_group_id: Optional[int] = None

    default_expense_account_id: Optional[int] = None
    default_income_account_id: Optional[int] = None
    default_inventory_account_id: Optional[int] = None

    model_config = {"from_attributes": True}