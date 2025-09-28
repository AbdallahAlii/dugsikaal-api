#
# # app/application_parties/services.py
#
# from __future__ import annotations
# import logging
# from typing import Optional, List, Dict
#
# from sqlalchemy.exc import IntegrityError
# from sqlalchemy.orm import Session
# from werkzeug.exceptions import BadRequest, Unauthorized, Forbidden, NotFound
#
# from app.application_parties.parties_models import Party, PartyRoleEnum, PartyOrganizationDetail, PartyCommercialPolicy
# from app.application_parties.repo import PartyRepository
# from app.application_parties.schemas import PartyCreate, PartyUpdate, PartyMinimalOut, PartyBulkDelete
# from config.database import db
# from app.common.generate_code.service import generate_next_code
# from app.security.rbac_effective import AffiliationContext
# from app.security.rbac_guards import ensure_scope_by_ids
#
# log = logging.getLogger(__name__)
#
# CUST_PREFIX = "CUST"
# SUPP_PREFIX = "SUP"
# GLOBAL_PARTY_ROLES = {"Super Admin", "Operations Manager", "Purchase Manager"}
#
#
# # REFACTORED: Define custom exceptions for cleaner error handling
# class PartyLogicError(BadRequest):
#     """Base exception for party-related business logic errors."""
#     pass
#
#
# class DuplicatePartyCodeError(PartyLogicError):
#     """Raised when a party code already exists for the company."""
#     pass
#
#
# class PartyService:
#     def __init__(self, repo: Optional[PartyRepository] = None, session: Optional[Session] = None):
#         self.repo = repo or PartyRepository(session or db.session)
#         self.s = self.repo.s
#
#     def _validate_commercial_policy(self, is_cash_party: bool, role: PartyRoleEnum, policy: Optional[dict]):
#         """Central validation logic for commercial policies."""
#         # FIX: The rule should apply to cash parties of any role, not just Customers.
#         if policy and is_cash_party:
#             raise PartyLogicError("Cash parties cannot have a commercial policy.")
#
#     def create_party(
#             self,
#             payload: PartyCreate,
#             context: AffiliationContext,
#             branch_id: Optional[int] = None,
#     ) -> PartyMinimalOut:
#         # REFACTORED: Service now returns a Pydantic model on success or raises an exception on failure.
#         try:
#             company_id = context.company_id
#             if not company_id:
#                 raise Unauthorized("User company context missing.")
#
#             # Rule: Cash customers cannot have a commercial policy.
#             self._validate_commercial_policy(payload.is_cash_party, payload.role, payload.commercial_policy)
#
#             # --- Scope and Permission checks ---
#             is_global_creator = bool(GLOBAL_PARTY_ROLES.intersection(context.roles))
#             final_branch_id = branch_id
#             if final_branch_id is None and not is_global_creator:
#                 if not context.branch_id:
#                     raise Forbidden("User has no assigned branch to create a party.")
#                 final_branch_id = context.branch_id[0]
#             # If the user is a global creator (Super Admin, etc.), they can create at the company level.
#             # Otherwise, the party must be tied to a specific branch.
#             if is_global_creator and branch_id is None:
#                 final_branch_id = None
#
#             ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=final_branch_id)
#
#             if payload.role == PartyRoleEnum.CUSTOMER and not (
#                     is_global_creator or "Sales User" in context.roles):
#                 raise Forbidden("Not authorized to create a Customer.")
#
#             if payload.role == PartyRoleEnum.SUPPLIER and not (
#                     is_global_creator or "Purchase User" in context.roles):
#                 raise Forbidden("Not authorized to create a Supplier.")
#
#             # --- Business Logic validations ---
#             if payload.is_cash_party and self.repo.get_cash_party_by_role(company_id, payload.role):
#                 raise PartyLogicError(f"A cash {payload.role.value} party already exists.")
#
#             if not payload.code:
#                 prefix = CUST_PREFIX if payload.role == PartyRoleEnum.CUSTOMER else SUPP_PREFIX
#                 # FIX: Pass the resolved final_branch_id
#                 payload.code = generate_next_code(prefix=prefix, company_id=company_id, branch_id=final_branch_id)
#             elif self.repo.party_code_exists(company_id, payload.code):
#                 raise DuplicatePartyCodeError("Party code already exists.")
#
#             # --- Database Operations ---
#             p = Party(company_id=company_id, branch_id=final_branch_id,
#                       **payload.dict(exclude={'org_details', 'commercial_policy'}))
#             self.repo.create_party(p)
#
#             if payload.org_details:
#                 self.repo.create_organization_details(
#                     PartyOrganizationDetail(**payload.org_details.dict(), party_id=p.id)
#                 )
#
#             if payload.commercial_policy:
#                 self.repo.create_commercial_policy(
#                     PartyCommercialPolicy(**payload.commercial_policy.dict(), party_id=p.id, company_id=company_id)
#                 )
#
#             self.s.commit()
#             return PartyMinimalOut.from_orm(p)
#
#         except (BadRequest, Unauthorized, Forbidden, IntegrityError) as e:
#             self.s.rollback()
#             msg = str(getattr(e, "orig", e)).lower()
#             if "parties_city_id_fkey" in msg:
#                 # REVISED FIX: Raise a generic, user-friendly error.
#                 raise PartyLogicError("The selected city does not exist or is invalid.")
#
#             if isinstance(e, IntegrityError) and "uq_party_company_code" in str(e.orig).lower():
#                 raise DuplicatePartyCodeError("Party code must be unique.")
#             log.warning(f"Party creation failed: {e}")
#             raise e  # Re-raise the original or a wrapped exception
#         except Exception:
#             self.s.rollback()
#             log.exception("Unexpected error during party creation.")
#             raise
#
#     def update_party(self, party_id: int, payload: PartyUpdate, context: AffiliationContext) -> PartyMinimalOut:
#         try:
#             p: Optional[Party] = self.repo.get_party_by_id(party_id)
#             if not p:
#                 raise NotFound("Party not found.")
#
#             if not self._can_manage_party(context, p):
#                 raise Forbidden("Not authorized to update this party.")
#
#             # Rule: Cannot add a commercial policy to a cash customer.
#             self._validate_commercial_policy(p.is_cash_party, p.role, payload.commercial_policy)
#
#             updates = payload.dict(exclude={'org_details', 'commercial_policy'}, exclude_unset=True)
#             self.repo.update_party(p, updates)
#
#             if payload.org_details:
#                 org_updates = payload.org_details.dict()
#                 if not p.org_details:
#                     self.repo.create_organization_details(PartyOrganizationDetail(**org_updates, party_id=p.id))
#                 else:
#                     self.repo.update_organization_details(p.org_details, org_updates)
#
#             if payload.commercial_policy:
#                 policy_updates = payload.commercial_policy.dict()
#                 if not p.commercial_policy:
#                     self.repo.create_commercial_policy(
#                         PartyCommercialPolicy(**policy_updates, party_id=p.id, company_id=p.company_id))
#                 else:
#                     self.repo.update_commercial_policy(p.commercial_policy, policy_updates)
#
#             self.s.commit()
#             return PartyMinimalOut.from_orm(p)
#
#         except (BadRequest, Unauthorized, Forbidden, NotFound) as e:
#             self.s.rollback()
#             raise e
#         except Exception:
#             self.s.rollback()
#             log.exception("Unexpected error during party update.")
#             raise
#
#     def bulk_delete_parties(self, payload: PartyBulkDelete, context: AffiliationContext) -> Dict[str, int]:
#         try:
#             parties_to_delete = self.repo.get_parties_to_delete(payload.ids)
#             if not parties_to_delete:
#                 raise NotFound("No valid parties found to delete.")
#
#             for p in parties_to_delete:
#                 if not self._can_manage_party(context, p):
#                     raise Forbidden("Not authorized to delete one or more of the selected parties.")
#
#                 # FIX: Add a check to prevent deletion of cash parties.
#                 if p.is_cash_party:
#                     raise PartyLogicError(f"Cash {p.role.value} cannot be deleted.")
#
#             deleted_count = self.repo.delete_parties(payload.ids)
#             self.s.commit()
#
#             return {"deleted_count": deleted_count}
#
#         except (Forbidden, NotFound, PartyLogicError) as e:
#             self.s.rollback()
#             raise e
#         except Exception:
#             self.s.rollback()
#             log.exception("Unexpected error during bulk party deletion.")
#             raise
#
#     def _can_manage_party(self, context: AffiliationContext, party: Party) -> bool:
#         # FIX: The context has a `roles` attribute, not `effective_roles`.
#         # This part of the code needs to be updated as well.
#         is_global_manager = bool(GLOBAL_PARTY_ROLES.intersection(context.roles))
#         if is_global_manager and party.company_id == context.company_id:
#             return True
#         if party.branch_id is not None and party.branch_id in context.branch_id:
#             return True
#         return False
# app/application_parties/services.py

from __future__ import annotations
import logging
from typing import Optional, List, Dict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Unauthorized, Forbidden, NotFound

from app.application_parties.parties_models import (
    Party, PartyRoleEnum, PartyOrganizationDetail, PartyCommercialPolicy
)
from app.application_parties.repo import PartyRepository
from app.application_parties.schemas import PartyCreate, PartyUpdate, PartyMinimalOut, PartyBulkDelete
from config.database import db
from app.common.generate_code.service import generate_next_code
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

log = logging.getLogger(__name__)

CUST_PREFIX = "CUST"
SUPP_PREFIX = "SUP"
GLOBAL_PARTY_ROLES = {"Super Admin", "Operations Manager", "Purchase Manager"}


class PartyLogicError(BadRequest):
    pass


class DuplicatePartyCodeError(PartyLogicError):
    pass


class PartyService:
    def __init__(self, repo: Optional[PartyRepository] = None, session: Optional[Session] = None):
        self.repo = repo or PartyRepository(session or db.session)
        self.s = self.repo.s

    # ---- helpers -------------------------------------------------------------
    def _user_branch_ids(self, context: AffiliationContext) -> List[int]:
        """
        Normalize affiliation context branches to a list.
        Supports either `.branch_ids` (list-like) or `.branch_id` (single).
        """
        ids = getattr(context, "branch_ids", None)
        if ids:
            try:
                return list(ids)
            except TypeError:
                pass
        single = getattr(context, "branch_id", None)
        return [single] if single is not None else []

    def _is_global_actor(self, context: AffiliationContext) -> bool:
        roles = set(getattr(context, "roles", []) or [])
        return bool(GLOBAL_PARTY_ROLES.intersection(roles))

    def _validate_commercial_policy(self, is_cash_party: bool, role: PartyRoleEnum, policy: Optional[dict]):
        # Cash parties (any role) must not have commercial policy
        if policy and is_cash_party:
            raise PartyLogicError("Cash parties cannot have a commercial policy.")

    # ---- create --------------------------------------------------------------
    def create_party(
        self,
        payload: PartyCreate,
        context: AffiliationContext,
        branch_id: Optional[int] = None,
    ) -> PartyMinimalOut:
        try:
            company_id = getattr(context, "company_id", None)
            if not company_id:
                raise Unauthorized("User company context missing.")

            # business rule
            self._validate_commercial_policy(payload.is_cash_party, payload.role, payload.commercial_policy)

            # scope & branch resolution
            is_global_creator = self._is_global_actor(context)
            final_branch_id: Optional[int]

            if branch_id is not None:
                # explicit branch provided -> must be in scope
                final_branch_id = branch_id
            else:
                if is_global_creator:
                    # allow company-level party (no branch)
                    final_branch_id = None
                else:
                    user_branches = self._user_branch_ids(context)
                    if not user_branches:
                        raise Forbidden("User has no assigned branch to create a party.")
                    final_branch_id = user_branches[0]

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=final_branch_id,
            )

            # role-based permission
            roles = set(getattr(context, "roles", []) or [])
            if payload.role == PartyRoleEnum.CUSTOMER and not (is_global_creator or "Sales User" in roles):
                raise Forbidden("Not authorized to create a Customer.")
            if payload.role == PartyRoleEnum.SUPPLIER and not (is_global_creator or "Purchase User" in roles):
                raise Forbidden("Not authorized to create a Supplier.")

            # single cash party per role per company
            if payload.is_cash_party and self.repo.get_cash_party_by_role(company_id, payload.role):
                raise PartyLogicError(f"A cash {payload.role.value} party already exists.")

            # code
            if not payload.code:
                prefix = CUST_PREFIX if payload.role == PartyRoleEnum.CUSTOMER else SUPP_PREFIX
                payload.code = generate_next_code(prefix=prefix, company_id=company_id, branch_id=None)
            elif self.repo.party_code_exists(company_id, payload.code):
                raise DuplicatePartyCodeError("Party code already exists.")

            # persist
            base_data = payload.dict(exclude={"org_details", "commercial_policy"})
            p = Party(company_id=company_id, branch_id=final_branch_id, **base_data)
            self.repo.create_party(p)

            if payload.org_details:
                self.repo.create_organization_details(
                    PartyOrganizationDetail(**payload.org_details.dict(), party_id=p.id)
                )
            if payload.commercial_policy:
                self.repo.create_commercial_policy(
                    PartyCommercialPolicy(**payload.commercial_policy.dict(), party_id=p.id, company_id=company_id)
                )

            self.s.commit()
            return PartyMinimalOut.from_orm(p)

        except (BadRequest, Unauthorized, Forbidden, IntegrityError) as e:
            self.s.rollback()
            msg = str(getattr(e, "orig", e)).lower()
            if "parties_city_id_fkey" in msg:
                raise PartyLogicError("The selected city does not exist or is invalid.")
            if isinstance(e, IntegrityError) and "uq_party_company_code" in msg:
                raise DuplicatePartyCodeError("Party code must be unique.")
            log.warning(f"Party creation failed: {e}")
            raise
        except Exception:
            self.s.rollback()
            log.exception("Unexpected error during party creation.")
            raise

    # ---- update --------------------------------------------------------------
    def update_party(self, party_id: int, payload: PartyUpdate, context: AffiliationContext) -> PartyMinimalOut:
        try:
            p: Optional[Party] = self.repo.get_party_by_id(party_id)
            if not p:
                raise NotFound("Party not found.")

            if not self._can_manage_party(context, p):
                raise Forbidden("Not authorized to update this party.")

            self._validate_commercial_policy(p.is_cash_party, p.role, payload.commercial_policy)

            updates = payload.dict(exclude={"org_details", "commercial_policy"}, exclude_unset=True)
            self.repo.update_party(p, updates)

            if payload.org_details:
                org_updates = payload.org_details.dict()
                if not p.org_details:
                    self.repo.create_organization_details(PartyOrganizationDetail(**org_updates, party_id=p.id))
                else:
                    self.repo.update_organization_details(p.org_details, org_updates)

            if payload.commercial_policy:
                policy_updates = payload.commercial_policy.dict()
                if not p.commercial_policy:
                    self.repo.create_commercial_policy(
                        PartyCommercialPolicy(**policy_updates, party_id=p.id, company_id=p.company_id)
                    )
                else:
                    self.repo.update_commercial_policy(p.commercial_policy, policy_updates)

            self.s.commit()
            return PartyMinimalOut.from_orm(p)

        except (BadRequest, Unauthorized, Forbidden, NotFound) as e:
            self.s.rollback()
            raise
        except Exception:
            self.s.rollback()
            log.exception("Unexpected error during party update.")
            raise

    # ---- bulk delete ---------------------------------------------------------
    def bulk_delete_parties(self, payload: PartyBulkDelete, context: AffiliationContext) -> Dict[str, int]:
        try:
            parties_to_delete = self.repo.get_parties_to_delete(payload.ids)
            if not parties_to_delete:
                raise NotFound("No valid parties found to delete.")

            for p in parties_to_delete:
                if not self._can_manage_party(context, p):
                    raise Forbidden("Not authorized to delete one or more of the selected parties.")
                if p.is_cash_party:
                    raise PartyLogicError(f"Cash {p.role.value} cannot be deleted.")

            deleted_count = self.repo.delete_parties(payload.ids)
            self.s.commit()
            return {"deleted_count": deleted_count}

        except (Forbidden, NotFound, PartyLogicError) as e:
            self.s.rollback()
            raise
        except Exception:
            self.s.rollback()
            log.exception("Unexpected error during bulk party deletion.")
            raise

    # ---- authorization helper ------------------------------------------------
    def _can_manage_party(self, context: AffiliationContext, party: Party) -> bool:
        is_global_manager = self._is_global_actor(context)
        if is_global_manager and party.company_id == getattr(context, "company_id", None):
            return True
        user_branches = self._user_branch_ids(context)
        if party.branch_id is not None and party.branch_id in user_branches:
            return True
        return False
