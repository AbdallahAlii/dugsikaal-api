# app/application_pricing/services/pricing_master_service.py
from __future__ import annotations
from typing import Optional, List, Tuple, Union
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.database import db
from app.application_nventory.inventory_models import PriceList, PriceListType, ItemPrice
from app.application_pricing.repo.pricing_master_repo import PricingMasterRepository
from app.application_pricing.services.price_day_cache import bump_price_list_version
from app.common.timezone.service import company_posting_dt, to_utc

# ---- ERP-style messages (single-line) ----
def _missing_message(fields: List[str]) -> str:
    # e.g., "Missing Values Required: Item, Price List, Rate"
    return "Missing Values Required: " + ", ".join(fields)

PL_MANDATORY_FIELDS = ["Price List Name"]
PL_APPLICABILITY_ERR = "Price List must be applicable for Buying or Selling"

# ---- code generator for Item Price (short, unique-ish) ----
def _base36(n: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    s = []
    while n:
        n, r = divmod(n, 36)
        s.append(alphabet[r])
    return "".join(reversed(s))

def _gen_item_price_code(company_id: int, pl_id: int, item_id: int,
                         uom_id: Optional[int], branch_id: Optional[int],
                         repo: PricingMasterRepository) -> str:
    """
    Format: IP-{pl}-{item}-{U|B}{B|G}-{t6}
      - U/B: UOM present or Base
      - B/G: Branch present or Global
      - t6 : 6-char base36 time token
    Keeps it short and readable while very unlikely to collide.
    """
    import time
    tag_u = f"U{uom_id}" if uom_id else "B"
    tag_b = f"B{branch_id}" if branch_id else "G"
    t6 = _base36(int(time.time()))[-6:].rjust(6, "0")
    code = f"IP-{pl_id}-{item_id}-{tag_u}-{tag_b}-{t6}"

    # ensure uniqueness within company; add 2-char salt if needed (rare)
    if repo.item_price_code_exists(company_id, code):
        salt = _base36(int(time.time_ns()) % (36**2)).rjust(2, "0")
        code = f"{code}-{salt}"
    return code


class PricingMasterService:
    """
    Unified service for Price List & Item Price CRUD with clean messages.
    """

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PricingMasterRepository(self.s)

    # =========================================================================
    # Helpers
    # =========================================================================
    @staticmethod
    def _normalize_validity(company_id: int,
                            vf: Optional[Union[date, datetime]],
                            vu: Optional[Union[date, datetime]]) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Accept date-only or datetime; return tz-aware UTC datetimes using company TZ.
        """
        def _norm(x: Optional[Union[date, datetime]]) -> Optional[datetime]:
            if x is None:
                return None
            if isinstance(x, datetime):
                dt_local = company_posting_dt(db.session, company_id, x, treat_midnight_as_date=True)
            else:
                dt_local = company_posting_dt(db.session, company_id, x, treat_midnight_as_date=True)
            return to_utc(dt_local).replace(tzinfo=None)  # store naive UTC if your DB expects naive
        nvf, nvu = _norm(vf), _norm(vu)
        if nvf and nvu and nvf > nvu:
            raise ValueError("Valid Upto must be greater than or equal to Valid From")
        return nvf, nvu

    # =========================================================================
    # Price List (Create / Update)
    # =========================================================================
    def create_price_list(
        self,
        *,
        company_id: int,
        name: Optional[str],
        list_type: Optional[str],
        price_not_uom_dependent: Optional[bool],
        is_active: Optional[bool],
    ) -> PriceList:
        missing = []
        if not (name or "").strip():
            missing.extend(PL_MANDATORY_FIELDS)
        if missing:
            raise ValueError(_missing_message(missing))

        if list_type not in {"Buying", "Selling", "Both"}:
            raise ValueError(PL_APPLICABILITY_ERR)

        if self.repo.price_list_name_exists(company_id, name):
            raise ValueError("Price List Name must be unique per company")

        pl = PriceList(
            company_id=company_id,
            name=name.strip(),
            list_type=PriceListType(list_type),
            price_not_uom_dependent=bool(price_not_uom_dependent) if price_not_uom_dependent is not None else False,
            is_active=True if is_active is None else bool(is_active),
        )
        try:
            self.repo.save(pl)
            self.s.commit()
            return pl
        except IntegrityError as e:
            self.s.rollback()
            raise ValueError(f"Could not create Price List: {getattr(e, 'orig', e)}")

    def update_price_list(
        self,
        *,
        company_id: int,
        pl_id: int,
        name: Optional[str] = None,
        list_type: Optional[str] = None,
        price_not_uom_dependent: Optional[bool] = None,
        is_active: Optional[bool] = None,
    ) -> PriceList:
        pl = self.repo.price_list_by_id(company_id, pl_id)
        if not pl:
            raise ValueError("Price List not found")

        if name is not None:
            if not name.strip():
                raise ValueError(_missing_message(PL_MANDATORY_FIELDS))
            if self.repo.price_list_name_exists(company_id, name, exclude_id=pl_id):
                raise ValueError("Price List Name must be unique per company")
            pl.name = name.strip()

        if list_type is not None:
            if list_type not in {"Buying", "Selling", "Both"}:
                raise ValueError(PL_APPLICABILITY_ERR)
            pl.list_type = PriceListType(list_type)

        if price_not_uom_dependent is not None:
            pl.price_not_uom_dependent = bool(price_not_uom_dependent)

        if is_active is not None:
            pl.is_active = bool(is_active)

        try:
            self.repo.save(pl)
            self.s.commit()
            return pl
        except IntegrityError as e:
            self.s.rollback()
            raise ValueError(f"Could not update Price List: {getattr(e, 'orig', e)}")

    # =========================================================================
    # Item Price (Create / Update)
    # =========================================================================
    def create_item_price(
        self,
        *,
        company_id: int,
        price_list_id: Optional[int],
        item_id: Optional[int],
        rate: Optional[Decimal],
        uom_id: Optional[int],
        branch_id: Optional[int],
        valid_from: Optional[Union[date, datetime]],
        valid_upto: Optional[Union[date, datetime]],
    ) -> ItemPrice:
        # Missing fields (ERP clean single-line)
        missing: List[str] = []
        if not item_id:
            missing.append("Item")
        if not price_list_id:
            missing.append("Price List")
        if rate is None:
            missing.append("Rate")
        if missing:
            raise ValueError(_missing_message(missing))

        # Price List checks
        pl = self.repo.price_list_by_id(company_id, int(price_list_id))
        if not pl or not pl.is_active:
            raise ValueError("Price List is invalid or disabled")
        if int(pl.company_id) != int(company_id):
            raise ValueError("Price List does not belong to this company")

        # Item core
        ic = self.repo.item_core(company_id, int(item_id))
        if not ic:
            raise ValueError("Item not found")
        is_active, base_uom_id = ic
        if not is_active:
            raise ValueError("Item is not active")

        # UOM (optional) + compatibility
        if uom_id is not None:
            if not self.repo.uom_exists(company_id, int(uom_id)):
                raise ValueError("Unit of Measure is invalid")
            if not self.repo.uom_compatible_with_item(int(item_id), int(uom_id), base_uom_id):
                raise ValueError("Unit of Measure is not valid for this item")

        # Branch (optional) company guard
        if branch_id is not None:
            bc = self.repo.get_branch_company_id(int(branch_id))
            if bc and int(bc) != int(company_id):
                raise ValueError("Branch does not belong to this company")

        # Validity window (normalize)
        nvf, nvu = self._normalize_validity(company_id, valid_from, valid_upto)

        # Duplicate tuple check
        if self.repo.duplicate_item_price_exists(
            price_list_id=int(price_list_id), item_id=int(item_id), uom_id=uom_id, branch_id=branch_id
        ):
            raise ValueError("Item Price with the same (Price List, Item, UOM, Branch) already exists")

        # Always auto-generate code; ignore any user input for 'code'
        code = _gen_item_price_code(company_id, int(price_list_id), int(item_id), uom_id, branch_id, self.repo)

        ip = ItemPrice(
            code=code,
            company_id=company_id,
            item_id=int(item_id),
            price_list_id=int(price_list_id),
            branch_id=int(branch_id) if branch_id is not None else None,
            uom_id=int(uom_id) if uom_id is not None else None,
            rate=Decimal(str(rate)).quantize(Decimal("0.0001")),
            valid_from=nvf,
            valid_upto=nvu,
        )

        try:
            self.repo.save(ip)
            bump_price_list_version(company_id, int(price_list_id))  # invalidate snapshot
            self.s.commit()
            return ip
        except IntegrityError as e:
            self.s.rollback()
            raise ValueError(f"Could not create Item Price: {getattr(e, 'orig', e)}")

    def update_item_price(
        self,
        *,
        company_id: int,
        item_price_id: int,
        # Only allow these fields to change:
        rate: Optional[Decimal] = None,
        valid_from: Optional[Union[date, datetime]] = None,
        valid_upto: Optional[Union[date, datetime]] = None,
    ) -> ItemPrice:
        ip = self.repo.item_price_by_id(int(item_price_id))
        if not ip:
            raise ValueError("Item Price not found")
        if int(ip.company_id) != int(company_id):
            raise ValueError("Item Price does not belong to this company")

        # Immutable tuple (pl, item, uom, branch) + immutable code
        # Only change rate / validity
        if rate is None and valid_from is None and valid_upto is None:
            # Nothing to change
            return ip

        if rate is not None:
            ip.rate = Decimal(str(rate)).quantize(Decimal("0.0001"))

        if (valid_from is not None) or (valid_upto is not None):
            nvf, nvu = self._normalize_validity(
                company_id,
                valid_from if valid_from is not None else ip.valid_from,
                valid_upto if valid_upto is not None else ip.valid_upto,
            )
            ip.valid_from, ip.valid_upto = nvf, nvu

        try:
            self.repo.save(ip)
            bump_price_list_version(company_id, int(ip.price_list_id))  # invalidate snapshot
            self.s.commit()
            return ip
        except IntegrityError as e:
            self.s.rollback()
            raise ValueError(f"Could not update Item Price: {getattr(e, 'orig', e)}")

