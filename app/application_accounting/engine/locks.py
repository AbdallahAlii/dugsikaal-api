
# app/application_accounting/engine/locks.py
from __future__ import annotations
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from config.database import db


def _is_session_like(obj: Any) -> bool:
    """Checks if an object behaves like a SQLAlchemy Session."""
    return hasattr(obj, "execute") and hasattr(obj, "get_bind")


def _mix_to_signed_i64(company_id: int, doctype_id: int, doc_id: int) -> int:
    """
    Creates a deterministic 64-bit integer from document keys to serve as
    a unique lock key. The result is in the signed BIGINT range.
    """
    mask = (1 << 64) - 1
    # Constants are large primes to ensure good mixing
    x = (
                (int(company_id) * 14029467366897019727) ^
                (int(doctype_id) * 1609587929392839161) ^
                (int(doc_id) * 9650029242287828579)
        ) & mask

    # Convert unsigned 64-bit hash to a signed 64-bit integer
    return x - (1 << 64) if x >= (1 << 63) else x


@contextmanager
def lock_doc(*args):
    """
    Acquires a transaction-level advisory lock for a specific document.

    Usage:
      with lock_doc(session, company_id, doctype_id, doc_id):
          ...
      with lock_doc(company_id, doctype_id, doc_id): # uses default db.session
          ...

    On Postgres, this uses pg_advisory_xact_lock(bigint).
    It is a no-op on other database dialects.
    """
    if len(args) == 4 and _is_session_like(args[0]):
        s: Session = args[0]
        company_id, source_doctype_id, source_doc_id = map(int, args[1:4])
    elif len(args) == 3:
        s = db.session
        company_id, source_doctype_id, source_doc_id = map(int, args[0:3])
    else:
        raise TypeError(
            "lock_doc() expects (s, company_id, doctype_id, doc_id) "
            "or (company_id, doctype_id, doc_id)."
        )

    try:
        # Check if the current database connection is PostgreSQL
        bind = s.get_bind()
        if bind.dialect.name == "postgresql":
            k = _mix_to_signed_i64(company_id, source_doctype_id, source_doc_id)
            # Corrected SQL using CAST() for unambiguous syntax
            sql = text("SELECT pg_advisory_xact_lock(CAST(:k AS bigint))")
            s.execute(sql, {"k": k})

        yield
    finally:
        # Transaction-level advisory locks auto-release on commit/rollback.
        pass