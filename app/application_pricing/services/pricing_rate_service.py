from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Literal

from config.database import db
from app.application_nventory.inventory_models import PriceListType
from app.application_pricing.repo.pricing_repo import PricingRepository
from app.application_nventory.services.price_day_cache import get_rate_from_snapshot

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.common.timezone.service import now_in_company_tz, to_utc, ensure_aware

log = logging.getLogger(__name__)
Kind = Literal["selling", "buying"]


def _now_utc_for_company(company_id: int) -> datetime:
    local_now = now_in_company_tz(db.session, company_id)
    return to_utc(local_now)


@dataclass(frozen=True)
class RateLine:
    row_id: str
    item_id: int
    uom_id: Optional[int] = None
    qty: Optional[float] = None


def _target(kind: Kind) -> PriceListType:
    return PriceListType.SELLING if kind == "selling" else PriceListType.BUYING


def _rate_response(*, row_id: str, item_id: int, uom_id: Optional[int], rate: float, source: str) -> Dict:
    return {"row_id": row_id, "item_id": item_id, "uom_id": uom_id, "rate": float(rate), "source": source}


def _resolve_effective_price_list(
    repo: PricingRepository,
    *,
    company_id: int,
    kind: Kind,
    explicit_pl_id: Optional[int],
    explicit_pl_name: Optional[str],
) -> Tuple[int, bool]:
    if explicit_pl_id:
        pl = repo.get_price_list(company_id, price_list_id=int(explicit_pl_id), price_list_name=None)
        if pl and pl["active"]:
            return int(pl["id"]), bool(pl["pnu"])

    if explicit_pl_name:
        pl = repo.get_price_list(company_id, price_list_id=None, price_list_name=str(explicit_pl_name))
        if pl and pl["active"]:
            return int(pl["id"]), bool(pl["pnu"])

    pl_id = repo.resolve_company_default_price_list_id(company_id, _target(kind))
    if not pl_id:
        return 0, True

    pl = repo.get_price_list(company_id, price_list_id=pl_id, price_list_name=None)
    return (int(pl["id"]), bool(pl["pnu"])) if pl else (0, True)


def _convert_rate_between_uoms(
    repo: PricingRepository,
    *,
    item_id: int,
    rate_per_from_uom: float,
    from_uom_id: int,
    to_uom_id: int,
) -> float:
    if from_uom_id == to_uom_id:
        return float(rate_per_from_uom)

    f_from = repo.get_uom_factor(item_id=item_id, txn_uom_id=int(from_uom_id))
    f_to = repo.get_uom_factor(item_id=item_id, txn_uom_id=int(to_uom_id))

    if float(f_from) == 0:
        return float(rate_per_from_uom)

    price_per_base = float(rate_per_from_uom) / float(f_from)
    return float(price_per_base) * float(f_to)


def get_rate_batch(
    *,
    company_id: int,
    kind: Kind,
    branch_id: Optional[int],
    warehouse_id: Optional[int],
    items: List[RateLine],
    posting_date: Optional[datetime],
    price_list_id: Optional[int],
    price_list_name: Optional[str],
    customer_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    allow_default_price_list_fallback: bool = True,
    allow_last_selling_rate_fallback: bool = True,
    context: Optional[AffiliationContext] = None,
) -> Tuple[int, List[Dict]]:

    if context is not None:
        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

    repo = PricingRepository()

    if posting_date is None:
        when = _now_utc_for_company(company_id)
    else:
        if posting_date.tzinfo is None:
            local = ensure_aware(posting_date, now_in_company_tz(db.session, company_id).tzinfo)
            when = to_utc(local)
        else:
            when = to_utc(posting_date)

    eff_pl_id, pnu = _resolve_effective_price_list(
        repo,
        company_id=company_id,
        kind=kind,
        explicit_pl_id=price_list_id,
        explicit_pl_name=price_list_name,
    )

    item_ids = [ln.item_id for ln in items]
    core_map = repo.get_item_core_bulk(company_id=company_id, item_ids=item_ids)

    out: Dict[str, Dict] = {}
    misses: List[RateLine] = []

    for ln in items:
        core = core_map.get(ln.item_id)
        if not core or not core["is_active"]:
            out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=ln.uom_id, rate=0.0, source="inactive_or_missing_item")
            continue

        base_uom_id = int(core["base_uom_id"] or 0)
        txn_uom_id = int(ln.uom_id or base_uom_id)

        if eff_pl_id:
            lookup_uom = base_uom_id if (pnu and base_uom_id) else txn_uom_id
            snap = get_rate_from_snapshot(
                company_id=company_id,
                pl_id=eff_pl_id,
                I=int(ln.item_id),
                U=int(lookup_uom),
                B=branch_id,
                D=when,
                PU=int(base_uom_id),
            )
            if snap is not None:
                rate = float(snap)
                if pnu and txn_uom_id != base_uom_id:
                    factor = repo.get_uom_factor(item_id=ln.item_id, txn_uom_id=txn_uom_id)
                    rate = rate * float(factor)
                out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=txn_uom_id, rate=rate, source="item_price")
                continue

        misses.append(ln)

    if eff_pl_id and misses:
        try:
            sql_rows = repo.find_item_prices_best_bulk(
                company_id=company_id,
                price_list_id=eff_pl_id,
                branch_id=branch_id,
                when=when,
                lines=misses,
                price_not_uom_dependent=pnu,
                core_map=core_map,
            )
            for r in sql_rows:
                out[r["row_id"]] = r
        except Exception:
            log.exception("pricing.get_rate_batch SQL fallback failed (returning missing=0)")

    def _is_missing(row_id: str) -> bool:
        r = out.get(row_id)
        return (r is None) or (float(r.get("rate") or 0) <= 0 and r.get("source") in (None, "missing"))

    if kind == "selling" and allow_default_price_list_fallback:
        still_missing = [ln for ln in items if _is_missing(ln.row_id)]
        if still_missing:
            def_pl_id = repo.resolve_company_default_price_list_id(company_id, PriceListType.SELLING)
            if def_pl_id and def_pl_id != eff_pl_id:
                pl = repo.get_price_list(company_id, price_list_id=def_pl_id, price_list_name=None)
                pnu2 = bool(pl["pnu"]) if pl else True
                try:
                    fb_rows = repo.find_item_prices_best_bulk(
                        company_id=company_id,
                        price_list_id=def_pl_id,
                        branch_id=branch_id,
                        when=when,
                        lines=still_missing,
                        price_not_uom_dependent=pnu2,
                        core_map=core_map,
                    )
                    for r in fb_rows:
                        r["source"] = "default_price_list"
                        out[r["row_id"]] = r
                except Exception:
                    log.exception("pricing.get_rate_batch default PL fallback failed")

    if kind == "selling" and allow_last_selling_rate_fallback:
        for ln in items:
            if not _is_missing(ln.row_id):
                continue

            core = core_map.get(ln.item_id)
            if not core or not core["is_active"]:
                continue

            base_uom_id = int(core["base_uom_id"] or 0)
            txn_uom_id = int(ln.uom_id or base_uom_id)

            last = repo.get_last_selling_rate(company_id=company_id, item_id=ln.item_id, branch_id=branch_id)
            if last:
                last_rate, last_uom_id = last
                rr = float(last_rate)

                if last_uom_id and txn_uom_id and last_uom_id != txn_uom_id:
                    rr = _convert_rate_between_uoms(
                        repo,
                        item_id=ln.item_id,
                        rate_per_from_uom=rr,
                        from_uom_id=last_uom_id,
                        to_uom_id=txn_uom_id,
                    )

                out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=txn_uom_id, rate=rr, source="last_selling_rate")

    if kind == "buying":
        for ln in items:
            if not _is_missing(ln.row_id):
                continue

            core = core_map.get(ln.item_id)
            if not core or not core["is_active"]:
                continue

            base_uom_id = int(core["base_uom_id"] or 0)
            txn_uom_id = int(ln.uom_id or base_uom_id)

            last_rate = repo.get_last_purchase_rate(company_id=company_id, item_id=ln.item_id, branch_id=branch_id, warehouse_id=warehouse_id)
            if last_rate is not None and float(last_rate) > 0:
                out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=txn_uom_id, rate=float(last_rate), source="last_purchase_rate")
                continue

            val_rate = repo.get_valuation_rate_from_bin(company_id=company_id, item_id=ln.item_id, branch_id=branch_id, warehouse_id=warehouse_id)
            if val_rate is not None and float(val_rate) > 0:
                out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=txn_uom_id, rate=float(val_rate), source="valuation_rate")

    for ln in items:
        if ln.row_id not in out:
            core = core_map.get(ln.item_id)
            base_uom_id = int(core["base_uom_id"] or 0) if core else 0
            txn_uom_id = int(ln.uom_id or base_uom_id) if base_uom_id else ln.uom_id
            out[ln.row_id] = _rate_response(row_id=ln.row_id, item_id=ln.item_id, uom_id=txn_uom_id, rate=0.0, source="missing")

    return eff_pl_id, [out[ln.row_id] for ln in items]
