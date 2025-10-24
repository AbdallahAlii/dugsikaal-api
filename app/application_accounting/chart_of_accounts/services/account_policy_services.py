from __future__ import annotations
import logging
from typing import Optional
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound

from app.business_validation.item_validation import BizValidationError
from app.common.cache.cache_invalidator import bump_mop_list_company, bump_mop_detail, bump_list_cache_company
from app.security.rbac_effective import AffiliationContext
from config.database import db

from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, ModeOfPaymentAccount, AccountAccessPolicy
)
from app.application_accounting.chart_of_accounts.schemas.account_policies_schemas import (
    ModeOfPaymentCreate, ModeOfPaymentUpdate, AccountAccessPolicyCreate, AccountAccessPolicyUpdate
)
from app.application_accounting.chart_of_accounts.Repository.account_policies_repo import PoliciesRepository

log = logging.getLogger(__name__)


class PoliciesService:
    def __init__(self, repo: Optional[PoliciesRepository] = None, session=None):
        self.repo = repo or PoliciesRepository(session or db.session)
        self.s = self.repo.s

    # ───────────── Mode of Payment ─────────────
    def create_mode_of_payment(self, payload: ModeOfPaymentCreate, ctx: AffiliationContext) -> ModeOfPayment:
        # Check unique name
        if self.repo.get_mop_by_name(ctx.company_id, payload.name):
            raise BizValidationError("Mode of Payment already exists")

        try:
            # Create MoP
            mop = ModeOfPayment(
                company_id=ctx.company_id,
                name=payload.name.strip(),
                type=payload.type,
                enabled=payload.enabled,
            )
            self.repo.create_mop(mop)

            # Add accounts (Frappe-style: create with all accounts)
            for acc in payload.accounts:
                if not self.repo.account_in_company(ctx.company_id, acc.account_id):
                    raise BizValidationError(f"Account {acc.account_id} not found in company")

                if not self.repo.account_is_leaf(acc.account_id):
                    raise BizValidationError("Account must be a leaf account")

                # Handle default
                if acc.is_default:
                    self.repo.unset_mop_defaults(mop.id)

                mop_acc = ModeOfPaymentAccount(
                    mode_of_payment_id=mop.id,
                    account_id=acc.account_id,
                    is_default=acc.is_default,
                    enabled=acc.enabled
                )
                self.repo.add_mop_account(mop_acc)

            self.s.commit()
            # 🔄 Cache bumps: list (company) and detail
            bump_mop_list_company(ctx.company_id)
            bump_mop_detail(mop.id)
            return mop

        except BizValidationError as e:
            self.s.rollback()
            # Let the precise validation message reach the API response layer
            raise e
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Duplicate account mapping")
        except Exception as e:
            self.s.rollback()
            log.exception("Create MoP failed: %s", str(e))
            raise BizValidationError("Failed to create Mode of Payment")

    def update_mode_of_payment(self, mop_id: int, payload: ModeOfPaymentUpdate,
                               ctx: AffiliationContext) -> ModeOfPayment:
        mop = self.repo.get_mop_by_id(mop_id)
        if not mop or mop.company_id != ctx.company_id:
            raise NotFound("Mode of Payment not found")

        try:
            # Update basic fields
            updates = {}
            if payload.name is not None:
                existing = self.repo.get_mop_by_name(ctx.company_id, payload.name.strip())
                if existing and existing.id != mop_id:
                    raise BizValidationError("Mode of Payment name already exists")
                updates["name"] = payload.name.strip()

            if payload.type is not None:
                updates["type"] = payload.type
            if payload.enabled is not None:
                updates["enabled"] = payload.enabled

            if updates:
                self.repo.update_mop_fields(mop, updates)

            # Frappe-style: replace entire accounts table if provided
            if payload.accounts is not None:
                # Remove existing accounts
                existing_accounts = self.repo.get_mop_accounts(mop_id)
                for existing in existing_accounts:
                    self.s.delete(existing)

                # Add new accounts
                for acc in payload.accounts:
                    if not self.repo.account_in_company(ctx.company_id, acc.account_id):
                        raise BizValidationError(f"Account {acc.account_id} not found in company")

                    if not self.repo.account_is_leaf(acc.account_id):
                        raise BizValidationError("Account must be a leaf account")

                    # Handle default
                    if acc.is_default:
                        self.repo.unset_mop_defaults(mop_id)

                    mop_acc = ModeOfPaymentAccount(
                        mode_of_payment_id=mop_id,
                        account_id=acc.account_id,
                        is_default=acc.is_default,
                        enabled=acc.enabled
                    )
                    self.repo.add_mop_account(mop_acc)

            self.s.commit()
            # 🔄 Cache bumps: list (company) and detail
            bump_mop_list_company(ctx.company_id)
            bump_mop_detail(mop.id)
            return mop

        except BizValidationError as e:
            self.s.rollback()
            # Preserve exact validation message (e.g., "Account must be a leaf account")
            raise e
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Duplicate account mapping")
        except Exception as e:
            self.s.rollback()
            log.exception("Update MoP failed: %s", str(e))
            raise BizValidationError("Failed to update Mode of Payment")

    # ───────────── Account Access Policy ─────────────
    def create_access_policy(self, payload: AccountAccessPolicyCreate, ctx: AffiliationContext) -> AccountAccessPolicy:
        # Validate references
        if not self.repo.account_in_company(ctx.company_id, payload.account_id):
            raise BizValidationError("Account not found")

        if not self.repo.account_is_leaf(payload.account_id):
            raise BizValidationError("Account must be a leaf account")

        mop = self.repo.get_mop_by_id(payload.mode_of_payment_id)
        if not mop or mop.company_id != ctx.company_id:
            raise BizValidationError("Mode of Payment not found")

        # Validate account is linked to MoP
        if not self.repo.mop_has_account(payload.mode_of_payment_id, payload.account_id):
            raise BizValidationError("Account not linked to this Mode of Payment")

        try:
            policy = AccountAccessPolicy(
                mode_of_payment_id=payload.mode_of_payment_id,
                company_id=ctx.company_id,
                role=payload.role,
                account_id=payload.account_id,
                user_id=payload.user_id,
                department_id=payload.department_id,
                branch_id=payload.branch_id,
                enabled=payload.enabled,
            )
            self.repo.create_access_policy(policy)
            self.s.commit()
            bump_list_cache_company("accounting", "account_access_policies", ctx.company_id)
            return policy

        except BizValidationError as e:
            self.s.rollback()
            raise e
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Duplicate policy")
        except Exception as e:
            self.s.rollback()
            log.exception("Create policy failed: %s", str(e))
            raise BizValidationError("Failed to create policy")

    def update_access_policy(self, policy_id: int, payload: AccountAccessPolicyUpdate,
                             ctx: AffiliationContext) -> AccountAccessPolicy:
        policy = self.repo.get_access_policy_by_id(policy_id)
        if not policy or policy.company_id != ctx.company_id:
            raise NotFound("Policy not found")

        try:
            updates = {}
            for field in ["role", "account_id", "user_id", "department_id", "branch_id", "enabled"]:
                if getattr(payload, field) is not None:
                    updates[field] = getattr(payload, field)

            if updates:
                # Validate account if changing
                if "account_id" in updates:
                    if not self.repo.account_in_company(ctx.company_id, updates["account_id"]):
                        raise BizValidationError("Account not found")
                    if not self.repo.account_is_leaf(updates["account_id"]):
                        raise BizValidationError("Account must be a leaf account")
                    if not self.repo.mop_has_account(policy.mode_of_payment_id, updates["account_id"]):
                        raise BizValidationError("Account not linked to this Mode of Payment")

                self.repo.update_access_policy_fields(policy, updates)

            self.s.commit()
            # 🔄 Cache bumps: list only
            bump_list_cache_company("accounting", "account_access_policies", ctx.company_id)
            return policy

        except BizValidationError as e:
            self.s.rollback()
            raise e
        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Duplicate policy")
        except Exception as e:
            self.s.rollback()
            log.exception("Update policy failed: %s", str(e))
            raise BizValidationError("Failed to update policy")
