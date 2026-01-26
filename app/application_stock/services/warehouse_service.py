from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Set

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, BadRequest

from app.application_stock.helpers.warehouse_validation import (
    WarehouseRuleError,
    validate_company_root_absent,
    validate_unique_name_in_branch,
    validate_unique_code_global,
    validate_parent_is_group,
    validate_branch_consistency_with_parent,
    validate_no_child_warehouses,
    validate_empty_stock_before_delete,
    validate_not_self_parent,
    validate_not_company_root,
    validate_not_linked_to_document,
    validate_branch_required_for_leaf,
)
from config.database import db
from app.application_stock.stock_models import Warehouse
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_stock.repo.warehouse_repo import WarehouseRepository
from app.application_stock.schemas.warehouse_schemas import WarehouseCreate, WarehouseUpdate

from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)

from app.common.cache.cache_invalidator import (
    bump_list_cache_company,
    bump_list_cache_branch,
    bump_detail,
    bump_stock_dropdowns,
)

log = logging.getLogger(__name__)
WH_PREFIX = "WH"


class WarehouseService:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = WarehouseRepository(self.s)

    # ---------------------------------------------------------------------
    # Scope + canonical company/branch
    # ---------------------------------------------------------------------
    def _ensure_scope(self, *, ctx: AffiliationContext, company_id: int, branch_id: Optional[int]) -> None:
        ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=branch_id)

    def _canonicalize_company_branch(
        self,
        *,
        ctx: AffiliationContext,
        payload_company_id: Optional[int],
        payload_branch_id: Optional[int],
    ) -> tuple[int, Optional[int]]:
        if payload_branch_id is not None:
            b_company_id = self.repo.get_branch_company_id(payload_branch_id)
            if b_company_id is None:
                raise NotFound("Branch not found.")
            if payload_company_id is not None and payload_company_id != b_company_id:
                raise WarehouseRuleError("Branch does not belong to the target company.", field="branch_id")
            self._ensure_scope(ctx=ctx, company_id=b_company_id, branch_id=payload_branch_id)
            return b_company_id, payload_branch_id

        company_id = payload_company_id or getattr(ctx, "company_id", None)
        if not company_id:
            raise BadRequest("Company context is required.")
        self._ensure_scope(ctx=ctx, company_id=company_id, branch_id=None)
        return company_id, None

    # ---------------------------------------------------------------------
    # Code
    # ---------------------------------------------------------------------
    def _gen_or_validate_code(self, *, company_id: int, manual: Optional[str]) -> str:
        if manual:
            code = manual.strip()
            # DB constraint is per-company now
            validate_unique_code_global(self.repo.code_exists_in_company(company_id=company_id, code=code))
            ensure_manual_code_is_next_and_bump(prefix=WH_PREFIX, company_id=company_id, branch_id=None, code=code)
            return code

        # auto code (tiny collision loop, almost never runs more than once)
        for _ in range(5):
            code = generate_next_code(prefix=WH_PREFIX, company_id=company_id, branch_id=None)
            if not self.repo.code_exists_in_company(company_id=company_id, code=code):
                return code

        raise WarehouseRuleError("Failed to generate a unique warehouse code. Please retry.")

    # ---------------------------------------------------------------------
    # Root ("All Warehouses")
    # ---------------------------------------------------------------------
    def _ensure_company_root(self, *, company_id: int) -> Warehouse:
        root = self.repo.get_company_root(company_id)
        if root:
            return root

        # Friendly guard (DB also enforces uniqueness)
        validate_company_root_absent(self.repo.company_root_exists(company_id))

        code = self._gen_or_validate_code(company_id=company_id, manual=None)
        root = Warehouse(
            code=code,
            company_id=company_id,
            branch_id=None,
            parent_warehouse_id=None,
            is_group=True,
            name="All Warehouses",
            description=None,
            status=StatusEnum.ACTIVE,
        )
        self.repo.create(root)
        return root

    # ---------------------------------------------------------------------
    # CREATE
    # ---------------------------------------------------------------------
    def create_warehouse(self, *, payload: WarehouseCreate, context: AffiliationContext) -> Warehouse:
        company_id, branch_id = self._canonicalize_company_branch(
            ctx=context,
            payload_company_id=payload.company_id,
            payload_branch_id=payload.branch_id,
        )

        # IMPORTANT: default group=True so creating a top/group node is easy.
        is_group = bool(payload.is_group) if payload.is_group is not None else True
        parent_id = payload.parent_warehouse_id

        validate_branch_required_for_leaf(is_group=is_group, branch_id=branch_id)

        # ERP default: if parent not provided -> attach to company root
        if parent_id is None:
            root = self._ensure_company_root(company_id=company_id)
            parent_id = int(root.id)

        pinfo = self.repo.parent_info(parent_id)
        if not pinfo:
            raise NotFound("Parent warehouse not found.")
        p_company_id, p_branch_id, p_is_group = pinfo

        if p_company_id != company_id:
            raise WarehouseRuleError("Parent/child company mismatch.", field="company_id")

        validate_parent_is_group(parent_id, p_is_group)
        validate_branch_consistency_with_parent(
            is_group=is_group,
            parent_branch_id=p_branch_id,
            child_branch_id=branch_id,
        )

        validate_unique_name_in_branch(self.repo.name_exists_in_branch(company_id, branch_id, payload.name))

        if payload.code:
            validate_unique_code_global(
                self.repo.code_exists_in_company(company_id=company_id, code=payload.code)
            )

        code = self._gen_or_validate_code(company_id=company_id, manual=payload.code)

        wh = Warehouse(
            code=code,
            company_id=company_id,
            branch_id=branch_id,
            parent_warehouse_id=parent_id,
            is_group=is_group,
            name=payload.name.strip(),
            description=payload.description,
            status=StatusEnum.ACTIVE,
        )

        try:
            self.repo.create(wh)
            self.s.commit()
        except IntegrityError as ex:
            self.s.rollback()
            # Keep message simple to user, but log the real DB reason for you
            log.exception("Warehouse create failed (IntegrityError). orig=%r", getattr(ex, "orig", None))
            raise WarehouseRuleError("Invalid warehouse data. Please check branch/parent/group fields.") from None

        return wh

    # ---------------------------------------------------------------------
    # UPDATE
    # ---------------------------------------------------------------------
    def update_warehouse(self, *, warehouse_id: int, payload: WarehouseUpdate, context: AffiliationContext) -> Warehouse:
        wh = self.repo.get_by_id(warehouse_id, for_update=True)
        if not wh:
            raise NotFound("Warehouse not found.")

        self._ensure_scope(ctx=context, company_id=wh.company_id, branch_id=wh.branch_id)

        if payload.status is not None:
            wh.status = payload.status

        if payload.name is not None and payload.name.strip() and payload.name.strip() != wh.name:
            validate_unique_name_in_branch(
                self.repo.name_exists_in_branch(wh.company_id, wh.branch_id, payload.name, exclude_id=wh.id)
            )
            wh.name = payload.name.strip()

        if payload.description is not None:
            wh.description = payload.description

        if "parent_warehouse_id" in payload.model_fields_set:
            new_parent_id = payload.parent_warehouse_id
            if new_parent_id is None:
                raise BadRequest("parent_warehouse_id cannot be null. To move to root, set it to the root warehouse id.")

            if new_parent_id != wh.parent_warehouse_id:
                validate_not_self_parent(wh.id, new_parent_id)

                pinfo = self.repo.parent_info(new_parent_id)
                if not pinfo:
                    raise NotFound("New parent warehouse not found.")
                p_company_id, p_branch_id, p_is_group = pinfo

                if p_company_id != wh.company_id:
                    raise WarehouseRuleError("Parent/child company mismatch.", field="company_id")

                validate_parent_is_group(new_parent_id, p_is_group)

                validate_branch_consistency_with_parent(
                    is_group=wh.is_group,
                    parent_branch_id=p_branch_id,
                    child_branch_id=wh.branch_id,
                )

                wh.parent_warehouse_id = new_parent_id

        self.repo.save(wh)
        self.s.commit()

        try:
            bump_detail("stock", "warehouses", wh.id)
            bump_stock_dropdowns("stock", "warehouses", wh.company_id)
            bump_list_cache_company("stock", "warehouses", wh.company_id)
            if wh.branch_id is not None:
                bump_list_cache_branch("stock", "warehouses", wh.company_id, int(wh.branch_id))
        except Exception:
            log.exception("[cache] failed to bump warehouses caches after update")

        return wh

    # ---------------------------------------------------------------------
    # DELETE (single)
    # ---------------------------------------------------------------------
    def delete_warehouse(self, *, warehouse_id: int, context: AffiliationContext) -> None:
        wh = self.repo.get_by_id(warehouse_id, for_update=True)
        if not wh:
            raise NotFound("Warehouse not found.")

        self._ensure_scope(ctx=context, company_id=wh.company_id, branch_id=wh.branch_id)

        # Block deleting company root
        is_root = bool(wh.is_group) and wh.branch_id is None and wh.parent_warehouse_id is None
        validate_not_company_root(is_root)

        validate_no_child_warehouses(self.repo.has_children(warehouse_id))

        link = self.repo.find_first_linked_document(company_id=wh.company_id, warehouse_id=warehouse_id)
        validate_not_linked_to_document(link)

        try:
            qty = self.repo.sum_stock_qty(wh.company_id, warehouse_id)
            validate_empty_stock_before_delete(qty)
        except Exception:
            pass

        self.repo.delete(wh)
        self.s.commit()

        try:
            bump_list_cache_company("stock", "warehouses", wh.company_id)
            if wh.branch_id is not None:
                bump_list_cache_branch("stock", "warehouses", wh.company_id, int(wh.branch_id))
            bump_detail("stock", "warehouses", warehouse_id)
            bump_stock_dropdowns("stock", "warehouses", wh.company_id)
        except Exception:
            log.exception("[cache] failed to bump warehouses caches after delete")

    # ---------------------------------------------------------------------
    # DELETE (bulk) - partial success using savepoints
    # ---------------------------------------------------------------------
    def delete_warehouses_bulk(self, *, warehouse_ids: List[int], context: AffiliationContext) -> Dict[str, Any]:
        deleted: List[int] = []
        blocked: List[Dict[str, Any]] = []
        touched_companies: Set[int] = set()
        touched_branches: Set[tuple[int, int]] = set()

        for wid in warehouse_ids:
            with self.s.begin_nested():  # SAVEPOINT
                try:
                    wh = self.repo.get_by_id(wid, for_update=True)
                    if not wh:
                        raise NotFound("Warehouse not found.")

                    self._ensure_scope(ctx=context, company_id=wh.company_id, branch_id=wh.branch_id)

                    is_root = bool(wh.is_group) and wh.branch_id is None and wh.parent_warehouse_id is None
                    validate_not_company_root(is_root)

                    validate_no_child_warehouses(self.repo.has_children(wid))

                    link = self.repo.find_first_linked_document(company_id=wh.company_id, warehouse_id=wid)
                    validate_not_linked_to_document(link)

                    try:
                        qty = self.repo.sum_stock_qty(wh.company_id, wid)
                        validate_empty_stock_before_delete(qty)
                    except Exception:
                        pass

                    self.repo.delete(wh)

                    deleted.append(wid)
                    touched_companies.add(int(wh.company_id))
                    if wh.branch_id is not None:
                        touched_branches.add((int(wh.company_id), int(wh.branch_id)))

                except Exception as ex:
                    blocked.append({"id": wid, "reason": str(ex)})

        self.s.commit()

        try:
            for cid in touched_companies:
                bump_list_cache_company("stock", "warehouses", cid)
                bump_stock_dropdowns("stock", "warehouses", cid)
            for cid, bid in touched_branches:
                bump_list_cache_branch("stock", "warehouses", cid, bid)
            for wid in deleted:
                bump_detail("stock", "warehouses", wid)
        except Exception:
            log.exception("[cache] failed to bump warehouses caches after bulk delete")

        return {"deleted": deleted, "blocked": blocked}
