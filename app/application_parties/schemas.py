# app/application_parties/schemas.py

from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, Field

from app.application_parties.parties_models import PartyNatureEnum, PartyRoleEnum


# ---------------------------------------------------------------------------
# Nested / detail inputs
# ---------------------------------------------------------------------------

class PartyOrganizationDetailCreate(BaseModel):
    org_company_name: Optional[str] = None
    org_branch_name: Optional[str] = None
    org_contact_name: Optional[str] = None
    org_contact_phone: Optional[str] = None
    org_contact_email: Optional[str] = None
    # NOTE: city_id lives on Party itself, not here.


class PartyCommercialPolicyCreate(BaseModel):
    allow_credit: bool = True
    credit_limit: float = 0.0


# ---------------------------------------------------------------------------
# Core Party inputs
# ---------------------------------------------------------------------------

class PartyCreate(BaseModel):
    """
    Input schema for creating a Party.

    Company/branch are *not* included here:
    - `company_id` is taken from AffiliationContext or passed as a separate
      argument to the service when needed (e.g., Data Import).
    - `branch_id` is passed separately to the service and is optional:
        * if provided -> branch-scoped party
        * if omitted -> company-level (global) party
    """

    # Required
    name: str
    nature: PartyNatureEnum
    role: PartyRoleEnum
    phone: str

    # Optional basics
    code: Optional[str] = None
    is_cash_party: bool = False
    email: Optional[str] = None
    address_line1: Optional[str] = None
    city_id: Optional[int] = None
    notes: Optional[str] = None

    # Optional nested detail models
    org_details: Optional[PartyOrganizationDetailCreate] = None
    commercial_policy: Optional[PartyCommercialPolicyCreate] = None


class PartyUpdate(BaseModel):
    """
    Input schema for updating a Party.

    We intentionally do NOT allow changing:
      - role
      - nature
      - is_cash_party
    via this general update API. If you ever need to support that,
    it should be a dedicated, controlled action.
    """

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    city_id: Optional[int] = None
    notes: Optional[str] = None

    org_details: Optional[PartyOrganizationDetailCreate] = None
    commercial_policy: Optional[PartyCommercialPolicyCreate] = None


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class PartyMinimalOut(BaseModel):
    id: int
    code: str
    name: str
    role: PartyRoleEnum
    branch_id: Optional[int] = None

    class Config:
        from_attributes = True  # Pydantic v2 equivalent of orm_mode = True


class PartyCreateResponse(BaseModel):
    message: str = "Party created successfully."
    party: PartyMinimalOut


# ---------------------------------------------------------------------------
# Other schemas
# ---------------------------------------------------------------------------

class PartyBulkDelete(BaseModel):
    ids: List[int] = Field(..., min_length=1)
