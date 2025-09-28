from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, validator

# ---------- Roles ----------

class RoleCreateRequest(BaseModel):
    name: str
    scope: str                  # "COMPANY" or "BRANCH"
    company_id: Optional[int] = None
    description: Optional[str] = None

    @validator("scope")
    def _scope_ok(cls, v: str):
        v = (v or "").upper()
        if v not in ("COMPANY", "BRANCH"):
            raise ValueError("scope must be COMPANY or BRANCH")
        return v


class BulkDeleteRolesRequest(BaseModel):
    role_ids: List[int] = Field(..., min_items=1)


# ---------- Set user roles (assign/unassign in a single call) ----------

class SetUserRolesRequest(BaseModel):
    # Assign/unassign roles in one call (SET semantics).
    role_ids: List[int] = Field(default_factory=list)


# ---------- Permission overrides ----------

class OverrideCreateRequest(BaseModel):
    permission_id: int
    is_allowed: bool
    reason: Optional[str] = None
    company_id: Optional[int] = None
    branch_id: Optional[int] = None


class OverrideDeleteRequest(BaseModel):
    permission_id: int
    company_id: Optional[int] = None
    branch_id: Optional[int] = None


# ---------- User constraints ----------

class UserConstraintCreateRequest(BaseModel):
    doctype_id: int
    field_name: str
    ref_doctype_id: int
    ref_id: int
    allow_children: bool = False


class UserConstraintDeleteRequest(BaseModel):
    doctype_id: int
    field_name: str
    ref_doctype_id: int
    ref_id: int
