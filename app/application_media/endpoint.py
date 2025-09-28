from __future__ import annotations

import base64
import hashlib
import hmac
import time
from http import HTTPStatus
import re
from typing import Optional

from flask import Blueprint, Response, abort, request, send_from_directory

from app.common.api_response import api_success
from app.security.rbac_guards import require_permission
from config.media_config import settings
from config.settings import settings as app_settings  # reuse your app SECRET_KEY
from .encrypted_media import download_and_decrypt, image_url_from_key

media_bp = Blueprint("media_stream", __name__, url_prefix="/api/media")

# -------------------------------------------------------------------
# Key safety: only allow characters we generate for keys. Block "../".
# -------------------------------------------------------------------
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._/\-]+$")

def _assert_safe_key(k: str) -> None:
    if not _SAFE_KEY.fullmatch(k) or ".." in k or k.startswith("/"):
        abort(HTTPStatus.BAD_REQUEST)

# -------------------------------------------------------------------
# Cookie + RBAC path: requires session cookie and File:Read permission
# -------------------------------------------------------------------
@media_bp.get("/img/<path:img_key>")
@require_permission("File", "Read")
def stream_image(img_key: str):
    """
    Decrypts and streams an image with the correct MIME type.
    Intended for <img src="/api/media/img/<img_key>"> when the cookie is sent.
    """
    _assert_safe_key(img_key)
    try:
        raw_bytes, mime_type = download_and_decrypt(img_key)
    except FileNotFoundError:
        abort(HTTPStatus.NOT_FOUND)
    except Exception:
        abort(HTTPStatus.INTERNAL_SERVER_ERROR)

    resp = Response(raw_bytes, mimetype=mime_type)
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "private, max-age=300"  # tighten to "no-store" if needed
    return resp

@media_bp.get("/url/<path:img_key>")
@require_permission("File", "Read")
def get_image_url(img_key: str):
    """
    Returns a JSON payload with the URL of the cookie+RBAC streaming endpoint.
    """
    _assert_safe_key(img_key)
    url = image_url_from_key(img_key)  # e.g. "/api/media/img/<img_key>"
    return api_success(data={"url": url})

# -------------------------------------------------------------------
# Token-signed URLs: for HTTP cross-origin where cookies won't attach
# -------------------------------------------------------------------

# Use a dedicated signing secret if you have it; else fall back to app SECRET_KEY
_SIGNING_SECRET = (getattr(app_settings, "SECRET_KEY", None) or "dev-secret").encode("utf-8")

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("utf-8")

def _b64u_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)

def _make_token(img_key: str, exp_ts: int) -> str:
    data = f"{img_key}|{exp_ts}".encode("utf-8")
    mac = hmac.new(_SIGNING_SECRET, data, hashlib.sha256).digest()
    return f"{_b64u(mac)}.{exp_ts}"

def _verify_token(img_key: str, token: str) -> bool:
    try:
        sig_b64, exp_s = token.split(".", 1)
        exp_ts = int(exp_s)
    except Exception:
        return False
    if exp_ts < int(time.time()):
        return False
    data = f"{img_key}|{exp_ts}".encode("utf-8")
    mac = hmac.new(_SIGNING_SECRET, data, hashlib.sha256).digest()
    return hmac.compare_digest(_b64u(mac), sig_b64)

@media_bp.get("/presign/<path:img_key>")
@require_permission("File", "Read")
def presign_image(img_key: str):
    """
    Returns a short-lived, signed URL that does NOT require cookies.
    Use when your frontend is on a different origin over HTTP.
    """
    _assert_safe_key(img_key)
    try:
        ttl = int(request.args.get("ttl", 300))
    except Exception:
        ttl = 300
    ttl = max(30, min(ttl, 3600))  # clamp 30s..1h

    exp = int(time.time()) + ttl
    token = _make_token(img_key, exp)
    signed_url = f"/api/media/img-signed/{img_key}?t={token}"
    return api_success(data={"url": signed_url, "expires_at": exp})

@media_bp.get("/img-signed/<path:img_key>")
def stream_image_signed(img_key: str):
    """
    Decrypts and streams an image if the 't' token is valid (no cookie needed).
    Intended for <img src="/api/media/img-signed/<img_key>?t=..."> on HTTP cross-origin.
    """
    _assert_safe_key(img_key)
    token = request.args.get("t")
    if not token or not _verify_token(img_key, token):
        abort(HTTPStatus.FORBIDDEN)

    try:
        raw_bytes, mime_type = download_and_decrypt(img_key)
    except FileNotFoundError:
        abort(HTTPStatus.NOT_FOUND)
    except Exception:
        abort(HTTPStatus.INTERNAL_SERVER_ERROR)

    resp = Response(raw_bytes, mimetype=mime_type)
    resp.headers["Content-Disposition"] = "inline"
    # Signed URLs may be cached privately while valid
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp

# ---- DEV ONLY: serve encrypted files from disk when MEDIA_BACKEND=local
if settings.MEDIA_BACKEND.lower() == "local":
    @media_bp.get("/_debug/raw/<path:filename>")
    def serve_media_local(filename):
        _assert_safe_key(filename)
        return send_from_directory(settings.LOCAL_MEDIA_ROOT, filename)
