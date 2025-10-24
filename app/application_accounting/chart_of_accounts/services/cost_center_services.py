from __future__ import annotations
import logging
from typing import Optional
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import Forbidden, NotFound

from app.application_accounting.chart_of_accounts.models import CostCenter
from app.application_accounting.chart_of_accounts.Repository.cost_center_repo import CostCenterRepository
from app.application_accounting.chart_of_accounts.schemas.cost_center_schemas import CostCenterCreate, CostCenterUpdate, \
    CostCenterOut
from app.application_accounting.chart_of_accounts.validators.cost_center_validators import CostCenterValidator
from app.business_validation.item_validation import BizValidationError
from app.common.cache.cache_invalidator import bump_list_cache_company, bump_list_cache_branch, \
    bump_cost_centers_list_company, bump_cost_centers_list_branch, bump_cost_center_detail
from app.security.rbac_guards import ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext
from config.database import db

log = logging.getLogger(__name__)

# Define roles that can manage cost centers
COST_CENTER_MANAGER_ROLES = {"Super Admin", "Finance Manager", "Accountant", "Operations Manager"}


class CostCenterService:
    def __init__(self, repo: Optional[CostCenterRepository] = None, session=None):
        self.repo = repo or CostCenterRepository(session or db.session)
        self.s = self.repo.s

    def create_cost_center(self, payload: CostCenterCreate, context: AffiliationContext) -> CostCenterOut:
        """Create Cost Center with comprehensive validation"""
        log.info("Creating cost center: name='%s'", payload.name)

        # Permission check
        if not COST_CENTER_MANAGER_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to create a cost center.")

        # Determine branch_id - use provided branch or user's current branch
        branch_id = payload.branch_id or getattr(context, "branch_id", None)
        if not branch_id:
            raise BizValidationError("Branch context is required for cost center creation.")

        # Scope check - user can only create for their company and accessible branch
        ensure_scope_by_ids(
            context=context,
            target_company_id=context.company_id,
            target_branch_id=branch_id
        )

        # Validate name uniqueness
        CostCenterValidator.validate_name_uniqueness(
            self.repo, context.company_id, branch_id, payload.name
        )

        try:
            # Create the cost center
            cost_center = CostCenter(
                company_id=context.company_id,
                branch_id=branch_id,
                name=payload.name,
                status=payload.status
            )

            self.repo.create_cost_center(cost_center)
            self.s.commit()

            # 🔄 Cache bumps: list (company + branch) and detail
            bump_cost_centers_list_company(context.company_id)
            bump_cost_centers_list_branch(context.company_id, branch_id)
            bump_cost_center_detail(cost_center.id)

            log.info("Cost center created successfully: id=%d, name='%s'", cost_center.id, cost_center.name)
            return CostCenterOut.model_validate(cost_center)

        except IntegrityError:
            self.s.rollback()
            raise BizValidationError("Cost center with this name already exists.")
        except Exception as e:
            self.s.rollback()
            log.error("Error creating cost center: %s", str(e))
            raise BizValidationError("Failed to create cost center.")

    def update_cost_center(self, cost_center_id: int, payload: CostCenterUpdate,
                           context: AffiliationContext) -> CostCenterOut:
        """Update cost center details"""
        cost_center = self.repo.get_cost_center_by_id(cost_center_id)
        if not cost_center:
            raise NotFound("Cost center not found.")

        # Permission check
        if not COST_CENTER_MANAGER_ROLES.intersection(context.roles):
            raise Forbidden("Not authorized to update a cost center.")

        # Scope check
        ensure_scope_by_ids(
            context=context,
            target_company_id=cost_center.company_id,
            target_branch_id=cost_center.branch_id
        )

        updates = {}

        # Validate and apply name update
        if payload.name is not None and payload.name != cost_center.name:
            CostCenterValidator.validate_name_uniqueness(
                self.repo, cost_center.company_id, cost_center.branch_id, payload.name, cost_center_id
            )
            updates['name'] = payload.name

        # Validate and apply status update
        if payload.status is not None and payload.status != cost_center.status:
            CostCenterValidator.validate_status_transition(cost_center.status.value, payload.status.value)
            updates['status'] = payload.status

        if not updates:
            raise BizValidationError("No changes provided for update.")

        try:
            self.repo.update_cost_center(cost_center, updates)
            self.s.commit()

            # 🔄 Cache bumps: list (company + branch) and detail
            bump_cost_centers_list_company(cost_center.company_id)
            bump_cost_centers_list_branch(cost_center.company_id, cost_center.branch_id)
            bump_cost_center_detail(cost_center.id)

            log.info("Cost center updated successfully: id=%d", cost_center_id)
            return CostCenterOut.model_validate(cost_center)

        except Exception as e:
            self.s.rollback()
            log.error("Error updating cost center: %s", str(e))
            raise BizValidationError("Failed to update cost center.")

    def get_company_cost_centers(self, context: AffiliationContext, branch_id: Optional[int] = None) -> list[
        CostCenterOut]:
        """Get all cost centers for the current company (and optional branch)"""
        target_branch_id = branch_id or getattr(context, "branch_id", None)

        ensure_scope_by_ids(
            context=context,
            target_company_id=context.company_id,
            target_branch_id=target_branch_id
        )

        if target_branch_id:
            cost_centers = self.repo.get_cost_centers_by_company_branch(context.company_id, target_branch_id)
        else:
            # If no branch specified, get all cost centers for company (user must have company-level access)
            cost_centers = []
            # This would require a different repo method to get all company cost centers
            # For now, we'll use the first branch the user has access to
            user_branches = [aff.branch_id for aff in getattr(context, "affiliations", [])
                             if aff.company_id == context.company_id and aff.branch_id]
            if user_branches:
                cost_centers = self.repo.get_cost_centers_by_company_branch(context.company_id, user_branches[0])

        return [CostCenterOut.model_validate(cc) for cc in cost_centers]

    def get_active_cost_centers(self, context: AffiliationContext, branch_id: Optional[int] = None) -> list[
        CostCenterOut]:
        """Get active cost centers for the current company/branch"""
        target_branch_id = branch_id or getattr(context, "branch_id", None)

        ensure_scope_by_ids(
            context=context,
            target_company_id=context.company_id,
            target_branch_id=target_branch_id
        )

        if not target_branch_id:
            raise BizValidationError("Branch context is required.")

        cost_centers = self.repo.get_active_cost_centers(context.company_id, target_branch_id)
        return [CostCenterOut.model_validate(cc) for cc in cost_centers]