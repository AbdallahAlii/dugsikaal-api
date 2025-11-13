# application_data_import/__init__.py
from __future__ import annotations

# Kept minimal on purpose. The app factory in app/__init__.py registers blueprints.
# This package exposes only the registry-loader convenience for early imports.

def ready() -> bool:
    return True
