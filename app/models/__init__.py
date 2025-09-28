# app/models/__init__.py
from __future__ import annotations
import importlib
import pkgutil
from types import ModuleType

# Scan direct children of "app" (e.g. app/auth, app/rbac, app/users, ...)
BASE_PACKAGE = "app"

def _import_all_submodules_of(pkg_mod: ModuleType) -> int:
    """If pkg_mod is a package, import all its submodules recursively."""
    count = 0
    if hasattr(pkg_mod, "__path__"):  # it's a package
        for _, subname, _ in pkgutil.walk_packages(pkg_mod.__path__, pkg_mod.__name__ + "."):
            importlib.import_module(subname)
            count += 1
    return count

def _import_models_for(child_pkg_qualname: str) -> int:
    """
    Try to import "<child>.models" (preferred) or "<child>.model" (fallback).
    If it's a package, also import all its modules (e.g., company.py, branch.py, ...).
    """
    count = 0
    # 1) app.<child>.models
    try:
        models_mod = importlib.import_module(f"{child_pkg_qualname}.models")
        count += 1
        count += _import_all_submodules_of(models_mod)
        return count
    except ModuleNotFoundError:
        pass

    # 2) optional fallback: app.<child>.model (only if you ever used singular)
    try:
        model_mod = importlib.import_module(f"{child_pkg_qualname}.model")
        count += 1
        count += _import_all_submodules_of(model_mod)
        return count
    except ModuleNotFoundError:
        return 0

def _import_under_app() -> int:
    """
    For each immediate package under 'app' (auth, rbac, users, ...),
    import its 'models' (and all submodules) if present.
    """
    try:
        app_pkg = importlib.import_module(BASE_PACKAGE)
    except ModuleNotFoundError:
        return 0

    imported = 0
    for _, child_qualname, ispkg in pkgutil.iter_modules(app_pkg.__path__, BASE_PACKAGE + "."):
        # Skip ourselves (app.models) to avoid trying app.models.models
        if not ispkg or child_qualname.endswith(".models"):
            continue
        imported += _import_models_for(child_qualname)
    return imported

# Run once when you do `import app.models`
_IMPORTED_MODELS_COUNT = _import_under_app()
