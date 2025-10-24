from __future__ import annotations
import logging
from typing import Optional

from app.business_validation.item_validation import BizValidationError

log = logging.getLogger(__name__)

# User-friendly error messages
ERR_COST_CENTER_NAME_EXISTS = "Cost center with this name already exists"
ERR_COST_CENTER_NOT_FOUND = "Cost center not found"
ERR_INVALID_STATUS_CHANGE = "Invalid cost center status change"


class CostCenterValidator:
    """Cost Center specific business validators"""

    @staticmethod
    def validate_name_uniqueness(repo, company_id: int, branch_id: int, name: str,
                                 exclude_id: Optional[int] = None) -> None:
        """Validate that cost center name is unique within company and branch"""
        existing = repo.get_cost_center_by_name(company_id, branch_id, name)
        if existing and (exclude_id is None or existing.id != exclude_id):
            raise BizValidationError(ERR_COST_CENTER_NAME_EXISTS)

    @staticmethod
    def validate_status_transition(current_status: str, new_status: str) -> None:
        """Validate cost center status transitions"""
        # Allow any status transition for now, but we can add restrictions if needed
        valid_statuses = ['Draft', 'Active', 'Inactive']
        if new_status not in valid_statuses:
            raise BizValidationError(f"Invalid status: {new_status}")