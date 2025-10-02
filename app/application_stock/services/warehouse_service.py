from __future__ import annotations

import logging
from typing import Optional
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, BadRequest, Forbidden

from config.database import db
from app.application_stock.stock_models import Warehouse
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_stock.repo.warehouse_repo import WarehouseRepository
from app.application_stock.schemas.warehouse_schemas import WarehouseCreate, WarehouseUpdate
from app.application_stock.helpers.warehouse_validation import (
    WarehouseRuleError,
    validate_company_root_absent,
    validate_branch_group_absent,
    validate_unique_name_in_branch,
    validate_unique_code_global,
    validate_leaf_requires_branch_and_parent,
    validate_branch_consistency_with_parent,
    validate_parent_is_group,
    validate_no_child_warehouses,
    validate_empty_stock_before_delete,
    validate_not_self_parent,
)

from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.common.cache.cache_invalidator import (
    bump_list_cache_company,
    bump_list_cache_branch,
    bump_detail, bump_stock_dropdowns,
    # bump_list_cache_with_context,  # keep handy if your list read uses extra params
)
log = logging.getLogger(__name__)
WH_PREFIX = "WH"
GLOBAL_STOCK_ROLES = {"Super Admin", "Operations Manager", "Stock Manager"}

class WarehouseService:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = WarehouseRepository(self.s)

    # ---------- helpers ----------
    def _is_global_actor(self, ctx: AffiliationContext) -> bool:
        roles = set(getattr(ctx, "roles", []) or [])
        return bool(GLOBAL_STOCK_ROLES.intersection(roles))

    def _resolve_company_branch(self, payload: WarehouseCreate, ctx: AffiliationContext) -> tuple[int, Optional[int]]:
        company_id = payload.company_id or getattr(ctx, "company_id", None)
        if not company_id:
            raise BadRequest("Company context is required.")

        # For leaves/branch-groups we may need a branch; for root we must keep it None.
        branch_id = payload.branch_id
        return company_id, branch_id
    def _ensure_branch_scope(self, *, context: AffiliationContext, branch_id: int) -> int:
        """Load branch → return its company_id and ensure user has scope to that (company, branch)."""
        b_company_id = self.repo.get_branch_company_id(branch_id)
        if b_company_id is None:
            raise NotFound("Branch not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=b_company_id,
            target_branch_id=branch_id,
        )
        return b_company_id
    def _ensure_scope(self, ctx: AffiliationContext, company_id: int, branch_id: Optional[int]) -> None:
        ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=branch_id)

    def _gen_or_validate_code(self, company_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            # global uniqueness column exists; do a friendly pre-check anyway
            validate_unique_code_global(self.repo.code_exists_global(code))
            # company-scoped counter (branch_id=None for WH series)
            ensure_manual_code_is_next_and_bump(prefix=WH_PREFIX, company_id=company_id, branch_id=None, code=code)
            return code
        return generate_next_code(prefix=WH_PREFIX, company_id=company_id, branch_id=None)

    # ---------- create ----------
    def create_warehouse(self, *, payload: WarehouseCreate, context: AffiliationContext) -> Warehouse:
        company_id, branch_id = self._resolve_company_branch(payload, context)

        # scope: root requires global actor; others require branch/company scope
        if payload.is_group and payload.parent_warehouse_id is None and branch_id is None:
            if not self._is_global_actor(context):
                raise Forbidden("Only global roles can create a company root warehouse.")
            ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)
        else:
            if branch_id is not None:
                # Canonicalize: get the branch’s real company_id and scope-check that pair
                b_company_id = self._ensure_branch_scope(context=context, branch_id=branch_id)

                # If a company_id was sent in payload, it must match the branch's company
                if payload.company_id is not None and payload.company_id != b_company_id:
                    raise Forbidden("Out of scope. Branch does not belong to the target company.")

                # From here on, company_id must be the branch’s actual company
                company_id = b_company_id
            else:
                # No branch in payload (e.g., leaf should never be here; branch-group must have a branch)
                ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=None)

        # Validate parent if provided
        pinfo = None
        if payload.parent_warehouse_id is not None:
            pinfo = self.repo.parent_info(payload.parent_warehouse_id)
            if not pinfo:
                raise NotFound("Parent warehouse not found.")
            p_company_id, p_branch_id, p_is_group = pinfo
            if p_company_id != company_id:
                raise WarehouseRuleError("Parent/child company mismatch.", field="company_id")

        # classify
        is_root   = payload.is_group and payload.parent_warehouse_id is None and branch_id is None
        is_bgroup = payload.is_group and payload.parent_warehouse_id is not None and branch_id is not None
        is_leaf   = (not payload.is_group)

        # Structural validations
        if is_root:
            validate_company_root_absent(self.repo.company_root_exists(company_id))

        elif is_bgroup:
            # parent must be the company root (group, same company, branch None)
            if not pinfo:
                raise WarehouseRuleError("Parent must be provided for a branch group.", field="parent_warehouse_id")
            _, p_branch_id, p_is_group = pinfo
            if not p_is_group or p_branch_id is not None:
                raise WarehouseRuleError("Parent must be the company root.", field="parent_warehouse_id")
            validate_branch_group_absent(self.repo.branch_group_exists(company_id, branch_id))  # type: ignore[arg-type]

        elif is_leaf:
            # leaf requires branch + parent; parent must be group with same branch
            validate_leaf_requires_branch_and_parent(False, branch_id, payload.parent_warehouse_id)
            if not pinfo:
                raise WarehouseRuleError("Parent must be provided for a physical warehouse.", field="parent_warehouse_id")
            _, p_branch_id, p_is_group = pinfo
            validate_parent_is_group(payload.parent_warehouse_id, p_is_group)
            validate_branch_consistency_with_parent(False, p_branch_id, branch_id)

        else:
            raise WarehouseRuleError("Invalid warehouse shape. Check is_group/branch/parent constraints.")

        # business uniqueness
        validate_unique_code_global(self.repo.code_exists_global(payload.code) if payload.code else False)
        validate_unique_name_in_branch(self.repo.name_exists_in_branch(company_id, branch_id, payload.name))

        # generate/validate code
        code = self._gen_or_validate_code(company_id, payload.code)

        # persist
        wh = Warehouse(
            code=code,
            company_id=company_id,
            branch_id=branch_id,
            parent_warehouse_id=payload.parent_warehouse_id,
            is_group=payload.is_group,
            name=payload.name.strip(),
            description=payload.description,
            status=StatusEnum.ACTIVE,
        )
        self.repo.create(wh)
        self.s.commit()
        # -------------- CACHE BUMPS (best-effort) --------------
        try:
            # Your warehouses list logs show scope=COMPANY
            bump_list_cache_company("stock", "warehouses", company_id)

            # If the UI also shows a branch-filtered list anywhere, bump branch scope too
            if branch_id is not None:
                bump_list_cache_branch("stock", "warehouses", company_id, int(branch_id))
            bump_stock_dropdowns("stock", "warehouses", company_id)
            # If your list read path keys the cache with params/context, mirror it:
            # bump_list_cache_with_context("stock", "warehouses", context, params={})
        except Exception:
            log.exception("[cache] failed to bump warehouses list cache after create")

        return wh

    # ---------- update ----------
    def update_warehouse(self, *, warehouse_id: int, payload: WarehouseUpdate, context: AffiliationContext) -> Warehouse:
        wh = self.repo.get_by_id(warehouse_id, for_update=True)
        if not wh:
            raise NotFound("Warehouse not found.")


        # Scope strictly to the actual persisted company/branch
        if wh.branch_id is not None:
            # Canonical scope check via branch
            self._ensure_branch_scope(context=context, branch_id=wh.branch_id)
        else:
            ensure_scope_by_ids(context=context, target_company_id=wh.company_id, target_branch_id=None)

        # Immutable fields: code/company/branch/is_group
        if payload.status is not None:
            wh.status = payload.status
        if payload.name is not None and payload.name.strip() and payload.name.strip() != wh.name:
            validate_unique_name_in_branch(self.repo.name_exists_in_branch(wh.company_id, wh.branch_id, payload.name, exclude_id=wh.id))
            wh.name = payload.name.strip()
        if payload.description is not None:
            wh.description = payload.description

        # Reparent (optional)
        if payload.parent_warehouse_id is not None and payload.parent_warehouse_id != wh.parent_warehouse_id:
            validate_not_self_parent(wh.id, payload.parent_warehouse_id)
            pinfo = self.repo.parent_info(payload.parent_warehouse_id)
            if not pinfo:
                raise NotFound("New parent warehouse not found.")
            p_company_id, p_branch_id, p_is_group = pinfo
            if p_company_id != wh.company_id:
                raise WarehouseRuleError("Parent/child company mismatch.", field="company_id")

            if wh.is_group:
                # Branch group must have parent = company root
                if p_is_group is False or p_branch_id is not None:
                    raise WarehouseRuleError("Parent must be the company root.", field="parent_warehouse_id")
            else:
                # Leaf: parent must be a group with SAME branch
                validate_parent_is_group(payload.parent_warehouse_id, p_is_group)
                validate_branch_consistency_with_parent(False, p_branch_id, wh.branch_id)

            wh.parent_warehouse_id = payload.parent_warehouse_id

        self.repo.save(wh)
        self.s.commit()
        # -------------- CACHE BUMPS (best-effort) --------------
        try:
            # Invalidate the detail view (if you cache docdetail)
            bump_detail("stock", "warehouses", wh.id)
            bump_stock_dropdowns("stock", "warehouses", wh.company_id)
            # And the list page(s)
            bump_list_cache_company("stock", "warehouses", wh.company_id)
            if wh.branch_id is not None:
                bump_list_cache_branch("stock", "warehouses", wh.company_id, int(wh.branch_id))

        except Exception:
            log.exception("[cache] failed to bump warehouses caches after update")

        return wh

    # ---------- delete ----------
    def delete_warehouse(self, *, warehouse_id: int, context: AffiliationContext) -> None:
        wh = self.repo.get_by_id(warehouse_id, for_update=True)
        if not wh:
            raise NotFound("Warehouse not found.")
        self._ensure_scope(context, wh.company_id, wh.branch_id)

        # Cannot delete if has children
        validate_no_child_warehouses(self.repo.has_children(warehouse_id))

        # Optional: block if stock exists (if Bin model available)
        try:
            qty = self.repo.sum_stock_qty(wh.company_id, warehouse_id)  # may return None
            validate_empty_stock_before_delete(qty)
        except Exception:
            # If Bin table not wired yet, skip stock guard.
            pass

        self.repo.delete(wh)
        self.s.commit()
        # -------------- CACHE BUMPS (best-effort) --------------
        try:
            bump_list_cache_company("stock", "warehouses", wh.company_id)
            if wh.branch_id is not None:
                bump_list_cache_branch("stock", "warehouses", wh.company_id, int(wh.branch_id))

            # If you cache docdetail, bump its version so stale details disappear immediately
            bump_detail("stock", "warehouses", warehouse_id)
            bump_stock_dropdowns("stock", "warehouses", wh.company_id)
        except Exception:
            log.exception("[cache] failed to bump warehouses caches after delete")

