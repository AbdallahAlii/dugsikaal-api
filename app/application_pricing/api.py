from __future__ import annotations
from datetime import datetime
from flask import Blueprint, request, g
import logging
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Forbidden, Conflict, BadRequest


import logging, uuid
from datetime import datetime
from flask import Blueprint, request, g
from pydantic import ValidationError

from app.application_nventory.services.pricing_service import get_selling_rate_batch
from app.application_pricing.pricing_schemas import PriceListCreate, PriceListUpdate, ItemPriceCreate, ItemPriceUpdate
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext, attach_auth_context
from app.application_pricing.services.pricing_master_service import PricingMasterService
from app.application_pricing.services.pricing_service import (
    get_selling_rate_basic, get_buying_rate_basic, _parse_iso
)
bp = Blueprint("pricing", __name__, url_prefix="/api/pricing")
log = logging.getLogger(__name__)
def _ctx() -> AffiliationContext:
    from app.auth.deps import get_current_user
    _ = get_current_user()  # sets g.current_user and (in your stack) g.auth
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx

def _compactify(data: dict, compact: bool) -> dict:
    if not compact:
        return data
    return {"rate": float(data.get("rate") or 0.0)}

def _resolve_branch(ctx: AffiliationContext, raw: dict) -> int | None:
    """
    Precedence:
      1) explicit body.branch_id
      2) ctx.branch_id
      3) if user has exactly one affiliated branch, use it
      4) None (company/global or any-branch fallback happens in service/repo)
    """
    if "branch_id" in raw and raw["branch_id"] is not None:
        return int(raw["branch_id"])
    if getattr(ctx, "branch_id", None) is not None:
        return int(ctx.branch_id)
    try:
        cands = {a.branch_id for a in (ctx.affiliations or []) if a.branch_id is not None}
        if len(cands) == 1:
            return int(next(iter(cands)))
    except Exception:
        pass
    return None
@bp.post("/selling-rate")
@require_permission("Item", "READ")
def selling_rate():
    req_id = uuid.uuid4().hex[:8]
    try:
        ctx = _ctx()
        raw = (request.get_json(silent=True) or {})
        branch_id = _resolve_branch(ctx, raw)
        when = _parse_iso(raw.get("posting_date"))
        compact = bool(raw.get("compact") or (request.args.get("view") == "compact"))

        # batch
        if isinstance(raw.get("items"), list):
            log.debug("[%s] selling/batch company=%s branch=%s items=%s",
                      req_id, ctx.company_id, branch_id, len(raw["items"]))
            data = get_selling_rate_batch(
                company_id=ctx.company_id,
                branch_id=branch_id,
                items=raw["items"],
                posting_date=when,
                price_list_id=raw.get("price_list_id"),
                price_list_name=raw.get("price_list_name"),
                customer_id=raw.get("customer_id"),
            )
            return api_success({"items": [{"row_id": r.get("row_id"), "rate": float(r["rate"])} for r in data]}
                               if compact else {"items": data})

        # single
        item_id = int(raw["item_id"])
        uom_id = int(raw["uom_id"]) if raw.get("uom_id") is not None else None
        qty = raw.get("qty")

        log.debug("[%s] selling/single company=%s branch=%s item=%s uom=%s",
                  req_id, ctx.company_id, branch_id, item_id, uom_id)

        data = get_selling_rate_basic(
            company_id=ctx.company_id,
            branch_id=branch_id,
            item_id=item_id,
            txn_uom_id=uom_id,     # None → no UOM preference
            qty=qty,
            posting_date=when,
            price_list_id=raw.get("price_list_id"),
            price_list_name=raw.get("price_list_name"),
            customer_id=raw.get("customer_id"),
        )
        log.debug("[%s] selling result=%s", req_id, data)
        return api_success(_compactify(data, compact))
    except Exception as e:
        log.exception("[SELLING %s] error: %s", req_id, e)
        return api_error(str(e), status_code=400)

@bp.post("/buying-rate")
@require_permission("Item", "READ")
def buying_rate():
    req_id = uuid.uuid4().hex[:8]
    try:
        ctx = _ctx()
        raw = (request.get_json(silent=True) or {})
        branch_id = _resolve_branch(ctx, raw)
        when = _parse_iso(raw.get("posting_date"))
        compact = bool(raw.get("compact") or (request.args.get("view") == "compact"))

        item_id = int(raw["item_id"])
        uom_id = int(raw["uom_id"]) if raw.get("uom_id") is not None else None
        qty = raw.get("qty")

        log.debug("[%s] buying/single company=%s branch=%s item=%s uom=%s",
                  req_id, ctx.company_id, branch_id, item_id, uom_id)

        data = get_buying_rate_basic(
            company_id=ctx.company_id,
            branch_id=branch_id,
            item_id=item_id,
            txn_uom_id=uom_id,     # None → no UOM preference
            qty=qty,
            posting_date=when,
            price_list_id=raw.get("price_list_id"),
            price_list_name=raw.get("price_list_name"),
            supplier_id=raw.get("supplier_id"),
        )
        log.debug("[%s] buying result=%s", req_id, data)
        return api_success(_compactify(data, compact))
    except Exception as e:
        log.exception("[BUYING %s] error: %s", req_id, e)
        return api_error(str(e), status_code=400)
def _parse_date_or_dt(val):
    """
    Accept 'YYYY-MM-DD' or full ISO (with/without 'Z').
    Returns datetime if full, or date if date-only.
    """
    if val is None:
        return None
    s = str(val).strip()
    try:
        if len(s) <= 10 and s.count("-") == 2:  # date-only
            return datetime.fromisoformat(s).date()
        # normalize trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None  # let service re-validate as needed


# ===================== Price Lists =====================
@bp.post("/price-lists/create")
@require_permission("PriceList", "CREATE")
def create_price_list():
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}

        try:
            plc = PriceListCreate.model_validate(raw)
            name = plc.name
            list_type = plc.list_type
            pnu = plc.price_not_uom_dependent
            active = plc.is_active
        except ValidationError as e:
            return api_error(str(e), status_code=422)

        svc = PricingMasterService()
        pl = svc.create_price_list(
            company_id=ctx.company_id,
            name=name,
            list_type=list_type,
            price_not_uom_dependent=pnu,
            is_active=active,
        )
        return api_success({"id": pl.id, "name": pl.name}, "Price List created.", status_code=201)

    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=e.code)
    except ValueError as e:
        # Already clean messages from service (single-line)
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.patch("/price-lists/<int:pl_id>/update")
@require_permission("PriceList", "EDIT")
def update_price_list(pl_id: int):
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}

        name = raw.get("name") or raw.get("price_list_name")
        list_type = raw.get("list_type")
        if list_type is not None:
            try:
                list_type = PriceListUpdate.model_validate({"list_type": list_type}).list_type
            except ValidationError as e:
                return api_error(str(e), status_code=422)

        svc = PricingMasterService()
        pl = svc.update_price_list(
            company_id=ctx.company_id,
            pl_id=pl_id,
            name=name,
            list_type=list_type,
            price_not_uom_dependent=raw.get("price_not_uom_dependent"),
            is_active=raw.get("is_active"),
        )
        return api_success({"id": pl.id, "name": pl.name}, "Price List updated.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except ValueError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


# ===================== Item Prices =====================
@bp.post("/item-prices/create")
@require_permission("ItemPrice", "CREATE")
def create_item_price():
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}

        # Parse flexible date/date-time (service will normalize TZ)
        vf = _parse_date_or_dt(raw.get("valid_from"))
        vu = _parse_date_or_dt(raw.get("valid_upto"))

        # Validate basic structure with Pydantic (no 'code' here)
        try:
            _ = ItemPriceCreate.model_validate({**raw, "valid_from": vf, "valid_upto": vu})
        except ValidationError as e:
            return api_error(str(e), status_code=422)

        svc = PricingMasterService()
        ip = svc.create_item_price(
            company_id=ctx.company_id,
            price_list_id=raw.get("price_list_id"),
            item_id=raw.get("item_id"),
            rate=raw.get("rate"),
            uom_id=raw.get("uom_id"),
            branch_id=raw.get("branch_id"),
            valid_from=vf, valid_upto=vu,
        )
        return api_success({"id": ip.id, "code": ip.code}, "Item Price created.", status_code=201)

    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=e.code)
    except ValueError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.patch("/item-prices/<int:item_price_id>/update")
@require_permission("ItemPrice", "EDIT")
def update_item_price(item_price_id: int):
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}

        # Only rate/validity updatable
        try:
            _ = ItemPriceUpdate.model_validate(raw)
        except ValidationError as e:
            return api_error(str(e), status_code=422)

        vf = _parse_date_or_dt(raw.get("valid_from")) if "valid_from" in raw else None
        vu = _parse_date_or_dt(raw.get("valid_upto")) if "valid_upto" in raw else None

        svc = PricingMasterService()
        ip = svc.update_item_price(
            company_id=ctx.company_id,
            item_price_id=item_price_id,
            rate=raw.get("rate"),
            valid_from=vf, valid_upto=vu,
        )
        return api_success({"id": ip.id, "code": ip.code}, "Item Price updated.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except ValueError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)