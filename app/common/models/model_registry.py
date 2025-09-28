# app/core/model_registry.py
from __future__ import annotations
from typing import Type, Any, Optional, Iterable
from sqlalchemy.orm import Mapper
from config.database import db

# Optional alias map if you want short names that differ from class/tablename
_ALIAS: dict[str, str] = {}  # e.g., {"Org": "Company", "orgs": "companies"}

def register_alias(alias: str, target: str) -> None:
    """
    Map an alias (used by clients/config) to a model class name or __tablename__.
    Example: register_alias("Org", "Company")  or  register_alias("orgs", "companies")
    """
    _ALIAS[alias] = target

def _iter_mappers() -> Iterable[Mapper]:
    # Works for Flask-SQLAlchemy 3.x / SQLAlchemy 2.x
    return db.Model.registry.mappers  # type: ignore[attr-defined]

def get_model(name: str) -> Type[Any]:
    """
    Return a model class by class name (preferred) or by __tablename__.
    You MUST ensure the module defining the model is imported before calling this.
    """
    # resolve alias
    target = _ALIAS.get(name, name)

    # 1) by class name
    for m in _iter_mappers():
        cls = m.class_
        if cls.__name__ == target:
            return cls  # type: ignore[return-value]

    # 2) by __tablename__
    for m in _iter_mappers():
        cls = m.class_
        if getattr(cls, "__tablename__", None) == target:
            return cls  # type: ignore[return-value]

    # build some diagnostics
    class_names = sorted({m.class_.__name__ for m in _iter_mappers()})
    table_names  = sorted({getattr(m.class_, "__tablename__", "") for m in _iter_mappers()})
    raise ValueError(
        f"Model '{name}' not found (alias→'{target}'). "
        f"Known classes: {class_names}. Known tables: {table_names}. "
        f"Make sure the module defining that model is imported at startup."
    )

def list_models() -> list[str]:
    return sorted({m.class_.__name__ for m in _iter_mappers()})

def list_tables() -> list[str]:
    return sorted({getattr(m.class_, "__tablename__", "") for m in _iter_mappers() if getattr(m.class_, '__tablename__', None)})

