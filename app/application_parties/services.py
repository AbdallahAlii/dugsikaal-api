# app/application_parties/services.py

from __future__ import annotations

import logging
from typing import Optional, Dict, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import BadRequest, Unauthorized, Forbidden, NotFound

from app.application_parties.parties_models import (
    Party,
    PartyRoleEnum,
    PartyOrganizationDetail,
    PartyCommercialPolicy,
)
from app.application_parties.repo import PartyRepository
from app.application_parties.schemas import (
    PartyCreate,
    PartyUpdate,
    PartyMinimalOut,
    PartyBulkDelete,
)
from config.database import db
from app.common.generate_code.service import generate_next_code
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

log = logging.getLogger(__name__)

CUST_PREFIX = "CUST"
SUPP_PREFIX = "SUP"


class PartyLogicError(BadRequest):
    """Domain-level / business-rule errors for Party operations."""
    pass


class DuplicatePartyCodeError(PartyLogicError):
    """Raised when a Party code already exists in the company."""
    pass


class PartyService:
    """
    Clean, ERP-style Party service.

    - No hard-coded role names for authorization.
    - Route-level `require_permission("Party", "CREATE"/"UPDATE"/"DELETE")`
      handles *who* can call these methods.
    - Scope is enforced via `ensure_scope_by_ids` / `resolve_company_branch_and_scope`.
    - `branch_id` is optional:
        * if set -> branch-scoped party
        * if None -> company-level (global) party.

    Transaction strategy:

    - autocommit=True  (HTTP routes):
        * On success: flush() → build DTO → commit().
        * On error: rollback().
    - autocommit=False (Data Import / background jobs):
        * On success: flush() only.
        * On error: no rollback here → outer `begin_nested()` or caller
          is responsible for rollback. This matches ERPNext-style “runner
          controls transaction, service just applies changes”.
    """

    def __init__(
        self,
        repo: Optional[PartyRepository] = None,
        session: Optional[Session] = None,
        autocommit: bool = True,
    ) -> None:
        # NOTE: db.session is a scoped_session; attribute access is proxied
        self.repo = repo or PartyRepository(session or db.session)
        self.s: Session = self.repo.s
        self.autocommit: bool = autocommit

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _validate_commercial_policy(
        self,
        is_cash_party: bool,
        role: PartyRoleEnum,
        policy: Optional[dict],
    ) -> None:
        """
        Business rule:
        - Cash parties (any role) must NOT have a commercial policy.
        """
        if policy and is_cash_party:
            raise PartyLogicError("Cash parties cannot have a commercial policy.")

    def _rollback_if_autocommit(self) -> None:
        """
        For HTTP routes (autocommit=True) we rollback immediately on errors.
        For Data Import (autocommit=False) the outer transaction / savepoint
        handles rollback. This avoids the
        "Can't operate on closed transaction inside context manager" error
        you saw when mixing rollback with `begin_nested()`.
        """
        if self.autocommit:
            self.s.rollback()

    # -------------------------------------------------------------------------
    # Create
    # -------------------------------------------------------------------------
    def create_party(
            self,
            payload: PartyCreate,
            context: AffiliationContext,
            branch_id: Optional[int] = None,
            company_id: Optional[int] = None,
            *,
            build_dto: bool = True,
    ) -> Union[PartyMinimalOut, Party]:
        """
        Create a new Party (Customer/Supplier).

        Fixes:
          - Robust retry when auto-generated code collides (race condition / generator bug).
          - Better duplicate detection across different DB error messages.
          - Debug logging to trace company/branch/code generation and failures.
        """
        try:
            # ---- 1) Company/branch resolution with scope checks ----------------
            company_hint = company_id if company_id is not None else getattr(context, "company_id", None)
            if company_hint is None:
                raise Unauthorized("User company context missing.")

            if branch_id is not None and not isinstance(branch_id, int):
                try:
                    branch_id_int: Optional[int] = int(branch_id)
                except (TypeError, ValueError):
                    raise BadRequest("branch_id must be an integer.")
            else:
                branch_id_int = branch_id

            resolved_company_id, resolved_branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=company_hint,
                branch_id=branch_id_int,
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=False,
            )

            if not resolved_company_id:
                raise BadRequest("Company could not be resolved for this party.")

            log.debug(
                "Party.create: resolved scope company_id=%s branch_id=%s role=%s is_cash=%s user_company=%s",
                resolved_company_id,
                resolved_branch_id,
                getattr(payload.role, "value", payload.role),
                payload.is_cash_party,
                getattr(context, "company_id", None),
            )

            # ---- 2) Business rules -------------------------------------------
            self._validate_commercial_policy(
                payload.is_cash_party,
                payload.role,
                payload.commercial_policy.model_dump() if payload.commercial_policy else None,
            )

            if payload.is_cash_party and self.repo.get_cash_party_by_role(resolved_company_id, payload.role):
                raise PartyLogicError(f"A cash {payload.role.value} party already exists for this company.")

            # ---- 3) Code normalize / generation (with retry on duplicates) ----
            # If user provided code, normalize it and validate uniqueness once.
            if payload.code is not None:
                payload.code = str(payload.code).strip()
                if payload.code == "":
                    payload.code = None

            if payload.code:
                payload.code = payload.code.upper()
                if self.repo.party_code_exists(resolved_company_id, payload.code):
                    raise DuplicatePartyCodeError("Party code already exists.")
                user_provided_code = True
            else:
                user_provided_code = False

            # Retry only when code is auto-generated.
            max_attempts = 5
            last_err: Optional[Exception] = None

            for attempt in range(1, max_attempts + 1):
                # Generate if needed
                if not user_provided_code:
                    prefix = CUST_PREFIX if payload.role == PartyRoleEnum.CUSTOMER else SUPP_PREFIX
                    new_code = generate_next_code(
                        prefix=prefix,
                        company_id=resolved_company_id,
                        branch_id=None,  # unique per company
                    )
                    payload.code = str(new_code).strip().upper()

                    log.debug(
                        "Party.create: generated code=%r (attempt %d/%d) for company_id=%s role=%s",
                        payload.code, attempt, max_attempts, resolved_company_id, payload.role.value
                    )

                    # Optional pre-check (good UX), but still not race-safe by itself
                    if self.repo.party_code_exists(resolved_company_id, payload.code):
                        log.warning(
                            "Party.create: generated code already exists (precheck) code=%r company_id=%s attempt=%d",
                            payload.code, resolved_company_id, attempt,
                        )
                        continue

                # ---- 4) Persist base Party -----------------------------------
                base_data = payload.model_dump(exclude={"org_details", "commercial_policy"})
                p = Party(
                    company_id=resolved_company_id,
                    branch_id=resolved_branch_id,
                    **base_data,
                )
                self.s.add(p)

                try:
                    # flush so p.id is assigned and constraints are checked
                    self.s.flush()

                    # ---- 5) Optional detail objects ---------------------------
                    if payload.org_details:
                        self.repo.create_organization_details(
                            PartyOrganizationDetail(**payload.org_details.model_dump(), party_id=p.id)
                        )

                    if payload.commercial_policy:
                        self.repo.create_commercial_policy(
                            PartyCommercialPolicy(
                                **payload.commercial_policy.model_dump(),
                                party_id=p.id,
                                company_id=resolved_company_id,
                            )
                        )

                    # Flush again to validate child constraints
                    self.s.flush()

                    if build_dto:
                        result: Union[PartyMinimalOut, Party] = PartyMinimalOut.model_validate(p)
                    else:
                        result = p

                    if self.autocommit:
                        self.s.commit()

                    log.info(
                        "Party.create: success id=%s code=%r company_id=%s branch_id=%s role=%s",
                        p.id, p.code, p.company_id, p.branch_id, p.role.value
                    )
                    return result

                except IntegrityError as ie:
                    # IMPORTANT: session is now in failed state; must rollback (if autocommit)
                    if self.autocommit:
                        self.s.rollback()
                    else:
                        # caller controls outer tx; but we must clear state to keep looping
                        self.s.rollback()

                    msg_raw = str(getattr(ie, "orig", ie))
                    msg = msg_raw.lower()

                    is_dup_code = (
                            "uq_party_company_code" in msg
                            or (
                                        "unique constraint failed" in msg and "parties.company_id" in msg and "parties.code" in msg)
                            or ("duplicate key" in msg and "code" in msg)
                    )

                    log.warning(
                        "Party.create: IntegrityError attempt=%d/%d code=%r company_id=%s dup=%s err=%s",
                        attempt, max_attempts, payload.code, resolved_company_id, is_dup_code, msg_raw
                    )

                    last_err = ie

                    # If user provided code, do NOT retry; return clean error
                    if user_provided_code:
                        raise DuplicatePartyCodeError("Party code must be unique.")

                    # Auto-generated code collided → retry generate next code
                    if is_dup_code:
                        continue

                    # Some other integrity error
                    raise

            # If we exhausted retries
            log.error(
                "Party.create: exhausted retries generating unique code company_id=%s role=%s last_code=%r",
                resolved_company_id, payload.role.value, payload.code
            )
            raise PartyLogicError("Failed to generate a unique Party code. Please try again.")

        except (BadRequest, Unauthorized, Forbidden) as e:
            self._rollback_if_autocommit()
            log.warning("Party creation failed (request/scope): %s", e)
            raise

        except PartyLogicError as e:
            self._rollback_if_autocommit()
            log.warning("Party creation failed (business): %s", e)
            raise

        except Exception as e:
            self._rollback_if_autocommit()
            log.exception("Unexpected error during party creation.")
            raise

    # -------------------------------------------------------------------------
    # Update
    # -------------------------------------------------------------------------
    def update_party(
        self,
        party_id: int,
        payload: PartyUpdate,
        context: AffiliationContext,
        *,
        build_dto: bool = True,
    ) -> Union[PartyMinimalOut, Party]:
        """
        Update an existing Party.

        - Route-level: `@require_permission("Party", "UPDATE")`.
        - Scope: user must have scope on the Party's (company_id, branch_id).

        - build_dto:
            * True  -> return PartyMinimalOut (HTTP routes).
            * False -> return Party ORM instance (for internal usage).
        """
        try:
            p: Optional[Party] = self.repo.get_party_by_id(party_id)
            if not p:
                raise NotFound("Party not found.")

            # Scope guard (system admins automatically allowed)
            ensure_scope_by_ids(
                context=context,
                target_company_id=p.company_id,
                target_branch_id=p.branch_id,
            )

            # Business rule: still enforce cash/commercial policy combination
            self._validate_commercial_policy(
                p.is_cash_party,
                p.role,
                payload.commercial_policy.model_dump()
                if payload.commercial_policy
                else None,
            )

            # Base fields
            updates = payload.model_dump(
                exclude={"org_details", "commercial_policy"},
                exclude_unset=True,
            )
            if updates:
                self.repo.update_party(p, updates)

            # Organization details
            if payload.org_details is not None:
                org_updates = payload.org_details.model_dump()
                if not p.org_details:
                    self.repo.create_organization_details(
                        PartyOrganizationDetail(**org_updates, party_id=p.id)
                    )
                else:
                    self.repo.update_organization_details(p.org_details, org_updates)

            # Commercial policy
            if payload.commercial_policy is not None:
                policy_updates = payload.commercial_policy.model_dump()
                if not p.commercial_policy:
                    self.repo.create_commercial_policy(
                        PartyCommercialPolicy(
                            **policy_updates,
                            party_id=p.id,
                            company_id=p.company_id,
                        )
                    )
                else:
                    self.repo.update_commercial_policy(
                        p.commercial_policy, policy_updates
                    )

            # Flush and build output before any commit to avoid expired attrs
            self.s.flush()

            if build_dto:
                result: Union[PartyMinimalOut, Party] = PartyMinimalOut.model_validate(p)
            else:
                result = p

            if self.autocommit:
                self.s.commit()

            return result

        except (BadRequest, Unauthorized, Forbidden, NotFound) as e:
            self._rollback_if_autocommit()
            raise

        except Exception:
            self._rollback_if_autocommit()
            log.exception("Unexpected error during party update.")
            raise

    # -------------------------------------------------------------------------
    # Bulk delete
    # -------------------------------------------------------------------------
    def bulk_delete_parties(
        self,
        payload: PartyBulkDelete,
        context: AffiliationContext,
    ) -> Dict[str, int]:
        """
        Bulk delete Parties.

        - Route-level `@require_permission("Party", "DELETE")`.
        - Scope: each Party must be in user's scope.
        - Cash parties cannot be deleted.
        """
        try:
            parties_to_delete = self.repo.get_parties_to_delete(payload.ids)
            if not parties_to_delete:
                raise NotFound("No valid parties found to delete.")

            for p in parties_to_delete:
                # Scope check per party
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=p.company_id,
                    target_branch_id=p.branch_id,
                )

                if p.is_cash_party:
                    raise PartyLogicError(
                        f"Cash {p.role.value} cannot be deleted."
                    )

            deleted_count = self.repo.delete_parties(payload.ids)

            # Ensure the delete has been flushed; commit only for autocommit
            self.s.flush()
            if self.autocommit:
                self.s.commit()

            return {"deleted_count": deleted_count}

        except (Forbidden, NotFound, PartyLogicError) as e:
            self._rollback_if_autocommit()
            raise

        except Exception:
            self._rollback_if_autocommit()
            log.exception("Unexpected error during bulk party deletion.")
            raise
