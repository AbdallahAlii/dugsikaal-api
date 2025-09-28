# app/auth/schemas.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class AffiliationOut(BaseModel):
    id: int
    company_id: int
    branch_id: Optional[int]
    user_type_id: int
    user_type: str
    is_primary: bool
    linked_entity_id: Optional[int]


class UserLite(BaseModel):
    id: int
    username: str


class MeResponse(BaseModel):
    ok: bool = True
    user: UserLite


class UserProfileResponse(BaseModel):
    ok: bool = True
    profile: dict  # simple dict; you can replace with a typed model later


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserLite
    message: str = Field(default="Login successful")


class LogoutResponse(BaseModel):
    ok: bool = True
    message: str = Field(default="Logout successful")



class ResetPasswordRequest(BaseModel):
    new_password: str

class ChangeMyPasswordRequest(BaseModel):
    old_password: str
    new_password: str

class UpdateAccountStatusRequest(BaseModel):
    new_status: str  # "Active" | "Inactive"