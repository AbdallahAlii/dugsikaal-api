from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timezone
from typing import Optional, Tuple, Union

from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine, Connection
from sqlalchemy import text

# ── Public API ──────────────────────────────────────────────────────────────────
# get_company_timezone(session_or_engine, company_id) -> ZoneInfo
# now_in_company_tz(session_or_engine, company_id) -> datetime (aware)
# ensure_aware(dt, tz_like) -> datetime (aware in target tz)
# to_utc(dt) -> datetime (aware in UTC)
# split_local_date_time_for_ui(dt, tz_like) -> (YYYY-MM-DD, HH:MM:SS)
# combine_local_posting_dt(date_or_dt, tz_like, *, created_at=None,
#                          treat_midnight_as_date=True, bump_usec=None) -> datetime
#
# Notes:
# - tz_like can be a str timezone name, ZoneInfo, or datetime.timezone (e.g., timezone.utc).
# - This module uses only stdlib 'zoneinfo' (no pytz).
# - All DB reads are done via a separate connection to avoid aborting the caller's tx.
# ────────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# Default fallback timezone — Somalia (GMT+3)
_DEFAULT_TZ_NAME = "Africa/Mogadishu"

TzLike = Union[str, ZoneInfo, timezone]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _as_engine(obj: Union[Session, Engine, Connection]) -> Engine:
    """
    Get an Engine from a Session/Engine/Connection without leaking transactions.
    """
    if isinstance(obj, Engine):
        return obj
    if isinstance(obj, Connection):
        return obj.engine
    # Assume Session
    bind = obj.get_bind()
    if isinstance(bind, Connection):
        return bind.engine
    return bind  # Engine


def _safe_zoneinfo(name: Optional[str]) -> ZoneInfo:
    """
    Best-effort ZoneInfo loader with fallback to _DEFAULT_TZ_NAME.
    """
    try:
        if name and name.strip():
            return ZoneInfo(name.strip())
    except Exception:
        pass
    return ZoneInfo(_DEFAULT_TZ_NAME)


def _fetch_scalar_safe(engine: Engine, sql: str, params: Optional[dict] = None) -> Optional[str]:
    """
    Execute a read-only scalar query using a separate connection to avoid
    contaminating the caller's ORM session / transaction.
    """
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params or {}).scalar_one_or_none()
    except Exception as ex:
        logger.debug("timezone._fetch_scalar_safe failed for %s with %s", sql, ex)
        return None


def _show_server_timezone(engine: Engine) -> Optional[str]:
    """
    Ask the DB server which timezone it's using (Postgres: SHOW TimeZone).
    """
    try:
        with engine.connect() as conn:
            return conn.exec_driver_sql("SHOW TimeZone").scalar_one_or_none()
    except Exception as ex:
        logger.debug("timezone._show_server_timezone failed: %s", ex)
        return None


def _tzinfo_from_like(tz_like: TzLike) -> ZoneInfo:
    if isinstance(tz_like, ZoneInfo):
        return tz_like
    if isinstance(tz_like, timezone):  # e.g., timezone.utc
        # Convert to ZoneInfo when possible; for UTC, ZoneInfo('UTC') is fine
        if tz_like is timezone.utc:
            return ZoneInfo("UTC")
        # Fallback: attach fixed offset via datetime.astimezone later
        return ZoneInfo("UTC")  # neutral default; caller can still astimezone
    if isinstance(tz_like, str):
        return _safe_zoneinfo(tz_like)
    # Unknown type -> fallback
    return _safe_zoneinfo(None)


def _mk_usec(bump_usec: Optional[int]) -> int:
    """
    Generate a microsecond offset for strict ordering.
    """
    if bump_usec is not None:
        return int(bump_usec)
    return int(time.time_ns() % 1_000_000)


# ── Public: Resolution & conversion ────────────────────────────────────────────

def get_company_timezone(session_or_engine: Union[Session, Engine, Connection], company_id: int) -> ZoneInfo:
    """
    Resolve the company's IANA timezone with safe fallbacks:

      1) companies.timezone
      2) system_settings.value where key = 'timezone'
      3) DB server GUC (SHOW TimeZone)
      4) Africa/Mogadishu

    All reads are done outside the caller's ORM transaction.
    """
    engine = _as_engine(session_or_engine)

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


def now_in_company_tz(session_or_engine: Union[Session, Engine, Connection], company_id: int) -> datetime:
    """
    Current datetime in the company's timezone (tz-aware).
    """
    tz = get_company_timezone(session_or_engine, company_id)
    return datetime.now(tz)


def ensure_aware(dt: datetime, tz_like: TzLike) -> datetime:
    """
    Ensure 'dt' is timezone-aware in the target timezone.
    If 'dt' is naive, attach tz; if already aware, convert to tz.
    """
    tz = _tzinfo_from_like(tz_like)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def to_utc(dt: datetime) -> datetime:
    """
    Convert a datetime to UTC. If naive, assume default fallback tz first.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_safe_zoneinfo(None))
    return dt.astimezone(timezone.utc)


def split_local_date_time_for_ui(dt: datetime, tz_like: TzLike) -> Tuple[str, str]:
    """
    Convert a datetime to the target tz and split into (date_str, time_str)
    for UI fields that mimic ERP-style 'Posting Date' + 'Posting Time'.

    Returns:
        ("YYYY-MM-DD", "HH:MM:SS")
    """
    tz = _tzinfo_from_like(tz_like)
    local = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    local = local.astimezone(tz)
    ds = local.date().isoformat()
    ts = local.time().strftime("%H:%M:%S")
    return ds, ts


def combine_local_posting_dt(
    posting_date_or_dt: Union[date, datetime],
    tz_like: TzLike,
    *,
    created_at: Optional[datetime] = None,
    treat_midnight_as_date: bool = True,
    bump_usec: Optional[int] = None,
) -> datetime:
    """
    Create a proper timezone-aware posting datetime in the given timezone.

    - If 'posting_date_or_dt' is a date: combine with the time-of-day from
      'created_at' (if provided) or 'now(tz)', and add a small microsecond
      bump for deterministic ordering.
    - If it's a datetime:
        * Make it aware in tz if naive.
        * If time == 00:00:00 and 'treat_midnight_as_date' is True, replace
          the time-of-day with 'created_at' or 'now(tz)' and add microsecond bump.

    This mirrors the ERP behavior where users often pick only a date, but we
    want a real time-of-day for ordering (stock valuation, back-dating, replay).
    """
    tz = _tzinfo_from_like(tz_like)

    # Choose base clock for time-of-day source
    base = ensure_aware(created_at, tz) if isinstance(created_at, datetime) else datetime.now(tz)

    if isinstance(posting_date_or_dt, datetime):
        dt = ensure_aware(posting_date_or_dt, tz)

        if treat_midnight_as_date and dt.time() == dtime(0, 0, 0):
            usec = _mk_usec(bump_usec)
            time_part = base.time().replace(microsecond=usec)
            return datetime.combine(dt.date(), time_part).replace(tzinfo=tz)

        return dt

    # date-only path
    usec = _mk_usec(bump_usec)
    time_part = base.time().replace(microsecond=usec)
    return datetime.combine(posting_date_or_dt, time_part).replace(tzinfo=tz)


# ── Optional convenience wrapper for company-aware posting datetimes ───────────

def company_posting_dt(
    session_or_engine: Union[Session, Engine, Connection],
    company_id: int,
    posting_date_or_dt: Union[date, datetime],
    *,
    created_at: Optional[datetime] = None,
    treat_midnight_as_date: bool = True,
    bump_usec: Optional[int] = None,
) -> datetime:
    """
    Shortcut that first resolves the company's timezone, then calls
    combine_local_posting_dt(...). Ideal for create/submit handlers.
    """
    tz = get_company_timezone(session_or_engine, company_id)
    return combine_local_posting_dt(
        posting_date_or_dt,
        tz,
        created_at=created_at,
        treat_midnight_as_date=treat_midnight_as_date,
        bump_usec=bump_usec,
    )


# ── Validation helpers ─────────────────────────────────────────────────────────

def is_valid_tz(name: str) -> bool:
    """
    Check if an IANA timezone name is valid.
    """
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


# ── Friendly alias kept for compatibility if you previously used DEFAULT_TZ ────
DEFAULT_TZ: ZoneInfo = _safe_zoneinfo(_DEFAULT_TZ_NAME)


# ── Example usage (doctest-ish) ────────────────────────────────────────────────
# >>> # resolve company tz (aware)
# >>> tz = get_company_timezone(session, 1)
# >>> assert isinstance(tz, ZoneInfo)
# >>> # current time in company tz
# >>> now_local = now_in_company_tz(session, 1)
# >>> # coercing posting date picked in a form to a real datetime
# >>> posting_dt = company_posting_dt(session, 1, date(2025, 10, 23))
# >>> # splitting an aware dt back for form fields
# >>> split_local_date_time_for_ui(posting_dt, tz)
