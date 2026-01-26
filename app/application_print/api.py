
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, request, g, Response, redirect
from sqlalchemy import select
from werkzeug.exceptions import HTTPException, NotFound

from app.application_print.models import PrintSettings, PrintFormat, PrintLetterhead
from app.application_print.print_config import (
    PrintFormatFieldTemplateUpdate,
    PrintFormatFieldTemplateCreate,
    PrintFormatUpdate,
    PrintFormatCreate,
    PrintSettingsUpdate,
    PrintSettingsCreate,
    PrintLetterheadUpdate,
    PrintLetterheadCreate,
    PrintStyleUpdate,
    PrintStyleCreate,
)
from app.application_print.services.config_service import PrintConfigService
from app.auth.deps import get_current_user
from app.common.api_response import api_error, api_success
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import require_permission

from app.application_print.registry.print_registry import get_print_config, PRINT_REGISTRY
from app.application_print.services.render_service import print_render_service
from config.database import db

log = logging.getLogger(__name__)

bp = Blueprint("prints", __name__, url_prefix="/print")
api_bp = Blueprint("print_api", __name__, url_prefix="/api/print")
config_svc = PrintConfigService()


# ---------------------------------------------------------------------
# DEBUG: log every request that reaches /api/print/*
# ---------------------------------------------------------------------
@api_bp.before_request
def _log_print_requests():
    try:
        log.info(
            "[api/print] %s %s args=%s view_args=%s",
            request.method,
            request.path,
            dict(request.args),
            getattr(request, "view_args", None),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------
# AUTH CONTEXT
# ---------------------------------------------------------------------
def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Unauthorized")
    return ctx


# ---------------------------------------------------------------------
# PERMISSION DECORATOR (FIXED)
# - Uses action "READ" (matches your other endpoints)
# - Avoids passing wrong args into guard wrapper
# ---------------------------------------------------------------------
def require_print_permission(view):
    @wraps(view)
    def wrapper(module: str, entity: str, *args, **kwargs):
        try:
            cfg = get_print_config(module, entity)
        except ValueError:
            return api_error(f"Unknown printable resource: {module}/{entity}.", status_code=404)

        guard = require_permission(cfg.permission_tag, "READ")

        @guard
        def _inner():
            return view(module, entity, *args, **kwargs)

        return _inner()

    return wrapper


# ---------------------------------------------------------------------
# REDIRECT FROM API TO CLEAN URL
# This handles requests that come to /api/print/html/*
# and redirects them to the clean /print/* URL
# ---------------------------------------------------------------------
# @api_bp.get("/html/<module>/<entity>/<identifier>")
# def redirect_to_clean_print(module: str, entity: str, identifier: str):
#     """Redirect API print requests to clean URLs"""
#     try:
#         ctx = _ctx()
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#
#     # Build query parameters
#     query_params = {}
#     if request.args.get("format"):
#         query_params["format"] = request.args.get("format")
#     if request.args.get("page_size"):
#         query_params["page_size"] = request.args.get("page_size")
#     if request.args.get("orientation"):
#         query_params["orientation"] = request.args.get("orientation")
#     if request.args.get("with_letterhead") == "0":
#         query_params["with_letterhead"] = "0"
#     if request.args.get("letterhead_id"):
#         query_params["letterhead_id"] = request.args.get("letterhead_id")
#     if request.args.get("style"):
#         query_params["style"] = request.args.get("style")
#
#     # Build the clean URL
#     base_url = f"/print/{module}/{entity}/{identifier}"
#     if query_params:
#         from urllib.parse import urlencode
#         query_string = urlencode(query_params)
#         clean_url = f"{base_url}?{query_string}"
#     else:
#         clean_url = base_url
#
#     log.info(f"Redirecting API print request to clean URL: {clean_url}")
#     return redirect(clean_url)
@bp.get("/<module>/<entity>/<identifier>")
@require_print_permission
def print_document(module: str, entity: str, identifier: str):
    try:
        ctx = _ctx()

        format_code = request.args.get("format") or request.args.get("print_format")
        page_size = request.args.get("page_size") or "A4"
        orientation = request.args.get("orientation") or "Portrait"
        with_letterhead = request.args.get("with_letterhead", "1") != "0"
        letterhead_id = request.args.get("letterhead_id", type=int)
        style_code = request.args.get("style")

        log.info(
            "[print_document] module=%s entity=%s id=%s format=%s page_size=%s orientation=%s with_letterhead=%s letterhead_id=%s style=%s",
            module, entity, identifier, format_code, page_size, orientation, with_letterhead, letterhead_id, style_code
        )

        html = print_render_service.render_document(
            module=module,
            entity=entity,
            identifier=identifier,
            ctx=ctx,
            format_code=format_code,
            letterhead_id=letterhead_id,
            with_letterhead=with_letterhead,
            style_code=style_code,
            page_size=page_size,
            orientation=orientation,
        )
        return Response(html, mimetype="text/html")

    except Exception as e:
        log.exception("Unhandled error in print_document")
        return Response(
            f"<h1>Print Error</h1><pre>{e}</pre>",
            status=500,
            mimetype="text/html",
        )


@api_bp.get("/options")
def get_ui_print_options():
    try:
        ctx = _ctx()
    except PermissionError:
        return api_error("Unauthorized", status_code=401)

    module = (request.args.get("module") or "").strip()
    entity = (request.args.get("entity") or "").strip()
    if not module or not entity:
        return api_error("module and entity are required", status_code=422)

    try:
        cfg = get_print_config(module, entity)
    except ValueError:
        return api_error(f"Unknown printable resource: {module}/{entity}.", status_code=404)

    company_id = getattr(ctx, "company_id", None)

    # ---- letterheads (company only) ----
    letterheads = []
    default_letterhead_id = None
    if company_id:
        q_lh = (
            db.session.query(PrintLetterhead)
            .filter(
                PrintLetterhead.company_id == company_id,
                PrintLetterhead.is_disabled.is_(False),
            )
            .order_by(PrintLetterhead.is_default_for_company.desc(), PrintLetterhead.id.asc())
        )
        for lh in q_lh.all():
            if lh.is_default_for_company and default_letterhead_id is None:
                default_letterhead_id = lh.id
            letterheads.append(
                {
                    "id": lh.id,
                    "name": lh.name,
                    "code": lh.code,
                    "is_default": bool(lh.is_default_for_company),
                }
            )

    # ---- formats (company + global) ----
    from sqlalchemy import or_
    q_pf = (
        db.session.query(PrintFormat)
        .filter(
            PrintFormat.doctype == cfg.doctype,
            PrintFormat.is_disabled.is_(False),
        )
    )
    if company_id:
        q_pf = q_pf.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
    else:
        q_pf = q_pf.filter(PrintFormat.company_id.is_(None))

    q_pf = q_pf.order_by(
        PrintFormat.company_id.is_(None).asc(),   # company first
        PrintFormat.is_default_for_doctype.desc(),
        PrintFormat.is_standard.desc(),
        PrintFormat.id.asc(),
    )

    formats = []
    default_format_code = None
    for pf in q_pf.all():
        if pf.is_default_for_doctype and default_format_code is None:
            default_format_code = pf.code
        formats.append(
            {
                "id": pf.id,
                "name": pf.name,
                "code": pf.code,
                "is_default": bool(pf.is_default_for_doctype),
            }
        )

    # ---- settings default page size ----
    page_size = "A4"
    settings = None
    if company_id:
        settings = db.session.scalar(select(PrintSettings).where(PrintSettings.company_id == company_id).limit(1))
    if not settings:
        settings = db.session.scalar(select(PrintSettings).where(PrintSettings.company_id.is_(None)).limit(1))
    if settings and settings.pdf_page_size:
        page_size = settings.pdf_page_size

    payload = {
        "letterheads": letterheads,
        "print_formats": formats,
        "page_sizes": ["A4", "A5", "Letter", "Legal"],
        "defaults": {
            "letterhead_id": default_letterhead_id,
            "print_format_code": default_format_code,
            "page_size": page_size,
        },
        "meta": {"doctype": cfg.doctype},
    }
    return api_success(data=payload, message="Success", status_code=200)


# ---------------------------------------------------------------------
# JSON PREVIEW  /api/print/preview/<path>/<id>
# ---------------------------------------------------------------------

@api_bp.get("/preview/<path:doctype_path>/<identifier>")
def print_preview(doctype_path: str, identifier: str):
    try:
        ctx = _ctx()
    except PermissionError:
        return api_error("Unauthorized", status_code=401)

    parts = doctype_path.split('/')

    if len(parts) == 2:
        module, entity = parts[0], parts[1]
        try:
            cfg = get_print_config(module, entity)
        except ValueError:
            return api_error(f"Unknown printable resource: {module}/{entity}", status_code=404)
    else:
        needle = "".join(ch for ch in doctype_path if ch.isalnum()).lower()
        target = None
        for mod, entities in PRINT_REGISTRY.items():
            for ent, c in entities.items():
                lbl = "".join(ch for ch in (getattr(c, "doctype", "") or "") if ch.isalnum()).lower()
                if lbl == needle:
                    target = (mod, ent, c)
                    break
            if target:
                break
        if not target:
            return api_error(f"Unknown printable doctype: {doctype_path}", status_code=404)
        module, entity, cfg = target

    guard = require_permission(cfg.permission_tag, "READ")

    @guard
    def _inner():
        format_code = request.args.get("format") or request.args.get("print_format")
        page_size = request.args.get("page_size") or "A4"
        orientation = request.args.get("orientation") or "Portrait"
        with_letterhead = request.args.get("with_letterhead", "1") != "0"
        letterhead_id = request.args.get("letterhead_id", type=int)
        style_code = request.args.get("style")

        try:
            html = print_render_service.render_document(
                module=module,
                entity=entity,
                identifier=identifier,
                ctx=ctx,
                format_code=format_code,
                letterhead_id=letterhead_id,
                with_letterhead=with_letterhead,
                style_code=style_code,
                page_size=page_size,
                orientation=orientation,
            )

            return api_success(
                data={
                    "doctype": cfg.doctype,
                    "name": identifier,
                    "html": html,
                    "meta": {
                        "page_size": page_size,
                        "orientation": orientation,
                        "with_letterhead": with_letterhead,
                        "letterhead_id": letterhead_id,
                        "style": style_code,
                    },
                },
                message="Success",
                status_code=200,
            )

        except Exception as e:
            log.exception("Unhandled error in print_preview")
            return api_error(f"Unable to render preview: {e}", status_code=500)

    return _inner()

# ---------------------------------------------------------------------
# HTML INSIDE /api  (THIS IS WHAT YOU OPEN IN NEW TAB)
# /api/print/html/<module>/<entity>/<identifier>
# ---------------------------------------------------------------------
@api_bp.get("/html/<module>/<entity>/<identifier>")
@require_print_permission
def print_document_html_api(module: str, entity: str, identifier: str):
    try:
        ctx = _ctx()

        format_code = request.args.get("format") or request.args.get("print_format")
        page_size = request.args.get("page_size") or "A4"
        orientation = request.args.get("orientation") or "Portrait"
        with_letterhead = request.args.get("with_letterhead", "1") != "0"
        letterhead_id = request.args.get("letterhead_id", type=int)
        style_code = request.args.get("style")

        log.info(
            "[print_html] module=%s entity=%s id=%s format=%s page_size=%s orientation=%s with_letterhead=%s letterhead_id=%s style=%s",
            module, entity, identifier, format_code, page_size, orientation, with_letterhead, letterhead_id, style_code
        )

        html = print_render_service.render_document(
            module=module,
            entity=entity,
            identifier=identifier,
            ctx=ctx,
            format_code=format_code,
            letterhead_id=letterhead_id,
            with_letterhead=with_letterhead,
            style_code=style_code,
            page_size=page_size,
            orientation=orientation,
        )
        return Response(html, mimetype="text/html")

    except Exception as e:
        log.exception("Unhandled error in print_document_html_api")
        return Response(
            f"<h1>Print Error</h1><pre>{e}</pre>",
            status=500,
            mimetype="text/html",
        )

