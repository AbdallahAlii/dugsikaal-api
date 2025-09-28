from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

_FALLBACK_TZ = "Africa/Nairobi"  # change if you prefer a different default


def _safe_zoneinfo(name: Optional[str]) -> ZoneInfo:
    try:
        if name:
            return ZoneInfo(name)
    except Exception:
        pass
    return ZoneInfo(_FALLBACK_TZ)


def _fetch_scalar_safe(engine: Engine, sql: str, params: Optional[dict] = None) -> Optional[str]:
    """
    Execute a read-only query using a separate connection so we don't
    contaminate the caller's ORM session / transaction if something fails.
    """
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar_one_or_none()
    except Exception:
        # swallow and return None – this does NOT affect the ORM session state
        return None


def _show_server_timezone(engine: Engine) -> Optional[str]:
    # Final fallback: ask Postgres what it's using
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql("SHOW TimeZone").scalar_one_or_none()
            return row
    except Exception:
        return None


def get_company_timezone(s: Session, company_id: int) -> ZoneInfo:
    """
    Returns the company's configured IANA timezone as tzinfo.
    Lookup order (customize to your schema):
      1) companies.timezone
      2) system_settings.value where key = 'timezone'
      3) server GUC (SHOW TimeZone)
      4) _FALLBACK_TZ
    All reads are done on a separate connection to avoid aborting the caller's tx.
    """
    engine = s.get_bind()

    # 1) Company-specific
    tzname = _fetch_scalar_safe(
        engine,
        "SELECT timezone FROM companies WHERE id = :cid LIMIT 1",
        {"cid": int(company_id)},
    )
    if tzname:
        return _safe_zoneinfo(tzname)

    # 2) Global/system setting
    tzname = _fetch_scalar_safe(
        engine,
        "SELECT value FROM system_settings WHERE key = 'timezone' LIMIT 1",
    )
    if tzname:
        return _safe_zoneinfo(tzname)

    # 3) Server GUC
    tzname = _show_server_timezone(engine)
    if tzname:
        return _safe_zoneinfo(tzname)

    # 4) Hard fallback
    return _safe_zoneinfo(None)
