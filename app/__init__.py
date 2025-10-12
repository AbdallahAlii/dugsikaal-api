# app/__init__.py
import logging
from datetime import timedelta
from flask import Flask, jsonify
from flask_session import Session
from flask_cors import CORS
import importlib

from sqlalchemy.orm import relationship
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from app.common.api_response import api_error
from app.common.cache.local_cache import clear_local_cache
from app.logging_config import configure_logging
from config.settings import settings
from config.database import db, migrate, db_healthcheck
from config.redis_config import get_redis_raw, ping_redis
from app.application_media.utils import ensure_local_media_folders
from core.middleware.request_id import before_request_request_id, after_request_request_id
# from core.middleware.session_auth import before_request_session_user
from core.middleware.session_auth import before_request_session_auth
from core.middleware.security_headers import after_request_security_headers
from core.auth import require_login_globally, public

# ---- CRITICAL: IMPORT MODELS FIRST USING CENTRAL REGISTRY ----
from app.models_registry import *  # This imports all models via the central registry


# Configure logging
configure_logging("DEBUG")  # You can change the log level as per your environment

def create_app() -> Flask:
    app = Flask(__name__)

    from app.cli.seed_command import seed_cli
    app.cli.add_command(seed_cli)
    # ---- Core config ----
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ---- Sessions (Redis-backed) ----

    app.config.update(
        SESSION_TYPE="redis",
        SESSION_REDIS=get_redis_raw(),
        SESSION_PERMANENT=True,
        SESSION_USE_SIGNER=True,
        SESSION_KEY_PREFIX="erp_session:",
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=settings.SESSION_COOKIE_MAX_AGE),
        SESSION_COOKIE_NAME=settings.SESSION_COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=settings.SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SECURE=settings.cookie_secure_effective,  # false in dev
        SESSION_COOKIE_SAMESITE=settings.cookie_samesite_effective,  # "lax" in your env
        SESSION_COOKIE_DOMAIN=settings.SESSION_COOKIE_DOMAIN,
    )
    Session(app)


    app.logger.info("✓ All models imported via central registry")
    # ---- DB ----
    db.init_app(app)
    # 1) models first
    importlib.import_module("app.models")
    # 2) migrate.init_app
    migrate.init_app(app, db)
    # 3) auto-register lists, details, dropdowns for every application_* package
    from core.module_autoreg import autoregister_all
    autoregister_all()


    # # ✅ THIS IS THE FIX: Call the registration function after models are loaded.
    # from app.application_hr import register_module_lists
    # register_module_lists()
    # from app.application_nventory import register_module_lists as register_inventory_lists
    # register_inventory_lists()
    # from app.application_nventory import register_module_details as register_inventory_detail_configs
    # register_inventory_detail_configs()
    # from app.application_buying import register_module_lists as register_buying_lists
    #
    # register_buying_lists()
    # from app.application_buying import register_module_details as register_buying_detail_configs
    # register_buying_detail_configs()


    # ---- CORS (allow credentials for session cookie) ----
    CORS(
        app,
        supports_credentials=True,  # Allow cookies to be sent with cross-origin requests
        origins=["http://localhost:5173", "http://localhost:2000"],  # Adjust based on your frontend URLs
        allow_headers=["Content-Type", "Authorization", "Cookie"],  # Allow the Cookie header
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    # ---- GLOBAL MIDDLEWARE HOOKS (run on every request/response)
    app.before_request(before_request_request_id)
    app.before_request(before_request_session_auth)
    app.after_request(after_request_request_id)
    app.after_request(after_request_security_headers)

    # ---- CACHE TEARDOWN HOOK ----
    @app.teardown_request
    def _clear_cache_on_teardown(exc):
        try:
            clear_local_cache()
        except Exception:
            pass
    # ---- GLOBAL EXCEPTION HANDLERS ----

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        # Preserve the HTTP status (e.g., 403 Forbidden from ensure_scope_by_ids)
        return api_error(e.description or e.name, status_code=e.code)

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(e: IntegrityError):
        # Always rollback on DB conflicts to keep the session clean
        db.session.rollback()
        return api_error("Database conflict.", status_code=409)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        # Log full traceback; present a safe message to clients
        app.logger.exception("Unhandled error", exc_info=True)
        return api_error("Internal server error.", status_code=500)

    # ---- Ensure local media folders exist ----
    ensure_local_media_folders()
    # ---- Require login by default; mark selected views @public
    require_login_globally(app)
    # ---- Health endpoints ----
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.get("/ready")
    def ready():
        return jsonify({"status": "ready", "db": db_healthcheck(), "redis": ping_redis()}), 200

    # ---- Register blueprints here  ----
    from app.auth.endpoints import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    from app.application_hr.endpoints import bp as hr_bp
    app.register_blueprint(hr_bp, url_prefix="/api/hr")
    from app.application_rbac.endpoints import bp as rbac_bp
    app.register_blueprint(rbac_bp, url_prefix="/api/rbac")

    from app.application_reports.routes import bp as reports_bp
    app.register_blueprint(reports_bp)
    from app.application_accounting.endpoints import  bp as accounting_bp
    app.register_blueprint(accounting_bp)
    from app.application_media.endpoint import media_bp
    app.register_blueprint(media_bp)  # This will register at /api/media

    from app.application_nventory.endpoints import bp as inventory_bp
    app.register_blueprint(inventory_bp, url_prefix="/api/inventory")

    from app.application_parties.endpoints import bp as parties_bp
    app.register_blueprint(parties_bp, url_prefix="/api/parties")

    from app.application_buying.endpoints import bp as buying_bp
    app.register_blueprint(buying_bp, url_prefix="/api/buying")
    from app.application_stock.endpoints import bp as stock_bp
    app.register_blueprint(stock_bp, url_prefix="/api/stock")
    from app.application_sales.endpoints import bp as sales_bp
    app.register_blueprint(sales_bp, url_prefix="/api/sales")
    from app.navigation_workspace.endpoints import bp as nav_workspace_bp
    app.register_blueprint(nav_workspace_bp , url_prefix="/api/navigation")
    from app.application_doctypes.endpoint import docypelist_bp
    from app.application_doctypes.core_dropdowns.endpoint import dropdowns_bp
    app.register_blueprint(dropdowns_bp)

    app.register_blueprint(docypelist_bp)


    return app
