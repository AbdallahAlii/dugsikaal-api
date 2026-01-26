# app/application_shareholder/services/services.py
from __future__ import annotations

import logging
from typing import Optional, Tuple, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.application_shareholder.repository.shareholder_repo import ShareholderRepository
from app.application_shareholder.models import Shareholder, ShareType, ShareLedgerEntry, ShareTransactionTypeEnum
from app.application_shareholder.schemas.schemas import (
    ShareholderCreate,
    ShareholderUpdate,
    ShareholderCreateResponse,
    ShareholderMinimalOut,
    ShareTypeCreate,
    ShareTypeUpdate,
    ShareLedgerEntryCreate,
)
from app.business_validation.shareholder_validation import (
    validate_shareholder_basic,
)
from app.common.models.base import StatusEnum
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.common.cache.cache_invalidator import bump_list_cache_company
from app.common.timezone.service import ensure_aware, to_utc, get_company_timezone
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.business_validation.item_validation import BizValidationError
from app.application_media.service import save_image_for
from app.application_media.utils import MediaFolder

log = logging.getLogger(__name__)

SHAREHOLDER_PREFIX = "ACC-SH"


class ShareholderService:
    def __init__(
        self,
        repo: Optional[ShareholderRepository] = None,
        session: Optional[Session] = None,
    ):
        self.repo = repo or ShareholderRepository(session or db.session)
        self.s: Session = self.repo.s

    # --------------------------
    # Transaction helpers
    # --------------------------

    @property
    def _in_nested_tx(self) -> bool:
        try:
            in_nested = getattr(self.s, "in_nested_transaction", None)
            if callable(in_nested):
                return bool(in_nested())
        except Exception:
            pass

        tx = getattr(self.s, "transaction", None)
        if tx is None:
            return False

        if getattr(tx, "nested", False):
            return True

        parent = getattr(tx, "parent", None)
        while parent is not None:
            if getattr(parent, "nested", False):
                return True
            parent = parent.parent

        return False

    def _commit_or_flush(self) -> None:
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        if self._in_nested_tx:
            return
        self.s.rollback()

    # --------------------------
    # Helpers
    # --------------------------

    def _allocate_shareholder_code(
        self,
        *,
        company_id: int,
        manual_code: Optional[str],
    ) -> str:
        if manual_code:
            manual = manual_code.strip()
            ensure_manual_code_is_next_and_bump(
                prefix=SHAREHOLDER_PREFIX,
                company_id=company_id,
                branch_id=None,
                code=manual,
            )
            if self.repo.shareholder_code_exists(company_id, manual):
                raise BizValidationError("Shareholder code already exists in this company.")
            return manual

        return generate_next_code(
            prefix=SHAREHOLDER_PREFIX,
            company_id=company_id,
            branch_id=None,
        )

    # ------------------------------------------------------------------
    # Shareholder create / update
    # ------------------------------------------------------------------

    def create_shareholder(
        self,
        *,
        payload: ShareholderCreate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ShareholderCreateResponse]]:
        try:
            company_id = payload.company_id or context.company_id
            # basic validations
            validate_shareholder_basic(
                company_id=company_id,
                full_name=payload.full_name,
                category=payload.category,
                national_id=payload.national_id,
                registration_no=payload.registration_no,
            )

            # scope: user must have access to this company
            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None,
            )

            # code allocation
            code = self._allocate_shareholder_code(
                company_id=company_id,
                manual_code=payload.code,
            )

            sh = Shareholder(
                company_id=company_id,
                code=code,
                full_name=payload.full_name.strip(),
                category=payload.category,
                national_id=payload.national_id,
                registration_no=payload.registration_no,
                contact_email=payload.contact_email,
                contact_phone=payload.contact_phone,
                address=payload.address,
                status=payload.status or StatusEnum.ACTIVE,
                remarks=payload.remarks,
            )

            self.repo.create_shareholder(sh)

            # emergency contacts
            if payload.emergency_contacts:
                self.repo.create_emergency_contacts(
                    shareholder_id=sh.id,
                    rows=[c.dict() for c in payload.emergency_contacts],
                )

            # optional image
            if file_storage:
                new_key = save_image_for(
                    folder=MediaFolder.SHAREHOLDERS,  # add this enum member
                    item_id=sh.id,
                    file=file_storage,
                    bytes_=bytes_,
                    filename=filename,
                    content_type=content_type,
                    old_img_key=sh.img_key,
                )
                if new_key:
                    sh.img_key = new_key
                    self.s.flush([sh])

            self._commit_or_flush()

            # cache bump (best effort)
            try:
                bump_list_cache_company("shareholder", "shareholders", company_id)
            except Exception:
                log.exception("[cache] failed to bump shareholders list cache after create")

            resp = ShareholderCreateResponse(
                shareholder=ShareholderMinimalOut(
                    id=sh.id,
                    code=sh.code,
                    full_name=sh.full_name,
                )
            )
            return True, "Shareholder created", resp

        except BizValidationError as e:
            log.warning("BizValidationError during shareholder create: %s", e)
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None
        except IntegrityError as e:
            log.error("IntegrityError during shareholder create: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_shareholder_company_code" in msg:
                return False, "Shareholder code already exists in this company.", None
            return False, "Integrity error while creating Shareholder.", None
        except ValueError as e:
            log.error("ValueError during shareholder create: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = str(e)
            if "Unknown code type prefix" in msg:
                return (
                    False,
                    "Shareholder code series 'ACC-SH' is not configured. Please contact System Administrator.",
                    None,
                )
            return False, msg, None
        except Exception as e:
            log.exception("Unexpected error during shareholder create: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Shareholder.", None

    def update_shareholder(
        self,
        *,
        shareholder_id: int,
        payload: ShareholderUpdate,
        context: AffiliationContext,
        file_storage=None,
        bytes_: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ShareholderCreateResponse]]:
        try:
            sh = self.repo.get_shareholder_by_id(shareholder_id)
            if not sh:
                return False, "Shareholder not found.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=sh.company_id,
                target_branch_id=None,
            )

            data = payload.dict(exclude_unset=True)

            # if category changes, revalidate some rules
            category = data.get("category", sh.category)
            national_id = data.get("national_id", sh.national_id)
            registration_no = data.get("registration_no", sh.registration_no)
            full_name = data.get("full_name", sh.full_name)

            validate_shareholder_basic(
                company_id=sh.company_id,
                full_name=full_name,
                category=category,
                national_id=national_id,
                registration_no=registration_no,
            )

            # apply simple fields
            fields = [
                "full_name",
                "category",
                "national_id",
                "registration_no",
                "contact_email",
                "contact_phone",
                "address",
                "img_key",
                "status",
                "remarks",
            ]
            update_data = {f: data[f] for f in fields if f in data}
            self.repo.update_shareholder_fields(sh, update_data)

            # emergency contacts replace
            if "emergency_contacts" in data and data["emergency_contacts"] is not None:
                contacts = (
                    [c.dict() for c in payload.emergency_contacts]
                    if payload.emergency_contacts
                    else []
                )
                self.repo.update_emergency_contacts(sh.id, contacts)

            # optional image
            if file_storage:
                new_key = save_image_for(
                    folder=MediaFolder.SHAREHOLDERS,
                    item_id=sh.id,
                    file=file_storage,
                    bytes_=bytes_,
                    filename=filename,
                    content_type=content_type,
                    old_img_key=sh.img_key,
                )
                if new_key:
                    sh.img_key = new_key
                    self.s.flush([sh])

            self._commit_or_flush()

            try:
                bump_list_cache_company("shareholder", "shareholders", sh.company_id)
            except Exception:
                log.exception("[cache] failed to bump shareholders list cache after update")

            resp = ShareholderCreateResponse(
                message="Shareholder updated",
                shareholder=ShareholderMinimalOut(
                    id=sh.id,
                    code=sh.code,
                    full_name=sh.full_name,
                ),
            )
            return True, "Shareholder updated", resp

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            msg = getattr(e, "description", str(e))
            return False, msg, None
        except IntegrityError as e:
            log.error("IntegrityError during shareholder update: %s", e, exc_info=True)
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_shareholder_company_code" in msg:
                return False, "Shareholder code already exists in this company.", None
            return False, "Integrity error while updating Shareholder.", None
        except Exception as e:
            log.exception("Unexpected error during shareholder update: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Shareholder.", None

    # ------------------------------------------------------------------
    # Share Type create / update
    # ------------------------------------------------------------------

    def create_share_type(
        self,
        *,
        payload: ShareTypeCreate,
        context: AffiliationContext,
    ):
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Share Type.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None,
            )

            if self.repo.share_type_code_exists(company_id, payload.code):
                raise BizValidationError("Share Type code already exists in this Company.")

            st = ShareType(
                company_id=company_id,
                code=payload.code.strip(),
                name=payload.name.strip(),
                nominal_value=payload.nominal_value,
                is_default=payload.is_default,
                total_authorised_shares=payload.total_authorised_shares,
                status=payload.status or StatusEnum.ACTIVE,
                remarks=payload.remarks,
            )
            self.repo.create_share_type(st)
            self._commit_or_flush()
            return True, "Share Type created", st

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_share_type_company_code" in msg:
                return False, "Share Type code already exists in this Company.", None
            return False, "Integrity error while creating Share Type.", None
        except Exception as e:
            log.exception("Unexpected error while creating Share Type: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Share Type.", None

    def update_share_type(
        self,
        *,
        share_type_id: int,
        payload: ShareTypeUpdate,
        context: AffiliationContext,
    ):
        try:
            st = self.repo.get_share_type_by_id(share_type_id)
            if not st:
                return False, "Share Type not found.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=st.company_id,
                target_branch_id=None,
            )

            data = payload.dict(exclude_unset=True)
            self.repo.update_share_type_fields(st, data)
            self._commit_or_flush()
            return True, "Share Type updated", st

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_share_type_company_code" in msg:
                return False, "Share Type code already exists in this Company.", None
            return False, "Integrity error while updating Share Type.", None
        except Exception as e:
            log.exception("Unexpected error while updating Share Type: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Share Type.", None

    # ------------------------------------------------------------------
    # Share Ledger Entry create (basic, ERP-style)
    # ------------------------------------------------------------------

    def create_share_ledger_entry(
        self,
        *,
        payload: ShareLedgerEntryCreate,
        context: AffiliationContext,
    ):
        """
        Basic SLE create.
        If transaction_type is TRANSFER_OUT / REDEMPTION, we ensure
        the shareholder has enough shares of that type.
        """
        try:
            company_id = payload.company_id or context.company_id
            if not company_id:
                return False, "Company is required for Share Ledger Entry.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=None,
            )

            # basic available-shares check for outgoing movements
            qty = float(payload.quantity)
            if payload.transaction_type in (
                ShareTransactionTypeEnum.TRANSFER_OUT,
                ShareTransactionTypeEnum.REDEMPTION,
            ):
                current = self.repo.total_shares_for_shareholder(
                    company_id=company_id,
                    shareholder_id=payload.shareholder_id,
                    share_type_id=payload.share_type_id,
                )
                if current + qty < -1e-6:  # qty is negative in our convention,
                    raise BizValidationError(
                        "Not enough shares available for this Shareholder and Share Type."
                    )

            tz = get_company_timezone(self.s, company_id)
            aware = ensure_aware(payload.posting_date, tz)
            posting_utc = to_utc(aware)

            sle = ShareLedgerEntry(
                company_id=company_id,
                shareholder_id=payload.shareholder_id,
                share_type_id=payload.share_type_id,
                posting_date=posting_utc,
                transaction_type=payload.transaction_type,
                quantity=payload.quantity,
                rate=payload.rate,
                amount=payload.amount,
                journal_entry_id=payload.journal_entry_id,
                source_doctype_id=payload.source_doctype_id,
                source_doc_id=payload.source_doc_id,
                remarks=payload.remarks,
            )
            self.repo.create_share_ledger_entry(sle)
            self._commit_or_flush()
            return True, "Share ledger entry created", sle

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("Unexpected error while creating Share Ledger Entry: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Share Ledger Entry.", None
