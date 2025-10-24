
# app/auth/endpoints.py
from __future__ import annotations
from flask import Blueprint, request, g,session,  make_response, current_app
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException
from app.auth.deps import get_current_user
from app.auth.service.me_service import profile_service
from app.auth.service.user_service import UserService
from app.common.api_response import api_error, api_success
from app.common.decorators import rate_limit
from app.common.timezone.service import get_company_timezone
from app.security.rbac_effective import AffiliationContext
from config.database import db
from core.auth import public
from app.auth.service.auth_service import AuthService
from app.auth.schemas import LoginRequest, ChangeMyPasswordRequest, ResetPasswordRequest, UpdateAccountStatusRequest
from app.security.rbac_guards import require_permission
bp = Blueprint("auth", __name__, url_prefix="/api/auth")
svc = AuthService()
user_svc = UserService()


@bp.post("/login")
@public
@rate_limit(key_prefix="login", limit=5, window=60, include_username=True)
def login():
    payload = request.get_json(silent=True) or {}
    try:
        req = LoginRequest(**payload)
    except Exception as e:
        return api_error(f"Invalid request: {e}", status_code=400)

    ok, msg, profile = svc.login(req.username, req.password)
    if not ok:
        return api_error(msg, status_code=401)

    # REMOVE THIS LINE:
    # g.current_user = profile

    return api_success(message=msg, data={"user": profile})

@bp.post("/logout")
@public
@rate_limit(key_prefix="logout", limit=10, window=60)  # optional, but nice
def logout():
    # 1) Service-level cleanup (Redis, audit log, SSO, etc.)
    ok, message = svc.logout()

    # 2) Always clear Flask session memory
    session.clear()
    session.permanent = False

    # 3) Expire cookies on the client
    resp = make_response(
        api_success(message=message if ok else "Logged out", data={})
        if ok else api_error(message=message or "Logout failed", status_code=500)
    )
    cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    cookie_domain = current_app.config.get("SESSION_COOKIE_DOMAIN", None)
    cookie_path = current_app.config.get("SESSION_COOKIE_PATH", "/")
    resp.delete_cookie(cookie_name, domain=cookie_domain, path=cookie_path)

    # If you set a CSRF cookie, expire it too (optional, if applicable)
    csrf_name = current_app.config.get("CSRF_COOKIE_NAME", None)
    if csrf_name:
        resp.delete_cookie(csrf_name, domain=cookie_domain, path="/")

    return resp


# @bp.get("/me")
# def me():
#     # This line is correct and will now work properly
#     # because the other checks are in place.
#     user_profile = get_current_user()
#
#     return api_success(data={"user": user_profile})
@bp.get("/me")
def me():
    # ensures session & sets g.current_user / g.auth
    user_profile = get_current_user()
    ctx: AffiliationContext | None = getattr(g, "auth", None)

    tz = "Africa/Mogadishu"
    try:
        if ctx and getattr(ctx, "company_id", None):
            tz = str(get_company_timezone(db.session, int(ctx.company_id)))
    except Exception:
        # keep default on any failure
        tz = "Africa/Mogadishu"

    # ⬇️ include company_timezone alongside user
    return api_success(data={"user": user_profile, "company_timezone": tz})



@bp.get("/me/profile")
def me_profile():
    # Ensure authenticated user & g.auth context (may be host-level with no company)
    user_profile = get_current_user()  # ensures session and sets g.current_user/g.auth
    ctx: AffiliationContext | None = getattr(g, "auth", None)

    user_id = int(user_profile.get("user_id") or user_profile.get("id"))

    # Allow host-level (system admin) profiles when no company context is present
    company_id = int(ctx.company_id) if (ctx and getattr(ctx, "company_id", None) is not None) else None
    branch_id = int(ctx.branch_id) if (ctx and getattr(ctx, "branch_id", None) is not None) else None

    data = profile_service.get_me_profile(
        user_id=user_id,
        company_id=company_id,
        branch_id=branch_id,
    )

    if not data:
        # If nothing came back, respond 404 (but service already falls back for host admins)
        return api_error("Profile not found.", status_code=404)

    return api_success(data=data)




# ---- self-service: change my password ----
@bp.patch("/me/password/change")
@rate_limit(key_prefix="change_my_password", limit=5, window=60)
def change_my_password():
    user = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = ChangeMyPasswordRequest(**payload)
        msg = user_svc.change_my_password_service(
            int(user.get("user_id") or user.get("id")),
            req.old_password,
            req.new_password,
        )
        return api_success(message=msg, data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except ValidationError as e:
        return api_error(f"Invalid request: {e}", status_code=400)
    except Exception as e:
        return api_error(f"An unexpected error occurred: {e}", status_code=500)

# ---- admin: reset user's password (permission + scope via g.auth from middleware) ----
@bp.patch("/users/<int:user_id>/password/change")
@require_permission(doctype="User", action="Manage Password")
def reset_user_password(user_id: int):
    _ = get_current_user()  # ensures session; middleware already attached g.auth
    payload = request.get_json(silent=True) or {}
    try:
        req = ResetPasswordRequest(**payload)
        msg = user_svc.reset_user_password_service(user_id, req.new_password, g.auth)  # use g.auth directly
        return api_success(message=msg, data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except ValidationError as e:
        return api_error(f"Invalid request: {e}", status_code=400)
    except Exception as e:
        return api_error(f"An unexpected error occurred: {e}", status_code=500)

# ---- admin: update user's account status ----
@bp.patch("/users/<int:user_id>/status/update")
@require_permission(doctype="User", action="Manage Status")
def update_user_account_status(user_id: int):
    _ = get_current_user()
    payload = request.get_json(silent=True) or {}
    try:
        req = UpdateAccountStatusRequest(**payload)
        msg = user_svc.update_account_status_service(user_id, req.new_status, g.auth)  # use g.auth directly
        return api_success(message=msg, data={})
    except HTTPException as e:
        return api_error(e.description or str(e), status_code=e.code or 400)
    except ValidationError as e:
        return api_error(f"Invalid request: {e}", status_code=400)
    except Exception as e:
        return api_error(f"An unexpected error occurred: {e}", status_code=500)