# app/common/cache/local_cache.py
from __future__ import annotations
from flask import g

def get_local_cache() -> dict:
    """
    Per-request memory cache (Frappe's frappe.local.cache equivalent).
    Resets automatically on request teardown.
    """
    lc = getattr(g, "_local_cache", None)
    if lc is None:
        lc = {}
        setattr(g, "_local_cache", lc)
    return lc

def clear_local_cache() -> None:
    """Manually clear the per-request cache (normally done in app teardown)."""
    if hasattr(g, "_local_cache"):
        g._local_cache.clear()

