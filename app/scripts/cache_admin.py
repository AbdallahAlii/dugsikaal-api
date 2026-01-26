# app/scripts/cache_admin.py
from __future__ import annotations
import os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from app.common.cache.cache_invalidator import bump_all_cache

app = create_app()
with app.app_context():
    bump_all_cache()
    print("✅ All caches invalidated (epoch bumped).")
