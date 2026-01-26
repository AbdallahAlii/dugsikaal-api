from __future__ import annotations

from flask import Flask

from app.application_print.api import bp as print_bp, api_bp as print_api_bp


def init_app(app: Flask) -> None:
    """
    Register print blueprints (HTML + JSON).
    """
    app.register_blueprint(print_bp)       # /print/...
    app.register_blueprint(print_api_bp)   # /api/print/...
