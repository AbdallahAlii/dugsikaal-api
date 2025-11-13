# # app/application_buying/receipt_serice.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
import logging
from datetime import datetime

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict

from config.database import db
from app.application_buying.schemas import (
    PurchaseReceiptCreate, PurchaseReceiptUpdate
)
from app.application_buying.repository.receipt_repo import PurchaseReceiptRepository
from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem
from app.application_stock.stock_models import DocStatusEnum, DocumentType, StockLedgerEntry
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.handlers.purchase import (
    build_intents_for_receipt, build_intents_for_return
)
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.bin_derive import derive_bin

from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation import item_validation as V

from app.security.rbac_guards import resolve_company_branch_and_scope, ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext
logger = logging.getLogger(__name__)

class PurchaseReceiptService:
    PREFIX = "PR"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseReceiptRepository(self.s)

    # util
    def _generate_or_validate_code(self, company_id: int, branch_id: int, code: Optional[str]) -> str:
        from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
        if code:
            c = code.strip()
            if self.repo.code_exists(company_id, branch_id, c):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=c)
            return c
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(self, company_id: int, branch_id: int, supplier_id: int, header_wh_id: Optional[int]) -> None:
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)
        if header_wh_id:
            valid_wh = self.repo.get_transactional_warehouse_ids(company_id, branch_id, [header_wh_id])
            V.validate_warehouse_is_transactional(header_wh_id in valid_wh)

    def _autofill_line_warehouse(self, header_wh_id: Optional[int], lines: List[Dict]) -> None:
        if not header_wh_id:
            return
        for ln in lines:
            if ln.get("warehouse_id") is None:
                ln["warehouse_id"] = header_wh_id

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict], is_return: bool) -> List[Dict]:
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")
        item_ids = [ln["item_id"] for ln in lines]
        details = self.repo.get_item_details_batch(company_id, item_ids)

        # add details and validate
        work = [{**ln, **details.get(ln["item_id"], {})} for ln in lines]
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in work])
        V.validate_no_service_items(work)
        V.validate_uom_present_for_stock_items(work)

        uoms = [ln["uom_id"] for ln in work if ln.get("uom_id")]
        if uoms:
            existing = self.repo.get_existing_uom_ids(company_id, uoms)
            V.validate_uoms_exist([(u, u in existing) for u in uoms])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in work if ln.get("uom_id")]
        compat = self.repo.get_compatible_uom_pairs(company_id, pairs)
        for ln in work:
            if ln.get("uom_id"):
                ln["uom_ok"] = (ln["item_id"], ln["uom_id"]) in compat
        V.validate_item_uom_compatibility(work)

        for ln in work:
            if is_return:
                # qty should be negative already, schema enforces; just sanity
                if Decimal(str(ln["accepted_qty"])) >= 0:
                    raise V.BizValidationError("Return lines must have negative qty.")
            else:
                if Decimal(str(ln["accepted_qty"])) <= 0:
                    raise V.BizValidationError("Receipt lines must have positive qty.")
            V.validate_accepted_quantity_logic(ln["received_qty"], ln["accepted_qty"])
            V.validate_positive_price(ln.get("unit_price"))

        # keep only model fields
        out = []
        for ln in work:
            out.append({
                "item_id": ln["item_id"],
                "uom_id": ln.get("uom_id"),
                "received_qty": ln["received_qty"],
                "accepted_qty": ln["accepted_qty"],
                "unit_price": ln.get("unit_price"),
                "remarks": ln.get("remarks"),
                "warehouse_id": ln.get("warehouse_id"),
                "return_against_item_id": ln.get("return_against_item_id"),
            })
        return out

    def _calculate_total(self, company_id: int, lines: List[Dict]) -> Decimal:
        from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
        total = Decimal("0")
        for ln in lines:
            if ln.get("unit_price") is None:
                continue
            price = Decimal(str(ln["unit_price"]))
            qty = Decimal(str(ln["accepted_qty"]))
            item_id = ln["item_id"]
            uom_id = ln.get("uom_id")
            detail = self.repo.get_item_details_batch(company_id, [item_id]).get(item_id, {})
            base_uom = detail.get("base_uom_id")
            if not base_uom or not uom_id or uom_id == base_uom:
                total += qty * price
            else:
                try:
                    base_qty_float, _ = to_base_qty(qty=abs(qty), item_id=item_id, uom_id=uom_id, base_uom_id=base_uom, strict=True)
                    base_qty = Decimal(str(base_qty_float))
                    if qty < 0:
                        base_qty = -base_qty
                    total += base_qty * price
                except UOMFactorMissing:
                    total += qty * price
        return total

    # public APIs
    def create_purchase_receipt(self, *, payload: PurchaseReceiptCreate, context: AffiliationContext) -> PurchaseReceipt:
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )
        PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, company_id)

        self._validate_header(company_id, branch_id, payload.supplier_id, payload.warehouse_id)

        lines = [ln.model_dump() for ln in payload.items]
        # auto-fill line warehouses from header if provided
        self._autofill_line_warehouse(payload.warehouse_id, lines)
        norm = self._validate_and_normalize_lines(company_id, lines, is_return=payload.is_return)

        code = self._generate_or_validate_code(company_id, branch_id, payload.code)
        total = self._calculate_total(company_id, norm)

        items = [PurchaseReceiptItem(**ln) for ln in norm]
        pr = PurchaseReceipt(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=context.user_id,
            supplier_id=payload.supplier_id,
            warehouse_id=payload.warehouse_id,
            code=code,
            posting_date=payload.posting_date,
            doc_status=DocStatusEnum.DRAFT,
            is_return=payload.is_return,
            return_against_id=payload.return_against_id,
            remarks=payload.remarks,
            total_amount=total,
            items=items,
        )
        self.repo.save(pr)
        self.s.commit()
        return pr
    def update_purchase_receipt(self, *, receipt_id: int, payload: PurchaseReceiptUpdate, context: AffiliationContext) -> PurchaseReceipt:
        pr = self.repo.get_by_id(receipt_id, for_update=True)
        if not pr:
            raise NotFound("Purchase Receipt not found.")
        ensure_scope_by_ids(context=context, target_company_id=pr.company_id, target_branch_id=pr.branch_id)

        # Only DRAFT updatable
        from app.business_validation.item_validation import guard_updatable_state
        guard_updatable_state(pr.doc_status)

        # Update header (nullable warehouse is ok; real enforcement happens at submit)
        if payload.posting_date is not None:
            from app.business_validation.posting_date_validation import PostingDateValidator
            PostingDateValidator.validate_standalone_document(self.s, payload.posting_date, pr.company_id)
            pr.posting_date = payload.posting_date

        if payload.supplier_id is not None and payload.supplier_id != pr.supplier_id:
            valid = self.repo.get_valid_supplier_ids(pr.company_id, [payload.supplier_id])
            from app.business_validation import item_validation as V
            V.validate_supplier_is_active(payload.supplier_id in valid)
            pr.supplier_id = payload.supplier_id

        if payload.warehouse_id is not None:
            # header warehouse is just a default; may be None
            if payload.warehouse_id:
                valid_wh = self.repo.get_transactional_warehouse_ids(pr.company_id, pr.branch_id, [payload.warehouse_id])
                from app.business_validation import item_validation as V
                V.validate_warehouse_is_transactional(payload.warehouse_id in valid_wh)
            pr.warehouse_id = payload.warehouse_id

        if payload.remarks is not None:
            pr.remarks = payload.remarks

        # Update lines if provided
        if payload.items is not None:
            lines_in = [it.model_dump() for it in payload.items]

            # Enforce directions based on pr.is_return
            from decimal import Decimal
            for ln in lines_in:
                if pr.is_return:
                    if Decimal(str(ln["accepted_qty"])) >= 0 or Decimal(str(ln["received_qty"])) >= 0:
                        raise ValueError("Return Receipt items must have negative quantities.")
                    if ln.get("return_against_item_id") is None:
                        raise ValueError("Return Receipt requires return_against_item_id on each item.")
                else:
                    if Decimal(str(ln["accepted_qty"])) <= 0 or Decimal(str(ln["received_qty"])) <= 0:
                        raise ValueError("Normal Receipt items must have positive quantities.")

            # Basic item/uom/price validations (same flavor as create, but lighter)
            from app.business_validation import item_validation as V
            V.validate_list_not_empty(lines_in, "items")
            V.validate_unique_items(lines_in, key="item_id")
            details = self.repo.get_item_details_batch(pr.company_id, [x["item_id"] for x in lines_in])
            V.validate_items_are_active([(x["item_id"], details.get(x["item_id"], {}).get("is_active", False)) for x in lines_in])
            for x in lines_in:
                V.validate_accepted_quantity_logic(x["received_qty"], x["accepted_qty"])
                V.validate_positive_price(x.get("unit_price"))

            self.repo.sync_lines(pr, lines_in)

        # Recalc totals
        self.repo.recalc_total(pr)
        self.s.commit()
        return pr

    def _doc_type_id(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt

    def _guard_submittable(self, pr: PurchaseReceipt) -> None:
        V.guard_submittable_state(pr.doc_status)
        if pr.is_return and not pr.return_against_id:
            raise V.BizValidationError("Return Receipt must reference original receipt.")

    def submit_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        logger.info("🔄 PR submit start | receipt_id=%s", receipt_id)

        pr = self.repo.get_by_id(receipt_id, for_update=False)
        if not pr:
            logger.error("❌ PR submit aborted: not found | receipt_id=%s", receipt_id)
            raise NotFound("Purchase Receipt not found.")
        ensure_scope_by_ids(context=context, target_company_id=pr.company_id, target_branch_id=pr.branch_id)

        PostingDateValidator.validate_standalone_document(self.s, pr.posting_date, pr.company_id)
        self._guard_submittable(pr)

        # Enforce per-line warehouse presence for stock movement at submit (fallback to header)
        for ln in pr.items:
            if ln.warehouse_id is None and pr.warehouse_id:
                ln.warehouse_id = pr.warehouse_id
            if ln.warehouse_id is None:
                logger.error("❌ PR line missing warehouse | receipt_id=%s line_id=%s item_id=%s",
                             receipt_id, getattr(ln, "id", None), getattr(ln, "item_id", None))
                raise V.BizValidationError("Warehouse is required on each stock line before submit.")

        # Build lines → intents
        item_ids = [i.item_id for i in pr.items]
        details = self.repo.get_item_details_batch(pr.company_id, item_ids)  # {item_id: {...}}
        lines = []
        for i in pr.items:
            base_uom = details.get(i.item_id, {}).get("base_uom_id")
            lines.append({
                "uom_id": i.uom_id,
                "item_id": i.item_id,
                "accepted_qty": i.accepted_qty,  # negative if return
                "unit_price": i.unit_price,
                "doc_row_id": i.id,
                "base_uom_id": base_uom,
                "warehouse_id": i.warehouse_id,  # per-line warehouse enforced above
            })

        doc_type_code = "PURCHASE_RETURN" if pr.is_return else "PURCHASE_RECEIPT"
        doc_type_id = self._doc_type_id(doc_type_code)
        posting_dt = resolve_posting_dt(pr.posting_date, created_at=pr.created_at, treat_midnight_as_date=True)
        logger.info("📅 PR posting_dt=%s | is_return=%s", posting_dt, pr.is_return)

        if pr.is_return:
            intents = build_intents_for_return(
                company_id=pr.company_id, branch_id=pr.branch_id, warehouse_id=pr.warehouse_id,
                # header used only as fallback
                posting_dt=posting_dt, doc_type_id=doc_type_id, doc_id=pr.id, lines=lines, session=self.s
            )
        else:
            intents = build_intents_for_receipt(
                company_id=pr.company_id, branch_id=pr.branch_id, warehouse_id=pr.warehouse_id,
                # header used only as fallback
                posting_dt=posting_dt, doc_type_id=doc_type_id, doc_id=pr.id, lines=lines, session=self.s
            )

        if not intents:
            logger.error("❌ PR submit aborted: no intents generated | receipt_id=%s", receipt_id)
            raise V.BizValidationError("No stock intents generated.")

        # Safety: ensure all intents have warehouse_id
        for idx, it in enumerate(intents):
            if it.warehouse_id is None:
                logger.error("❌ PR intent missing warehouse | idx=%s item_id=%s", idx, it.item_id)
                raise V.BizValidationError("Internal error: intent without warehouse. Please check warehouses/UOMs.")

        pairs = {(i.item_id, i.warehouse_id) for i in intents}

        # Backdated check
        def _future_exists(item_id: int, wh: int) -> bool:
            q = self.s.execute(
                select(func.count()).select_from(StockLedgerEntry).where(
                    StockLedgerEntry.company_id == pr.company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh,
                    ((StockLedgerEntry.posting_date > posting_dt.date()) | and_(
                        StockLedgerEntry.posting_date == posting_dt.date(),
                        StockLedgerEntry.posting_time > posting_dt,
                    )),
                    StockLedgerEntry.is_cancelled == False,
                )
            ).scalar() or 0
            return q > 0

        is_backdated = any(_future_exists(i, w) for (i, w) in pairs)
        if is_backdated:
            logger.warning("⚠️ PR is backdated; reposting will run after commit | receipt_id=%s", receipt_id)

        # ATOMIC write
        with self.s.begin_nested():
            pr_locked = self.repo.get_by_id(receipt_id, for_update=True)
            self._guard_submittable(pr_locked)

            sle_count = 0
            with lock_pairs(self.s, pairs):
                for idx, intent in enumerate(intents):
                    append_sle(self.s, intent, created_at_hint=pr_locked.created_at, tz_hint=None, batch_index=idx)
                    sle_count += 1
            if sle_count != len(intents):
                logger.error("❌ PR SLE append mismatch | expected=%s wrote=%s", len(intents), sle_count)
                raise RuntimeError("SLE append mismatch.")

            # GL (GRNI / Return GRNI)
            lines_for_gl = [{"accepted_qty": ln["accepted_qty"], "unit_price": ln["unit_price"]} for ln in lines]
            template = "PURCHASE_RETURN_GRNI" if pr_locked.is_return else "PURCHASE_RECEIPT_GRNI"
            stock_value = sum(
                abs(Decimal(str(x["accepted_qty"]))) * Decimal(str(x["unit_price"]))
                for x in lines_for_gl if x["unit_price"] is not None
            )

            PostingService(self.s).post(
                PostingContext(
                    company_id=pr_locked.company_id,
                    branch_id=pr_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=pr_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"{'Purchase Return' if pr_locked.is_return else 'Purchase Receipt'} {pr_locked.code}",
                    template_code=template,
                    payload={
                        ("RETURN_STOCK_VALUE" if pr_locked.is_return else "INVENTORY_PURCHASE_COST"): float(
                            stock_value),
                        "receipt_lines": lines_for_gl,
                        "is_return": pr_locked.is_return
                    },
                    runtime_accounts={},
                    party_id=pr_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                )
            )

            pr_locked.doc_status = DocStatusEnum.RETURNED if pr_locked.is_return else DocStatusEnum.SUBMITTED
            self.repo.save(pr_locked)

        self.s.commit()
        logger.info("💾 PR committed | receipt_id=%s", receipt_id)

        # Maintenance
        if is_backdated:
            with self.s.begin():
                for (item_id, wh_id) in pairs:
                    repost_from(self.s, pr.company_id, item_id, wh_id, posting_dt)
        else:
            with self.s.begin():
                for (item_id, wh_id) in pairs:
                    derive_bin(self.s, pr.company_id, item_id, wh_id)

        logger.info("🎉 PR submit done | %s", pr.code)
        return pr
    def cancel_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        logger.info("♻️ PR cancel start | receipt_id=%s", receipt_id)

        pr = self.repo.get_by_id(receipt_id, for_update=False)
        if not pr:
            logger.error("❌ PR cancel aborted: not found | receipt_id=%s", receipt_id)
            raise NotFound("Purchase Receipt not found.")
        ensure_scope_by_ids(context=context, target_company_id=pr.company_id, target_branch_id=pr.branch_id)
        V.guard_cancellable_state(pr.doc_status)

        dt_id = self._doc_type_id("PURCHASE_RETURN" if pr.is_return else "PURCHASE_RECEIPT")

        # Collect originals (ordered deterministically)
        rows = self.s.execute(
            select(StockLedgerEntry)
            .where(
                StockLedgerEntry.company_id == pr.company_id,
                StockLedgerEntry.doc_type_id == dt_id,
                StockLedgerEntry.source_doc_id == pr.id if hasattr(StockLedgerEntry, "source_doc_id") else StockLedgerEntry.doc_id == pr.id,
                StockLedgerEntry.is_cancelled == False,
                StockLedgerEntry.is_reversal == False,
            )
            .order_by(StockLedgerEntry.posting_date.asc(), StockLedgerEntry.posting_time.asc(), StockLedgerEntry.id.asc())
        ).scalars().all()

        pairs = {(r.item_id, r.warehouse_id) for r in rows}
        start_dt = min((r.posting_time for r in rows), default=resolve_posting_dt(pr.posting_date, created_at=pr.created_at, treat_midnight_as_date=True))

        with self.s.begin_nested():
            pr_locked = self.repo.get_by_id(receipt_id, for_update=True)
            V.guard_cancellable_state(pr_locked.doc_status)
            pr_locked.doc_status = DocStatusEnum.CANCELLED
            self.repo.save(pr_locked)

            if rows:
                with lock_pairs(self.s, pairs):
                    for o in rows:
                        cancel_sle(self.s, o)

        self.s.commit()
        logger.info("💾 PR cancel committed | receipt_id=%s", receipt_id)

        # Maintenance
        with self.s.begin():
            for (item_id, wh_id) in pairs:
                repost_from(self.s, pr.company_id, item_id, wh_id, start_dt)

        # Reverse GL
        with self.s.begin():
            PostingService(self.s).cancel(
                PostingContext(
                    company_id=pr.company_id,
                    branch_id=pr.branch_id,
                    source_doctype_id=dt_id,
                    source_doc_id=pr.id,
                    posting_date=resolve_posting_dt(pr.posting_date, created_at=pr.created_at, treat_midnight_as_date=True),
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"Cancel {'Purchase Return' if pr.is_return else 'Purchase Receipt'} {pr.code}",
                    template_code=None,
                    payload={},
                    runtime_accounts={},
                    party_id=pr.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                )
            )
        logger.info("🎉 PR cancel done | %s", pr.code)
        return pr
