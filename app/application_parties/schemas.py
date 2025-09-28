from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field

from app.application_parties.parties_models import PartyNatureEnum, PartyRoleEnum


# --- Inputs ---

class PartyOrganizationDetailCreate(BaseModel):
    org_company_name: Optional[str] = None
    org_branch_name: Optional[str] = None
    org_contact_name: Optional[str] = None
    org_contact_phone: Optional[str] = None
    org_contact_email: Optional[str] = None
    # REFACTORED: Removed city_id to align with the corrected model.
    # The main PartyCreate schema now handles the city_id.


class PartyCommercialPolicyCreate(BaseModel):
    allow_credit: bool = True
    credit_limit: float = 0.0


class PartyCreate(BaseModel):
    # Required fields
    name: str
    nature: PartyNatureEnum
    role: PartyRoleEnum
    phone: str

    # Optional fields
    code: Optional[str] = None
    is_cash_party: bool = False
    email: Optional[str] = None
    address_line1: Optional[str] = None
    city_id: Optional[int] = None
    notes: Optional[str] = None

    # Detail models
    org_details: Optional[PartyOrganizationDetailCreate] = None
    commercial_policy: Optional[PartyCommercialPolicyCreate] = None

    # REFACTORED: Removed the Pydantic validator. While good for initial checks,
    # the ultimate authority for this business rule must be the service layer to ensure
    # consistency across both create and update operations. Placing it only here
    # gives a false sense of complete validation.


class PartyUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    city_id: Optional[int] = None
    notes: Optional[str] = None

    # NOTE: It's good practice to not allow changing fundamental properties like role, nature, or is_cash_party
    # via a general update endpoint. If that's needed, it should be a specific, controlled action.

    # Nested updates
    org_details: Optional[PartyOrganizationDetailCreate] = None
    commercial_policy: Optional[PartyCommercialPolicyCreate] = None


# --- Outputs ---

class PartyMinimalOut(BaseModel):
    id: int
    code: str
    name: str
    role: PartyRoleEnum
    branch_id: Optional[int] = None

    class Config:
        from_attributes = True  # Pydantic v2 syntax for orm_mode


class PartyCreateResponse(BaseModel):
    message: str = "Party created successfully."
    party: PartyMinimalOut


# --- Other Schemas ---

class PartyBulkDelete(BaseModel):
    ids: List[int]