# # core/module_autoreg.py
# from __future__ import annotations
# import importlib
# import logging
# import pkgutil
# from types import ModuleType
# from typing import Callable, Iterable, Optional
#
# log = logging.getLogger(__name__)
#
# # Hooks we’ll look for inside each application package (export any subset)
# HOOK_NAMES: tuple[str, ...] = (
#     "register_module_lists",
#     "register_module_details",
#     "register_module_dropdowns",
#     "register_module_prints",
# )
#
#
# def _iter_application_packages(root_pkg: str = "app") -> Iterable[str]:
#     """
#     Discover subpackages under `app/` whose name starts with `application_`.
#     """
#     root = importlib.import_module(root_pkg)
#     for m in pkgutil.iter_modules(root.__path__, root_pkg + "."):
#         name = m.name
#         # Only top-level "app.application_*" packages (not nested utilities)
#         if name.startswith(f"{root_pkg}.application_"):
#             yield name
#
#
# def _import_optional(mod_name: str) -> Optional[ModuleType]:
#     try:
#         return importlib.import_module(mod_name)
#     except ModuleNotFoundError:
#         return None
#     except Exception:
#         log.exception("Failed to import %s", mod_name)
#         return None
#
#
# def _call_if_exists(pkg: ModuleType, hook: str) -> None:
#     fn: Optional[Callable] = getattr(pkg, hook, None)
#     if callable(fn):
#         try:
#             fn()
#             # NOTE: avoid emojis here to be safe on Windows consoles (cp1252).
#             log.info("OK %s.%s()", pkg.__name__, hook)
#         except Exception:
#             log.exception("Hook %s.%s() failed", pkg.__name__, hook)
#
#
# def autoregister_all() -> None:
#     """
#     Import each `app.application_*` package once and call any present hooks:
#       - register_module_lists()
#       - register_module_details()
#       - register_module_dropdowns()
#             - register_module_prints()
#     Tip: each package can keep its own internal structure; we just call hooks.
#     """
#     for pkg_name in _iter_application_packages():
#         pkg = _import_optional(pkg_name)
#         if not pkg:
#             continue
#         for hook in HOOK_NAMES:
#             _call_if_exists(pkg, hook)
# core/module_autoreg.py
from __future__ import annotations
import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

# Hooks we'll look for inside each application package (export any subset)
HOOK_NAMES: tuple[str, ...] = (
    "register_module_lists",
    "register_module_details",
    "register_module_dropdowns",
    "register_module_prints",
)


def _iter_application_packages(root_pkg: str = "app") -> Iterable[str]:
    """
    Discover subpackages under `app/` whose name starts with `application_`.
    Recursively includes subpackages under application_* packages.
    """
    root = importlib.import_module(root_pkg)
    packages_to_check = [root_pkg]
    seen = set()

    while packages_to_check:
        current_pkg = packages_to_check.pop()
        if current_pkg in seen:
            continue
        seen.add(current_pkg)

        try:
            module = importlib.import_module(current_pkg)
        except ModuleNotFoundError:
            continue
        except Exception:
            log.exception("Failed to import %s", current_pkg)
            continue

        # Check if this is an application_ package
        if current_pkg.startswith(f"{root_pkg}.application_"):
            yield current_pkg

        # Add all subpackages for further exploration
        try:
            for finder, name, ispkg in pkgutil.iter_modules(module.__path__, module.__name__ + "."):
                if ispkg:
                    packages_to_check.append(name)
        except AttributeError:
            # No __path__ attribute (might be a namespace package or not a package)
            continue


def _import_optional(mod_name: str) -> Optional[ModuleType]:
    try:
        return importlib.import_module(mod_name)
    except ModuleNotFoundError:
        return None
    except Exception:
        log.exception("Failed to import %s", mod_name)
        return None


def _call_if_exists(pkg: ModuleType, hook: str) -> None:
    fn: Optional[Callable] = getattr(pkg, hook, None)
    if callable(fn):
        try:
            fn()
            # NOTE: avoid emojis here to be safe on Windows consoles (cp1252).
            log.info("OK %s.%s()", pkg.__name__, hook)
        except Exception:
            log.exception("Hook %s.%s() failed", pkg.__name__, hook)


def autoregister_all() -> None:
    """
    Import each `app.application_*` package and its subpackages,
    and call any present hooks:
      - register_module_lists()
      - register_module_details()
      - register_module_dropdowns()
      - register_module_prints()

    Tip: each package can keep its own internal structure; we just call hooks.
    """
    for pkg_name in _iter_application_packages():
        pkg = _import_optional(pkg_name)
        if not pkg:
            continue
        for hook in HOOK_NAMES:
            _call_if_exists(pkg, hook)