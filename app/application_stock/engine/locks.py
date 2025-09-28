# # stock/engine/locks.py

from __future__ import annotations
from contextlib import contextmanager
from typing import Iterable, Tuple, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from config.database import db

def _is_session_like(obj: Any) -> bool:
    """Checks if an object behaves like a SQLAlchemy Session."""
    return hasattr(obj, "execute") and hasattr(obj, "get_bind")

def _advisory_key(item_id: int, warehouse_id: int) -> Tuple[int, int]:
    """Generates a consistent key pair for locking."""
    return (int(item_id), int(warehouse_id))

@contextmanager
def lock_pairs(*args):
    """
    Acquires a transaction-level advisory lock for item-warehouse pairs.

    Usage:
      with lock_pairs(session, pairs):
          ...
      with lock_pairs(pairs):  # uses the default db.session
          ...

    On Postgres, this uses pg_advisory_xact_lock(int, int).
    No-op on other database dialects.
    """
    if len(args) == 2 and _is_session_like(args[0]):
        s: Session = args[0]
        pairs: Iterable[Tuple[int, int]] = args[1]
    elif len(args) == 1:
        s = db.session
        pairs = args[0]
    else:
        raise TypeError("lock_pairs() expects (session, pairs) or (pairs) as arguments.")

    try:
        bind = s.get_bind()
        if bind.dialect.name == "postgresql":
            sql = text("SELECT pg_advisory_xact_lock(CAST(:k1 AS integer), CAST(:k2 AS integer))")
            for item_id, wh_id in pairs:
                k1, k2 = _advisory_key(item_id, wh_id)
                s.execute(sql, {"k1": k1, "k2": k2})
        yield
    finally:
        pass  # auto-release on transaction commit/rollback
