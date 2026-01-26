from __future__ import annotations

import logging
import re
import secrets
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_nventory.inventory_models import ItemGroup
from app.application_nventory.repo.item_group_repo import ItemGroupRepository

from app.business_validation.item_validation import BizValidationError
from app.business_validation.item_group_validation import (
    validate_item_group_name,
    validate_accounts_all_belong,
    ERR_IG_NOT_FOUND,
    ERR_IG_CODE_EXISTS,
    ERR_IG_PARENT_INVALID,
    ERR_IG_PARENT_NOT_GROUP,
    ERR_IG_CYCLE,
    ERR_IG_HAS_CHILD_GROUPS,
)

log = logging.getLogger(__name__)


def _sanitize_group_code(raw: str, max_len: int = 50) -> str:
    """Clean and format item group code."""
    if not raw:
        return ""
    s = (raw or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] if s else ""


def _initials(name: str, max_letters: int = 3) -> str:
    """Extract initials from name for code generation."""
    if not name:
        return "GRP"

    name = name.strip()
    words = [w for w in re.split(r"\s+", name) if w]
    letters = "".join(w[0] for w in words[:max_letters])
    if not letters:
        letters = re.sub(r"[^A-Za-z0-9]+", "", name)[:max_letters]
    return letters.upper() or "GRP"


def _random_tail(n_bytes: int = 2) -> str:
    """Generate random suffix for uniqueness."""
    return secrets.token_hex(n_bytes).upper()


def _generate_item_group_code(name: str) -> str:
    """Auto-generate item group code from name."""
    initials = _initials(name, max_letters=3)
    tail = _random_tail(2)
    code = _sanitize_group_code(f"GRP_{initials}_{tail}")
    log.info("Generated item group code: name='%s', initials=%s, tail=%s, final_code=%s",
             name, initials, tail, code)
    return code


class ItemGroupService:
    """Item Group service with proper error handling and transaction management."""

    def __init__(self, repo: Optional[ItemGroupRepository] = None, session: Optional[Session] = None):
        self.repo = repo or ItemGroupRepository(session or db.session)
        self.s: Session = self.repo.s

    # ---------------------------
    # Transaction Management
    # ---------------------------
    @property
    def _in_nested_tx(self) -> bool:
        """Check if we're inside a nested transaction."""
        try:
            transaction = getattr(self.s, "transaction", None)
            if not transaction:
                return False

            # Check for nested attribute
            if getattr(transaction, "nested", False):
                return True

            # Walk up parent chain
            parent = getattr(transaction, "parent", None)
            while parent:
                if getattr(parent, "nested", False):
                    return True
                parent = getattr(parent, "parent", None)

            return False
        except Exception:
            return False

    def _commit_or_flush(self) -> None:
        """Commit or flush based on transaction nesting."""
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        """Rollback only if we're at the top level transaction."""
        if not self._in_nested_tx:
            self.s.rollback()

    # ---------------------------
    # Root group getter/creator
    # ---------------------------
    def _get_or_create_root_id(self, *, company_id: int) -> int:
        """Get or create root item group for company."""
        try:
            company_id = int(company_id)
            rid = self.repo.get_root_item_group_id(company_id=company_id)
            if rid:
                return int(rid)

            root = self.repo.create_root_item_group(company_id=company_id)
            self._commit_or_flush()
            return int(root.id)
        except Exception as e:
            log.error("Failed to get/create root item group: %s", e)
            raise

    # ---------------------------
    # Code allocator with auto-generation
    # ---------------------------
    def _allocate_unique_code(self, *, company_id: int, name: str,
                              user_code: Optional[str] = None,
                              exclude_id: Optional[int] = None) -> str:
        """Allocate unique code, auto-generating if user doesn't provide."""
        company_id = int(company_id)

        # If user provided code, use it (sanitized)
        if user_code:
            code = _sanitize_group_code(user_code)
            if not code:
                raise BizValidationError("Item Group Code cannot be empty.")
        else:
            # Auto-generate code from name
            code = _generate_item_group_code(name)

        # Check if code exists
        if not self.repo.item_group_code_exists(
                company_id=company_id,
                code=code,
                exclude_id=exclude_id
        ):
            return code

        # If collision, add suffix
        for i in range(1, 100):
            cand = f"{code}-{i}"
            if not self.repo.item_group_code_exists(
                    company_id=company_id,
                    code=cand,
                    exclude_id=exclude_id
            ):
                return cand

        raise BizValidationError(ERR_IG_CODE_EXISTS)

    # ---------------------------
    # Validation helpers
    # ---------------------------
    def _validate_parent_and_accounts(self, *, company_id: int, parent_id: Optional[int],
                                      account_ids: list[int]) -> Tuple[Optional[bool], set[int]]:
        """Validate parent and accounts with proper error handling."""
        company_id = int(company_id)
        missing_accounts = set()
        parent_is_group = None

        # Validate parent if provided
        if parent_id:
            parent_is_group = self.repo.parent_is_group(
                company_id=company_id,
                parent_id=int(parent_id)
            )
            if parent_is_group is None:
                raise BizValidationError(ERR_IG_PARENT_INVALID)

        # Validate accounts if provided
        if account_ids:
            missing_accounts = self.repo.missing_account_ids(
                company_id=company_id,
                account_ids=account_ids
            )

        return parent_is_group, missing_accounts

    def _check_name_uniqueness(self, *, company_id: int, name: str, exclude_id: Optional[int] = None) -> None:
        """Check if item group name already exists in company."""
        if self.repo.item_group_name_exists(
                company_id=company_id,
                name=name,
                exclude_id=exclude_id
        ):
            raise BizValidationError("Item Group name already exists.")

    # -------------------------------------------------------------------------
    # CREATE - Simplified with only name required
    # -------------------------------------------------------------------------
    def create_item_group(self, *, payload, context: AffiliationContext) -> Tuple[bool, str, Optional[ItemGroup]]:
        """Create item group with proper error handling."""
        try:
            # Get company from user context
            company_id = context.company_id
            if not company_id:
                return False, "Company is required.", None

            company_id = int(company_id)

            # Check user has access to this company
            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None
            )

            # 1. Validate name (required)
            name = validate_item_group_name(getattr(payload, "name", None))

            # 2. Check name uniqueness
            self._check_name_uniqueness(company_id=company_id, name=name)

            # 3. Set defaults
            is_group = bool(getattr(payload, "is_group", True))  # Default to True like ERPNext

            # 4. Handle parent (default to root if not provided)
            parent_id = getattr(payload, "parent_item_group_id", None)
            if parent_id is None:
                parent_id = self._get_or_create_root_id(company_id=company_id)

            # 5. Collect account IDs for validation
            account_ids = [
                getattr(payload, "default_expense_account_id", None),
                getattr(payload, "default_income_account_id", None),
                getattr(payload, "default_inventory_account_id", None),
            ]
            valid_account_ids = [aid for aid in account_ids if aid is not None]

            # 6. Validate parent and accounts
            parent_is_group, missing_accounts = self._validate_parent_and_accounts(
                company_id=company_id,
                parent_id=parent_id,
                account_ids=valid_account_ids
            )

            if parent_is_group is not None and not parent_is_group:
                raise BizValidationError(ERR_IG_PARENT_NOT_GROUP)

            if missing_accounts:
                validate_accounts_all_belong(missing_ids=missing_accounts)

            # 7. Generate unique code
            user_code = getattr(payload, "code", None)
            code = self._allocate_unique_code(
                company_id=company_id,
                name=name,
                user_code=user_code,
                exclude_id=None
            )

            # 8. Create item group
            ig = ItemGroup(
                company_id=company_id,
                parent_item_group_id=int(parent_id) if parent_id else None,
                name=name,
                code=code,
                is_group=is_group,
                default_expense_account_id=getattr(payload, "default_expense_account_id", None),
                default_income_account_id=getattr(payload, "default_income_account_id", None),
                default_inventory_account_id=getattr(payload, "default_inventory_account_id", None),
            )

            self.repo.save(ig)
            self._commit_or_flush()

            # Invalidate cache if needed
            try:
                from app.common.cache.cache_invalidator import bump_list_cache_company, bump_inventory_dropdowns
                bump_list_cache_company("inventory", "item_groups", company_id)
                bump_inventory_dropdowns("inventory", "item_groups", company_id)
            except Exception:
                log.warning("Cache invalidation failed for item group creation")

            return True, "Item Group created successfully.", ig

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_IG_CODE_EXISTS, None
        except Exception as e:
            log.exception("create_item_group failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Item Group.", None

    # -------------------------------------------------------------------------
    # UPDATE
    # -------------------------------------------------------------------------
    def update_item_group(self, *, item_group_id: int, payload, context: AffiliationContext) -> Tuple[
        bool, str, Optional[ItemGroup]]:
        """Update item group with proper error handling."""
        try:
            # Get company from context
            company_id = context.company_id
            if not company_id:
                return False, "Company is required.", None

            company_id = int(company_id)

            # Check user has access to this company
            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None
            )

            # Get item group
            ig = self.repo.get_item_group_by_id(
                company_id=company_id,
                item_group_id=int(item_group_id)
            )
            if not ig:
                return False, ERR_IG_NOT_FOUND, None

            # Track updates
            updates_applied = False

            # 1. Update name if provided
            if getattr(payload, "name", None) is not None:
                new_name = validate_item_group_name(payload.name)

                # Check if name changed
                if new_name != ig.name:
                    # Check name uniqueness
                    self._check_name_uniqueness(
                        company_id=company_id,
                        name=new_name,
                        exclude_id=int(ig.id)
                    )
                    ig.name = new_name
                    updates_applied = True

            # 2. Update parent if provided
            if getattr(payload, "parent_item_group_id", None) is not None:
                new_parent = payload.parent_item_group_id

                # If null -> default to root
                if new_parent is None:
                    new_parent = self._get_or_create_root_id(company_id=company_id)

                if int(new_parent) == int(ig.id):
                    raise BizValidationError(ERR_IG_CYCLE)

                # Validate new parent
                parent_is_group = self.repo.parent_is_group(
                    company_id=company_id,
                    parent_id=int(new_parent)
                )
                if parent_is_group is None:
                    raise BizValidationError(ERR_IG_PARENT_INVALID)
                if not parent_is_group:
                    raise BizValidationError(ERR_IG_PARENT_NOT_GROUP)

                # Check for cycles
                if self.repo.would_create_cycle(
                        company_id=company_id,
                        group_id=int(ig.id),
                        new_parent_id=int(new_parent)
                ):
                    raise BizValidationError(ERR_IG_CYCLE)

                ig.parent_item_group_id = int(new_parent)
                updates_applied = True

            # 3. Update is_group if provided
            if getattr(payload, "is_group", None) is not None:
                new_is_group = bool(payload.is_group)
                if ig.is_group and not new_is_group:
                    # Cannot become leaf if has child groups
                    if self.repo.child_group_exists(
                            company_id=company_id,
                            parent_id=int(ig.id)
                    ):
                        raise BizValidationError(ERR_IG_HAS_CHILD_GROUPS)
                ig.is_group = new_is_group
                updates_applied = True

            # 4. Update code if provided
            if getattr(payload, "code", None) is not None:
                raw = payload.code
                if raw:
                    # User provided code
                    code = self._allocate_unique_code(
                        company_id=company_id,
                        name=ig.name,
                        user_code=raw,
                        exclude_id=int(ig.id)
                    )
                    ig.code = code
                    updates_applied = True

            # 5. Update accounts if provided
            account_fields = (
                "default_expense_account_id",
                "default_income_account_id",
                "default_inventory_account_id",
            )

            account_ids_to_validate = []

            for field in account_fields:
                if getattr(payload, field, None) is not None:
                    new_value = getattr(payload, field)
                    if new_value is not None:
                        account_ids_to_validate.append(int(new_value))
                    setattr(ig, field, new_value)
                    updates_applied = True

            # Validate new account IDs
            if account_ids_to_validate:
                missing = self.repo.missing_account_ids(
                    company_id=company_id,
                    account_ids=account_ids_to_validate
                )
                if missing:
                    validate_accounts_all_belong(missing_ids=missing)

            # Only save if updates were applied
            if updates_applied:
                self.repo.save(ig)
                self._commit_or_flush()

                # Invalidate cache if needed
                try:
                    from app.common.cache.cache_invalidator import bump_list_cache_company, bump_inventory_dropdowns
                    bump_list_cache_company("inventory", "item_groups", company_id)
                    bump_inventory_dropdowns("inventory", "item_groups", company_id)
                except Exception:
                    log.warning("Cache invalidation failed for item group update")

            return True, "Item Group updated successfully.", ig

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_IG_CODE_EXISTS, None
        except Exception as e:
            log.exception("update_item_group failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Item Group.", None