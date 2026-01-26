from __future__ import annotations


from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator

from app.common.models.base import StatusEnum


# ----------------------------
# Company – inputs
# ----------------------------

class CompanyCreate(BaseModel):
    name: str
    headquarters_address: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    city_id: Optional[int] = None

    prefix: str
    timezone: str
    status: StatusEnum = StatusEnum.ACTIVE

    # Optional: allow explicit owner username; otherwise we auto-generate PREFIX-0001 style
    owner_username: Optional[str] = None

    # NEW: choose a package from UI (e.g. "full_suite", "inventory", etc.)
    package_slug: Optional[str] = None

    @validator("name")
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Company name is required.")
        return v

    @validator("prefix")
    def _normalize_prefix(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("Company prefix is required.")
        return v

    @validator("timezone")
    def _strip_timezone(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Timezone is required.")
        return v

    @validator("owner_username")
    def _strip_owner_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None

    @validator("package_slug")
    def _strip_package_slug(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    headquarters_address: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    city_id: Optional[int] = None
    prefix: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[StatusEnum] = None

    @validator("prefix")
    def _normalize_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        return v or None

    @validator("name", "timezone")
    def _strip_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None















# ----------------------------
# Company – delete
# ----------------------------
class CompanyArchiveRequest(BaseModel):
    confirm_name: str = Field(..., min_length=1)
    reason: Optional[str] = None  # optional, for audit/logging

class CompanyRestoreRequest(BaseModel):
    confirm_name: str = Field(..., min_length=1)

class CompanyDeleteRequest(BaseModel):
    confirm_name: str = Field(..., description="Must match the company name to confirm deletion")
    purge: bool = Field(default=False, description="If true, also deletes company-scoped auth/subscription records")

    @validator("confirm_name")
    def _strip_confirm_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("confirm_name is required.")
        return v


# ----------------------------
# Company – package subscription set
# ----------------------------

class CompanyPackageSetRequest(BaseModel):
    package_slug: str
    is_enabled: bool = True
    valid_until: Optional[datetime] = None
    extra: dict = Field(default_factory=dict)

    @validator("package_slug")
    def _strip_slug(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("package_slug is required.")
        return v

# ----------------------------
# Branch – inputs
# ----------------------------

class BranchCreate(BaseModel):
    company_id: int
    name: str
    code: str
    location: Optional[str] = None
    is_hq: bool = False
    status: StatusEnum = StatusEnum.ACTIVE


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    location: Optional[str] = None
    is_hq: Optional[bool] = None
    status: Optional[StatusEnum] = None


# ----------------------------
# Package / Subscription – inputs
# ----------------------------

class CompanySetPackageRequest(BaseModel):
    """
    Enable/disable a package for a company from UI.
    """
    package_slug: str
    is_enabled: bool = True
    valid_until: Optional[datetime] = None
    extra: Dict[str, Any] = Field(default_factory=dict)

    @validator("package_slug")
    def _strip_pkg(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("package_slug is required.")
        return v


# ----------------------------
# Outputs
# ----------------------------

class OwnerUserOut(BaseModel):
    id: int
    username: str
    temp_password: str


class CompanyMinimalOut(BaseModel):
    id: int
    name: str
    prefix: Optional[str] = None
    timezone: Optional[str] = None
    status: StatusEnum


class BranchMinimalOut(BaseModel):
    id: int
    company_id: int
    name: str
    code: Optional[str] = None
    is_hq: bool
    status: StatusEnum


class CompanyCreateResponse(BaseModel):
    message: str = "Company created successfully"
    company: CompanyMinimalOut
    owner_user: OwnerUserOut


class ModulePackageOut(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    is_enabled: bool


class CompanyPackageSubscriptionOut(BaseModel):
    company_id: int
    package_id: int
    package_slug: str
    package_name: str
    is_enabled: bool
    valid_from: datetime
    valid_until: Optional[datetime] = None
