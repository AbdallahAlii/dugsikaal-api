# app/core/auth.py
from flask import g, jsonify, request

def public(view):
    """Mark a view as public (no login required)."""
    view.__public__ = True
    return view

def require_login_globally(app):
    """
    Enforce login on ALL endpoints unless decorated with @public.
    Uses g.current_user loaded by the session middleware.
    """
    @app.before_request
    def _global_login_gate():
        # Always allow CORS preflight and static files
        if request.method == "OPTIONS" or request.endpoint == "static":
            return

        # If the view exists and is marked public, allow
        view = app.view_functions.get(request.endpoint)
        if view and getattr(view, "__public__", False):
            return

        # Otherwise require login
        if getattr(g, "current_user", None) is None:
            return jsonify({"message": "Authentication required."}), 401
