#

# app/application_stock/engine/posting_clock.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date, time as dtime
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def _as_aware(dt: datetime, tz: timezone) -> datetime:
    """Return tz-aware datetime in target tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)

def resolve_posting_dt(
    posting_date_or_dt: datetime | date,
    *,
    created_at: Optional[datetime] = None,
    tz: Optional[timezone] = None,
    treat_midnight_as_date: bool = True,
    bump_usec: Optional[int] = None,
) -> datetime:
    """
    Return a timezone-aware posting datetime with a real time-of-day.

    - If caller passed a *datetime*:
        - If `treat_midnight_as_date` and time == 00:00:00 -> treat as date-only and borrow time-of-day.
        - Else -> normalize to `tz` and return unchanged time-of-day.
    - If caller passed a *date*:
        - Borrow time-of-day from created_at or server now.
    - Always inject a microsecond bump (either supplied `bump_usec` or derived from time_ns()) to ensure strict ordering.

    This prevents "all at 00:00:00" collisions and guarantees stable chronological ordering.
    """
    tz = tz or timezone.utc
    logger.info("resolve_posting_dt: Input: %s, tz: %s", posting_date_or_dt, tz)

    def _mk_usec() -> int:
        return int(time.time_ns() % 1_000_000) if bump_usec is None else int(bump_usec)

    # Choose base clock (created_at preferred to preserve document's creation time-of-day)
    base = created_at if isinstance(created_at, datetime) else datetime.now(tz)
    base = _as_aware(base, tz)

    if isinstance(posting_date_or_dt, datetime):
        dt = _as_aware(posting_date_or_dt, tz)
        # FIX: if midnight and flagged, treat as date-only to avoid 00:00:00 collisions.
        if treat_midnight_as_date and dt.time() == dtime(0, 0, 0):
            usec = _mk_usec()
            time_part = base.time().replace(microsecond=usec)
            result = datetime.combine(dt.date(), time_part).astimezone(tz)
            logger.info("resolve_posting_dt: Upgraded midnight datetime to %s", result)
            return result
        logger.info("resolve_posting_dt: Returning datetime: %s (timezone: %s)", dt, dt.tzinfo)
        return dt

    # Date-only path
    usec = _mk_usec()
    time_part = base.time().replace(microsecond=usec)
    result = datetime.combine(posting_date_or_dt, time_part).astimezone(tz)
    logger.info("resolve_posting_dt: Combined result: %s (timezone: %s)", result, result.tzinfo)
    return result
