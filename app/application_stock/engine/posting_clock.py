
# app/application_stock/engine/posting_clock.py

from __future__ import annotations

from datetime import datetime, timezone, date, time as dtime
import time
import logging
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def _as_aware(dt: datetime, tz: timezone | ZoneInfo) -> datetime:
    """Return tz-aware datetime in target tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def resolve_posting_dt(
        posting_date_or_dt: datetime | date,
        *,
        created_at: Optional[datetime] = None,
        tz: Optional[timezone | ZoneInfo] = None,
        treat_midnight_as_date: bool = True,
        bump_usec: Optional[int] = None,
) -> datetime:
    """
    Return a timezone-aware posting datetime with a real time-of-day.

    ✅ FIXES:
      - Properly handles ZoneInfo timezones
      - Upgrades midnight datetimes to real times
      - Injects microsecond bumps for ordering
      - Preserves timezone information correctly
    """
    # Default to UTC if no timezone provided
    if tz is None:
        tz = timezone.utc

    logger.info(f"resolve_posting_dt: Input: {posting_date_or_dt}, tz: {tz}")

    def _mk_usec() -> int:
        """Generate microsecond value for ordering."""
        if bump_usec is not None:
            return int(bump_usec)
        return int(time.time_ns() % 1_000_000)

    # Choose base clock (created_at preferred to preserve document's creation time)
    if isinstance(created_at, datetime):
        base = _as_aware(created_at, tz)
    else:
        # ✅ FIX: Create datetime in the target timezone
        if isinstance(tz, ZoneInfo):
            base = datetime.now(tz)
        else:
            base = datetime.now(tz)

    logger.info(f"resolve_posting_dt: Base datetime: {base} (tz: {base.tzinfo})")

    if isinstance(posting_date_or_dt, datetime):
        dt = _as_aware(posting_date_or_dt, tz)

        # ✅ FIX: Upgrade midnight datetime to real time
        if treat_midnight_as_date and dt.time() == dtime(0, 0, 0):
            usec = _mk_usec()
            time_part = base.time().replace(microsecond=usec)

            # ✅ FIX: Combine and ensure correct timezone
            if isinstance(tz, ZoneInfo):
                result = datetime.combine(dt.date(), time_part).replace(tzinfo=tz)
            else:
                result = datetime.combine(dt.date(), time_part).astimezone(tz)

            logger.info(f"resolve_posting_dt: Upgraded midnight to {result} (tz: {result.tzinfo})")
            return result

        logger.info(f"resolve_posting_dt: Returning datetime: {dt} (tz: {dt.tzinfo})")
        return dt

    # Date-only path
    usec = _mk_usec()
    time_part = base.time().replace(microsecond=usec)

    # ✅ FIX: Combine and ensure correct timezone
    if isinstance(tz, ZoneInfo):
        result = datetime.combine(posting_date_or_dt, time_part).replace(tzinfo=tz)
    else:
        result = datetime.combine(posting_date_or_dt, time_part).astimezone(tz)

    logger.info(f"resolve_posting_dt: Combined result: {result} (tz: {result.tzinfo})")
    return result