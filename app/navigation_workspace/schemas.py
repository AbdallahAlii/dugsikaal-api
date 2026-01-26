from __future__ import annotations


from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field
# -----------------------------
# Navigation tree (workspace menu)
# -----------------------------

class NavLinkOut(BaseModel):
    label: str
    path: str
    icon: Optional[str] = None


class NavSectionOut(BaseModel):
    label: str
    links: List[NavLinkOut]


class NavWorkspaceOut(BaseModel):
    title: str
    slug: str
    icon: Optional[str] = None
    description: Optional[str] = None
    # Root links (no section). With the new model these may often be empty.
    links: List[NavLinkOut]
    # Section groups with links.
    sections: List[NavSectionOut]
    home_path: Optional[str] = None

class NavTreeOut(BaseModel):
    workspaces: List[NavWorkspaceOut]


# -----------------------------
# DocType directory
# -----------------------------

class DirectoryLocation(BaseModel):
    workspace_slug: str
    workspace_title: str
    section_label: Optional[str]
    path: str
    icon: Optional[str] = None


class DirectoryDoctype(BaseModel):
    id: int
    name: str               # human label (e.g., "Purchase Receipt")
    group: str              # grouping label (workspace title or domain)
    actions: List[str]      # ["READ", "CREATE", "SUBMIT", ...]
    primary_path: str       # best "Go to List" / relevant route
    locations: List[DirectoryLocation]


class DocTypeDirectoryOut(BaseModel):
    doctypes: List[DirectoryDoctype]


class DocTypeDetailsOut(BaseModel):
    id: int
    name: str
    group: str
    actions: List[str]
    primary_path: str
    locations: List[DirectoryLocation]


# -----------------------------
# Admin: packages & visibility
# -----------------------------

class CompanyPackageIn(BaseModel):
    """
    One row per package (ERP-style).
    All fields are per-package, no shared valid_from for all.
    Dates come as DATE ONLY ("2025-11-27").
    """
    slug: str
    is_enabled: bool
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


class CompanyPackagesSetIn(BaseModel):
    """
    Bulk set/toggle many packages for a company at once.
    """
    packages: List[CompanyPackageIn] = Field(default_factory=list)


class CompanyPackageOut(BaseModel):
    company_id: int
    package_id: int
    package_slug: str
    package_name: str
    is_enabled: bool
    valid_from: datetime
    valid_until: Optional[datetime]


class CompanyPackagesOut(BaseModel):
    company_id: int
    packages: List[CompanyPackageOut]


class CompanyPackageToggleIn(BaseModel):
    """
    Enable/disable a single package for a company.
    Used by the single-package endpoint.
    """
    is_enabled: bool
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


class SystemWorkspaceVisibilityIn(BaseModel):
    company_id: int
    workspace_slug: str
    is_enabled: bool
    reason: Optional[str] = None


class CompanyWorkspaceVisibilityIn(BaseModel):
    company_id: int
    workspace_slug: str
    is_enabled: bool
    branch_id: Optional[int] = None
    user_id: Optional[int] = None
    reason: Optional[str] = None