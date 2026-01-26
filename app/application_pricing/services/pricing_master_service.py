from __future__ import annotations

import logging
from datetime import datetime, date, time as dtime
from decimal import Decimal
from typing import Optional, Tuple, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.exceptions import HTTPException

from config.database import db
from app.application_nventory.inventory_models import PriceList, PriceListType, ItemPrice
from app.application_pricing.repo.pricing_master_repo import PricingMasterRepository
from app.application_pricing.services.price_day_cache import bump_price_list_version

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc

from app.business_validation.item_validation import BizValidationError
from app.business_validation.pricing_validation import (
    validate_price_list_basic,
    validate_item_price_mandatory,
    validate_validity_range,
    ERR_PL_NOT_FOUND,
    ERR_PL_INACTIVE_DEFAULT,
    ERR_PL_DEFAULT_EXISTS,
    ERR_PL_NAME_EXISTS,
    ERR_IP_PRICE_LIST_INVALID,
    ERR_IP_ITEM_INVALID,
    ERR_IP_UOM_INVALID,
    ERR_IP_UOM_NOT_ALLOWED,
    ERR_IP_BRANCH_COMPANY_MISMATCH,
    ERR_IP_DUPLICATE,
    ERR_IP_NOT_FOUND,
)

log = logging.getLogger(__name__)
DEC4 = Decimal("0.0001")
IP_PREFIX = "IP"


def _base36(n: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    s = []
    while n:
        n, r = divmod(n, 36)
        s.append(alphabet[r])
    return "".join(reversed(s))


def _gen_item_price_code(*, company_id: int, repo: PricingMasterRepository) -> str:
    import time, uuid
    t6 = _base36(int(time.time()))[-6:].rjust(6, "0")
    code = f"{IP_PREFIX}-{t6}-{uuid.uuid4().hex[:4].upper()}"
    if repo.item_price_code_exists(company_id=company_id, code=code):
        code = f"{code}-{uuid.uuid4().hex[:2].upper()}"
    return code


def _pg_constraint_name(err: IntegrityError) -> str:
    """
    Best-effort: fetch Postgres constraint name (psycopg2/psycopg3),
    else fallback to string search.
    """
    try:
        orig = getattr(err, "orig", None)
        diag = getattr(orig, "diag", None)
        c = getattr(diag, "constraint_name", None)
        if c:
            return str(c)
    except Exception:
        pass
    return str(err).lower()


class PricingMasterService:
    def __init__(self, repo: Optional[PricingMasterRepository] = None, session: Optional[Session] = None):
        self.repo = repo or PricingMasterRepository(session or db.session)
        self.s: Session = self.repo.s

    # ---------------------------
    # TX helpers
    # ---------------------------
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
        if not self._in_nested_tx:
            self.s.rollback()

    # ---------------------------
    # Time helpers
    # ---------------------------
    def _normalize_validity(
        self,
        *,
        company_id: int,
        valid_from: Optional[Union[date, datetime]],
        valid_upto: Optional[Union[date, datetime]],
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        tz = get_company_timezone(self.s, company_id)

        def _norm_from(x) -> Optional[datetime]:
            if x is None:
                return None
            if isinstance(x, date) and not isinstance(x, datetime):
                local = datetime.combine(x, dtime(0, 0, 0)).replace(tzinfo=tz)
                return to_utc(local)
            return to_utc(ensure_aware(x, tz))

        def _norm_upto(x) -> Optional[datetime]:
            if x is None:
                return None
            if isinstance(x, date) and not isinstance(x, datetime):
                local = datetime.combine(x, dtime(23, 59, 59, 999999)).replace(tzinfo=tz)
                return to_utc(local)
            return to_utc(ensure_aware(x, tz))

        vf = _norm_from(valid_from)
        vu = _norm_upto(valid_upto)
        validate_validity_range(vf, vu)
        return vf, vu

    # ---------------------------
    # Default rule
    # ---------------------------
    def _validate_default_rule(self, *, company_id: int, pl: PriceList, exclude_id: Optional[int]) -> None:
        if not pl.is_default:
            return
        if not pl.is_active:
            raise BizValidationError(ERR_PL_INACTIVE_DEFAULT)
        if self.repo.default_price_list_exists(company_id=int(company_id), list_type=pl.list_type, exclude_id=exclude_id):
            raise BizValidationError(ERR_PL_DEFAULT_EXISTS)

    # -------------------------------------------------------------------------
    # PRICE LIST
    # -------------------------------------------------------------------------
    def create_price_list(self, *, payload, context: AffiliationContext) -> Tuple[bool, str, Optional[PriceList]]:
        try:
            company_id = getattr(payload, "company_id", None) or getattr(context, "company_id", None)
            if not company_id:
                return False, "Company is required.", None

            ensure_scope_by_ids(context=context, target_company_id=int(company_id), target_branch_id=None)

            name = (getattr(payload, "name", None) or "").strip()
            lt_enum = validate_price_list_basic(name=name, list_type=getattr(payload, "list_type", None))

            if self.repo.price_list_name_exists(company_id=int(company_id), name=name):
                raise BizValidationError(ERR_PL_NAME_EXISTS)

            pl = PriceList(
                company_id=int(company_id),
                name=name,
                list_type=lt_enum,
                price_not_uom_dependent=bool(getattr(payload, "price_not_uom_dependent", True)),
                is_active=bool(getattr(payload, "is_active", True)),
                is_default=bool(getattr(payload, "is_default", False)),
            )

            # clear default error BEFORE insert
            self._validate_default_rule(company_id=int(company_id), pl=pl, exclude_id=None)

            self.repo.save(pl)
            self._commit_or_flush()
            return True, "Price List created.", pl

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            cn = _pg_constraint_name(e)

            if "uq_price_list_company_name" in cn:
                return False, ERR_PL_NAME_EXISTS, None
            if "uq_price_list_default_selling" in cn or "uq_price_list_default_buying" in cn:
                return False, ERR_PL_DEFAULT_EXISTS, None

            return False, "Could not create Price List.", None
        except Exception:
            log.exception("create_price_list failed")
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Price List.", None

    def update_price_list(self, *, price_list_id: int, payload, context: AffiliationContext) -> Tuple[bool, str, Optional[PriceList]]:
        try:
            company_id = getattr(payload, "company_id", None) or getattr(context, "company_id", None)
            if not company_id:
                return False, "Company is required.", None

            ensure_scope_by_ids(context=context, target_company_id=int(company_id), target_branch_id=None)

            pl = self.repo.get_price_list_by_id(company_id=int(company_id), price_list_id=int(price_list_id))
            if not pl:
                return False, ERR_PL_NOT_FOUND, None

            if getattr(payload, "name", None) is not None:
                name = (payload.name or "").strip()
                validate_price_list_basic(name=name, list_type=pl.list_type.value)
                if self.repo.price_list_name_exists(company_id=int(company_id), name=name, exclude_id=pl.id):
                    raise BizValidationError(ERR_PL_NAME_EXISTS)
                pl.name = name

            if getattr(payload, "list_type", None) is not None:
                pl.list_type = validate_price_list_basic(name=pl.name, list_type=payload.list_type)

            if getattr(payload, "price_not_uom_dependent", None) is not None:
                pl.price_not_uom_dependent = bool(payload.price_not_uom_dependent)
            if getattr(payload, "is_active", None) is not None:
                pl.is_active = bool(payload.is_active)
            if getattr(payload, "is_default", None) is not None:
                pl.is_default = bool(payload.is_default)

            # Only validate default rule when relevant fields changed
            if any(getattr(payload, k, None) is not None for k in ("is_default", "is_active", "list_type")):
                self._validate_default_rule(company_id=int(company_id), pl=pl, exclude_id=pl.id)

            self.repo.save(pl)
            self._commit_or_flush()
            return True, "Price List updated.", pl

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError as e:
            self._rollback_if_top_level()
            cn = _pg_constraint_name(e)

            if "uq_price_list_company_name" in cn:
                return False, ERR_PL_NAME_EXISTS, None
            if "uq_price_list_default_selling" in cn or "uq_price_list_default_buying" in cn:
                return False, ERR_PL_DEFAULT_EXISTS, None

            return False, "Could not update Price List.", None
        except Exception:
            log.exception("update_price_list failed")
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Price List.", None

    # -------------------------------------------------------------------------
    # ITEM PRICE
    # -------------------------------------------------------------------------
    def create_item_price(self, *, payload, context: AffiliationContext) -> Tuple[bool, str, Optional[ItemPrice]]:
        try:
            company_id = getattr(payload, "company_id", None) or getattr(context, "company_id", None)
            if not company_id:
                return False, "Company is required.", None

            branch_id = getattr(payload, "branch_id", None)

            ensure_scope_by_ids(
                context=context,
                target_company_id=int(company_id),
                target_branch_id=int(branch_id) if branch_id is not None else None,
            )

            item_id = int(payload.item_id) if getattr(payload, "item_id", None) is not None else None
            price_list_id = int(payload.price_list_id) if getattr(payload, "price_list_id", None) is not None else None
            rate = float(payload.rate) if getattr(payload, "rate", None) is not None else None

            validate_item_price_mandatory(item_id=item_id, price_list_id=price_list_id, rate=rate)

            # 1. Validate Price List
            pl = self.repo.get_price_list_by_id(company_id=int(company_id), price_list_id=int(price_list_id))
            if not pl or not pl.is_active:
                raise BizValidationError(ERR_IP_PRICE_LIST_INVALID)

            # 2. Validate Item exists (ERPNext style - item must exist, but base_uom_id can be NULL)
            if not self.repo.item_exists_and_belongs_to_company(company_id=int(company_id), item_id=int(item_id)):
                raise BizValidationError(ERR_IP_ITEM_INVALID)

            # 3. Get base_uom_id (can be NULL for service items)
            base_uom_id = self.repo.get_item_base_uom_id(company_id=int(company_id), item_id=int(item_id))
            # Don't validate base_uom_id - it can be NULL in ERPNext

            # 4. Validate branch if provided
            if branch_id is not None:
                bc = self.repo.get_branch_company_id(int(branch_id))
                if bc is None or int(bc) != int(company_id):
                    raise BizValidationError(ERR_IP_BRANCH_COMPANY_MISMATCH)

            # 5. Handle UOM logic (ERPNext style)
            uom_id = getattr(payload, "uom_id", None)
            uom_id = int(uom_id) if uom_id is not None else None

            if uom_id is not None:
                # Check UOM belongs to company
                if not self.repo.uom_belongs_to_company(company_id=int(company_id), uom_id=int(uom_id)):
                    raise BizValidationError(ERR_IP_UOM_INVALID)

                # Only check UOM conversion if:
                # 1. Item has a base_uom_id (not NULL)
                # 2. Provided UOM is different from base UOM
                # 3. Item is a stock item (service items don't need UOM conversions)
                item_type = self.repo.get_item_type(company_id=int(company_id), item_id=int(item_id))
                is_stock_item = item_type == "STOCK_ITEM" if item_type else False

                if (is_stock_item and
                        base_uom_id is not None and
                        base_uom_id != uom_id and
                        not self.repo.uom_conversion_exists(item_id=int(item_id), uom_id=int(uom_id))):
                    raise BizValidationError(ERR_IP_UOM_NOT_ALLOWED)

                # For service items or items without base UOM, allow any UOM without conversion check
            else:
                # If no UOM provided, use base_uom_id (which can be NULL)
                uom_id = base_uom_id  # This can be NULL for service items

            # 6. Normalize validity dates
            vf_utc, vu_utc = self._normalize_validity(
                company_id=int(company_id),
                valid_from=getattr(payload, "valid_from", None),
                valid_upto=getattr(payload, "valid_upto", None),
            )

            # 7. Check for overlapping prices
            if self.repo.item_price_overlaps(
                    company_id=int(company_id),
                    price_list_id=int(price_list_id),
                    item_id=int(item_id),
                    branch_id=int(branch_id) if branch_id is not None else None,
                    uom_id=uom_id,
                    valid_from_utc=vf_utc,
                    valid_upto_utc=vu_utc,
                    exclude_id=None,
            ):
                return False, ERR_IP_DUPLICATE, None

            # 8. Create Item Price (ERPNext style - uom_id can be NULL)
            ip = ItemPrice(
                code=_gen_item_price_code(company_id=int(company_id), repo=self.repo),
                company_id=int(company_id),
                item_id=int(item_id),
                price_list_id=int(price_list_id),
                branch_id=int(branch_id) if branch_id is not None else None,
                uom_id=uom_id,  # This can be NULL
                rate=Decimal(str(rate)).quantize(DEC4),
                valid_from=vf_utc,
                valid_upto=vu_utc,
            )

            self.repo.save(ip)
            bump_price_list_version(int(company_id), int(price_list_id))
            self._commit_or_flush()
            return True, "Item Price created.", ip

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_IP_DUPLICATE, None
        except Exception:
            log.exception("create_item_price failed")
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Item Price.", None

    def update_item_price(self, *, item_price_id: int, payload, context: AffiliationContext) -> Tuple[
        bool, str, Optional[ItemPrice]]:
        try:
            ip = self.repo.get_item_price_by_id(item_price_id=int(item_price_id))
            if not ip:
                return False, ERR_IP_NOT_FOUND, None

            ensure_scope_by_ids(
                context=context,
                target_company_id=int(ip.company_id),
                target_branch_id=int(ip.branch_id) if ip.branch_id is not None else None,
            )

            changed = False

            if getattr(payload, "rate", None) is not None:
                ip.rate = Decimal(str(payload.rate)).quantize(DEC4)
                changed = True

            if getattr(payload, "valid_from", None) is not None or getattr(payload, "valid_upto", None) is not None:
                vf_in = getattr(payload, "valid_from", None)
                vu_in = getattr(payload, "valid_upto", None)

                vf_utc, vu_utc = self._normalize_validity(
                    company_id=int(ip.company_id),
                    valid_from=vf_in if vf_in is not None else ip.valid_from,
                    valid_upto=vu_in if vu_in is not None else ip.valid_upto,
                )

                if self.repo.item_price_overlaps(
                        company_id=int(ip.company_id),
                        price_list_id=int(ip.price_list_id),
                        item_id=int(ip.item_id),
                        branch_id=int(ip.branch_id) if ip.branch_id is not None else None,
                        uom_id=int(ip.uom_id) if ip.uom_id is not None else None,  # Handle NULL
                        valid_from_utc=vf_utc,
                        valid_upto_utc=vu_utc,
                        exclude_id=int(ip.id),
                ):
                    return False, ERR_IP_DUPLICATE, None

                ip.valid_from = vf_utc
                ip.valid_upto = vu_utc
                changed = True

            if not changed:
                return True, "Item Price updated.", ip

            self.repo.save(ip)
            bump_price_list_version(int(ip.company_id), int(ip.price_list_id))
            self._commit_or_flush()
            return True, "Item Price updated.", ip

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except HTTPException as e:
            self._rollback_if_top_level()
            return False, getattr(e, "description", str(e)), None
        except IntegrityError:
            self._rollback_if_top_level()
            return False, ERR_IP_DUPLICATE, None
        except Exception:
            log.exception("update_item_price failed")
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Item Price.", None