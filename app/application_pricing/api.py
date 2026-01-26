from __future__ import annotations

import uuid
import logging
from datetime import datetime, date
from typing import Optional, Any

from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound, Conflict

from config.database import db
from app.common.api_response import api_success, api_error

from app.auth.deps import get_current_user
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission, resolve_company_branch_and_scope

from app.navigation_workspace.services.subscription_guards import check_workspace_subscription
from app.common.timezone.service import get_company_timezone, ensure_aware, to_utc, company_posting_dt
from app.common.date_utils import parse_date_flex

from app.application_org.models.company import Branch
from app.application_pricing.pricing_schemas import PriceListCreate, PriceListUpdate, ItemPriceCreate, ItemPriceUpdate
from app.application_pricing.services.pricing_master_service import PricingMasterService
from app.application_pricing.services.pricing_rate_service import get_rate_batch, RateLine

log = logging.getLogger(__name__)
bp = Blueprint("pricing", __name__, url_prefix="/api/pricing")

WORKSPACE_SLUG = "inventory"
WORKSPACE_SUBSCRIPTION_EXEMPT_ENDPOINTS: set[str] = set()


@bp.before_request
def _guard_workspace_subscription():
    if request.method == "OPTIONS":
        return
    if request.endpoint in WORKSPACE_SUBSCRIPTION_EXEMPT_ENDPOINTS:
        return
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        return api_error("Authentication required.", status_code=401)
    ok, msg = check_workspace_subscription(ctx, workspace_slug=WORKSPACE_SLUG)
    if not ok:
        return api_error(msg, status_code=403)


def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx


def _get_branch_company_id(branch_id: int) -> Optional[int]:
    row = db.session.execute(db.select(Branch.company_id).where(Branch.id == int(branch_id)).limit(1)).first()
    return int(row[0]) if row and row[0] is not None else None


def _parse_posting_dt_any(company_id: int, val: Any) -> Optional[datetime]:
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip()

    try:
        ss = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(ss)
        tz = get_company_timezone(db.session, company_id)
        dt_local = ensure_aware(dt, tz)
        return to_utc(dt_local)
    except Exception:
        pass

    d: Optional[date] = parse_date_flex(s)
    if d is not None:
        dt_local = company_posting_dt(db.session, company_id, d)
        return to_utc(dt_local)

    return None


@bp.post("/get-rate")
@require_permission("Item", "READ")
def rate():
    req_id = uuid.uuid4().hex[:8]
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}

        kind = (raw.get("kind") or "selling").lower().strip()
        if kind not in ("selling", "buying"):
            return api_error("kind must be 'selling' or 'buying'", status_code=422)

        payload_company_id = raw.get("company_id")
        branch_id = raw.get("branch_id")
        branch_id = int(branch_id) if branch_id is not None else None

        company_id, branch_id = resolve_company_branch_and_scope(
            context=ctx,
            payload_company_id=int(payload_company_id) if payload_company_id is not None else None,
            branch_id=branch_id,
            get_branch_company_id=_get_branch_company_id,
            require_branch=False,
        )

        warehouse_id = raw.get("warehouse_id")
        warehouse_id = int(warehouse_id) if warehouse_id is not None else None

        posting_dt_utc = _parse_posting_dt_any(company_id, raw.get("posting_date"))

        view = (raw.get("view") or request.args.get("view") or "full").lower().strip()

        if isinstance(raw.get("items"), list):
            items = []
            for i, it in enumerate(raw["items"]):
                if "item_id" not in it:
                    return api_error("items[].item_id is required", status_code=422)
                items.append(RateLine(
                    row_id=str(it.get("row_id") or f"row{i+1}"),
                    item_id=int(it["item_id"]),
                    uom_id=int(it["uom_id"]) if it.get("uom_id") is not None else None,
                    qty=float(it["qty"]) if it.get("qty") is not None else None,
                ))
        else:
            if raw.get("item_id") is None:
                return api_error("item_id is required (or send items[])", status_code=422)
            items = [RateLine(
                row_id="row1",
                item_id=int(raw["item_id"]),
                uom_id=int(raw["uom_id"]) if raw.get("uom_id") is not None else None,
                qty=float(raw["qty"]) if raw.get("qty") is not None else None,
            )]

        eff_pl_id, rows = get_rate_batch(
            company_id=company_id,
            kind=kind,
            branch_id=branch_id,
            warehouse_id=warehouse_id,
            items=items,
            posting_date=posting_dt_utc,
            price_list_id=raw.get("price_list_id"),
            price_list_name=raw.get("price_list_name"),
            customer_id=raw.get("customer_id"),
            supplier_id=raw.get("supplier_id"),
            allow_default_price_list_fallback=True,
            allow_last_selling_rate_fallback=True,
            context=ctx,
        )

        if view == "compact":
            payload_items = [{"row_id": r["row_id"], "item_id": r["item_id"], "uom_id": r["uom_id"], "rate": r["rate"], "source": r["source"]} for r in rows]
        else:
            payload_items = rows

        return api_success({
            "kind": kind,
            "company_id": int(company_id),
            "branch_id": int(branch_id) if branch_id is not None else None,
            "price_list_id": int(eff_pl_id or 0),
            "items": payload_items if len(items) > 1 else payload_items[0],
        })

    except (BadRequest, ValidationError):
        log.exception("[%s] pricing.rate bad request", req_id)
        return api_error("Invalid request.", status_code=422)
    except (Forbidden, NotFound) as e:
        log.exception("[%s] pricing.rate scope error", req_id)
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 403))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        log.exception("[%s] pricing.rate unexpected error", req_id)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/price-lists/create")
@require_permission("Price List", "CREATE")
def create_price_list():
    try:
        ctx = _ctx()
        payload = PriceListCreate.model_validate(request.get_json(silent=True) or {})

        svc = PricingMasterService()
        ok, msg, pl = svc.create_price_list(payload=payload, context=ctx)
        if not ok or not pl:
            return api_error(msg, status_code=400)

        return api_success({"id": pl.id, "name": pl.name}, msg, status_code=201)

    except ValidationError:
        return api_error("Invalid request.", status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        log.exception("create_price_list failed")
        return api_error("Unexpected error.", status_code=500)


@bp.put("/price-lists/<int:price_list_id>/update")
@require_permission("Price List", "UPDATE")
def update_price_list(price_list_id: int):
    try:
        ctx = _ctx()
        payload = PriceListUpdate.model_validate(request.get_json(silent=True) or {})

        svc = PricingMasterService()
        ok, msg, pl = svc.update_price_list(price_list_id=price_list_id, payload=payload, context=ctx)
        if not ok or not pl:
            return api_error(msg, status_code=400)

        return api_success({"id": pl.id, "name": pl.name}, msg, status_code=200)

    except ValidationError:
        return api_error("Invalid request.", status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        log.exception("update_price_list failed")
        return api_error("Unexpected error.", status_code=500)


@bp.post("/item-prices/create")
@require_permission("Item Price", "CREATE")
def create_item_price():
    try:
        ctx = _ctx()
        payload = ItemPriceCreate.model_validate(request.get_json(silent=True) or {})

        svc = PricingMasterService()
        ok, msg, ip = svc.create_item_price(payload=payload, context=ctx)
        if not ok or not ip:
            return api_error(msg, status_code=400)

        return api_success({"id": ip.id, "code": ip.code}, msg, status_code=201)

    except ValidationError:
        return api_error("Invalid request.", status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        log.exception("create_item_price failed")
        return api_error("Unexpected error.", status_code=500)


@bp.put("/item-prices/<int:item_price_id>/update")
@require_permission("Item Price", "UPDATE")
def update_item_price(item_price_id: int):
    try:
        ctx = _ctx()
        payload = ItemPriceUpdate.model_validate(request.get_json(silent=True) or {})

        svc = PricingMasterService()
        ok, msg, ip = svc.update_item_price(item_price_id=item_price_id, payload=payload, context=ctx)
        if not ok or not ip:
            return api_error(msg, status_code=400)

        return api_success({"id": ip.id, "code": ip.code}, msg, status_code=200)

    except ValidationError:
        return api_error("Invalid request.", status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        log.exception("update_item_price failed")
        return api_error("Unexpected error.", status_code=500)
