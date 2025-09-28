# app/application_sales/services/quotation_service.py

from __future__ import annotations
import logging
from typing import Optional, List, Dict
from decimal import Decimal

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest
import app.business_validation.item_validation as V
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum
from app.application_sales.models import SalesQuotation, SalesQuotationItem
from app.application_sales.schemas import SalesQuotationCreate, SalesQuotationUpdate
from app.application_sales.repository.quotation_repo import SalesQuotationRepository
from app.application_buying.repository.receipt_repo import PurchaseReceiptRepository


class SalesQuotationService:
    """Service layer for managing Sales Quotations."""
    PREFIX = "SQUO"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = SalesQuotationRepository(self.s)
        self.common_repo = PurchaseReceiptRepository(self.s)

    def _get_validated_quotation(
        self, quotation_id: int, context: AffiliationContext, for_update: bool = False
    ) -> SalesQuotation:
        sq = self.repo.get_by_id(quotation_id, for_update=for_update)
        if not sq:
            raise NotFound("Sales Quotation not found.")
        ensure_scope_by_ids(context=context, target_company_id=sq.company_id, target_branch_id=sq.branch_id)
        return sq

    def _generate_or_validate_code(self, company_id: int, branch_id: int, manual_code: Optional[str]) -> str:
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code)
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_lines(self, company_id: int, lines: List[Dict]) -> List[Dict]:
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")
        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.common_repo.get_item_details_batch(company_id, item_ids)
        normalized = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in normalized])
        uom_ids = [ln["uom_id"] for ln in normalized if ln.get("uom_id")]
        if uom_ids:
            existing_uoms = self.common_repo.get_existing_uom_ids(company_id, uom_ids)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids])
        pairs = [(ln["item_id"], ln["uom_id"]) for ln in normalized if ln.get("uom_id")]
        compat = self.common_repo.get_compatible_uom_pairs(company_id, pairs)
        for ln in normalized:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compat
        V.validate_item_uom_compatibility(normalized)
        for ln in normalized:
            V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln["rate"])
        return normalized

    def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
        return sum(Decimal(str(ln["quantity"])) * Decimal(str(ln["rate"])) for ln in lines)

    def create_sales_quotation(self, *, payload: SalesQuotationCreate, context: AffiliationContext) -> SalesQuotation:
        lines_data = [ln.model_dump() for ln in payload.items]
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.common_repo.get_branch_company_id,
            require_branch=True,
        )
        valid_customers = self.common_repo.get_valid_customer_ids(company_id, [payload.customer_id])
        V.validate_customer_is_active(payload.customer_id in valid_customers)
        self._validate_lines(company_id, lines_data)
        try:
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(lines_data)
            sq = SalesQuotation(
                company_id=company_id, branch_id=branch_id, created_by_id=context.user_id,
                customer_id=payload.customer_id, code=code, posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT, total_amount=total_amount, remarks=payload.remarks,
                items=[SalesQuotationItem(**ln) for ln in lines_data],
            )
            self.repo.save(sq)
            self.s.commit()
            return sq
        except Exception:
            self.s.rollback()
            raise

    def update_sales_quotation(self, *, quotation_id: int, payload: SalesQuotationUpdate, context: AffiliationContext) -> SalesQuotation:
        try:
            sq = self._get_validated_quotation(quotation_id, context, for_update=True)
            V.guard_updatable_state(sq.doc_status)
            if payload.posting_date: sq.posting_date = payload.posting_date
            if payload.customer_id:
                valid_customers = self.common_repo.get_valid_customer_ids(sq.company_id, [payload.customer_id])
                V.validate_customer_is_active(payload.customer_id in valid_customers)
                sq.customer_id = payload.customer_id
            if payload.remarks is not None: sq.remarks = payload.remarks
            if payload.items is not None:
                lines_data = [ln.model_dump(exclude_unset=True) for ln in payload.items]
                self._validate_lines(sq.company_id, lines_data)
                self.repo.sync_lines(sq, lines_data)
                sq.total_amount = self._calculate_total_amount(lines_data)
            self.repo.save(sq)
            self.s.commit()
            return sq
        except Exception:
            self.s.rollback()
            raise

    def submit_sales_quotation(self, *, quotation_id: int, context: AffiliationContext) -> SalesQuotation:
        try:
            sq = self._get_validated_quotation(quotation_id, context, for_update=True)
            V.guard_submittable_state(sq.doc_status)
            V.validate_list_not_empty(sq.items, "items for submission")
            sq.doc_status = DocStatusEnum.SUBMITTED
            self.repo.save(sq)
            self.s.commit()
            return sq
        except Exception:
            self.s.rollback()
            raise

    def cancel_sales_quotation(self, *, quotation_id: int, context: AffiliationContext) -> SalesQuotation:
        try:
            sq = self._get_validated_quotation(quotation_id, context, for_update=True)
            V.guard_cancellable_state(sq.doc_status)
            sq.doc_status = DocStatusEnum.CANCELLED
            self.repo.save(sq)
            self.s.commit()
            return sq
        except Exception:
            self.s.rollback()
            raise