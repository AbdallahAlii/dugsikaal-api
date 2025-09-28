# app/navigation_workspace/schemas.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel

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
    links: List[NavLinkOut]                  # root links (no section)
    sections: List[NavSectionOut]            # grouped links

class NavTreeOut(BaseModel):
    workspaces: List[NavWorkspaceOut]




class DirectoryLocation(BaseModel):
    workspace_slug: str
    workspace_title: str
    section_label: Optional[str]
    path: str
    icon: Optional[str] = None

class DirectoryDoctype(BaseModel):
    id: int
    name: str               # human label (e.g., "Purchase Receipt")
    group: str              # grouping label shown to user (workspace title or domain)
    actions: List[str]      # ["READ","CREATE","SUBMIT",...]
    primary_path: str       # best "Go to List" route
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
