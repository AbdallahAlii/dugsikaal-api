#
# # app/application_stock/engine/posting_clock.py
#
# from __future__ import annotations
#
# from datetime import datetime, timezone, date, time as dtime
# import time
# import logging
# from typing import Optional
# from zoneinfo import ZoneInfo
#
# logger = logging.getLogger(__name__)
#
#
# def _as_aware(dt: datetime, tz: timezone | ZoneInfo) -> datetime:
#     """Return tz-aware datetime in target tz."""
#     if dt.tzinfo is None:
#         return dt.replace(tzinfo=tz)
#     return dt.astimezone(tz)
#
#
# def resolve_posting_dt(
#         posting_date_or_dt: datetime | date,
#         *,
#         created_at: Optional[datetime] = None,
#         tz: Optional[timezone | ZoneInfo] = None,
#         treat_midnight_as_date: bool = True,
#         bump_usec: Optional[int] = None,
# ) -> datetime:
#     """
#     Return a timezone-aware posting datetime with a real time-of-day.
#
#     ✅ FIXES:
#       - Properly handles ZoneInfo timezones
#       - Upgrades midnight datetimes to real times
#       - Injects microsecond bumps for ordering
#       - Preserves timezone information correctly
#     """
#     # Default to UTC if no timezone provided
#     if tz is None:
#         tz = timezone.utc
#
#     logger.info(f"resolve_posting_dt: Input: {posting_date_or_dt}, tz: {tz}")
#
#     def _mk_usec() -> int:
#         """Generate microsecond value for ordering."""
#         if bump_usec is not None:
#             return int(bump_usec)
#         return int(time.time_ns() % 1_000_000)
#
#     # Choose base clock (created_at preferred to preserve document's creation time)
#     if isinstance(created_at, datetime):
#         base = _as_aware(created_at, tz)
#     else:
#         # ✅ FIX: Create datetime in the target timezone
#         if isinstance(tz, ZoneInfo):
#             base = datetime.now(tz)
#         else:
#             base = datetime.now(tz)
#
#     logger.info(f"resolve_posting_dt: Base datetime: {base} (tz: {base.tzinfo})")
#
#     if isinstance(posting_date_or_dt, datetime):
#         dt = _as_aware(posting_date_or_dt, tz)
#
#         # ✅ FIX: Upgrade midnight datetime to real time
#         if treat_midnight_as_date and dt.time() == dtime(0, 0, 0):
#             usec = _mk_usec()
#             time_part = base.time().replace(microsecond=usec)
#
#             # ✅ FIX: Combine and ensure correct timezone
#             if isinstance(tz, ZoneInfo):
#                 result = datetime.combine(dt.date(), time_part).replace(tzinfo=tz)
#             else:
#                 result = datetime.combine(dt.date(), time_part).astimezone(tz)
#
#             logger.info(f"resolve_posting_dt: Upgraded midnight to {result} (tz: {result.tzinfo})")
#             return result
#
#         logger.info(f"resolve_posting_dt: Returning datetime: {dt} (tz: {dt.tzinfo})")
#         return dt
#
#     # Date-only path
#     usec = _mk_usec()
#     time_part = base.time().replace(microsecond=usec)
#
#     # ✅ FIX: Combine and ensure correct timezone
#     if isinstance(tz, ZoneInfo):
#         result = datetime.combine(posting_date_or_dt, time_part).replace(tzinfo=tz)
#     else:
#         result = datetime.combine(posting_date_or_dt, time_part).astimezone(tz)
#
#     logger.info(f"resolve_posting_dt: Combined result: {result} (tz: {result.tzinfo})")
#     return result

# app/application_stock/engine/posting_clock.py
from __future__ import annotations

import logging
from datetime import date, datetime, timezone as dt_timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# Reuse the centralized, safe timezone helpers
from app.common.timezone.service import (
    combine_local_posting_dt,
    company_posting_dt as _company_posting_dt,
    ensure_aware as _ensure_aware,
)

logger = logging.getLogger(__name__)

# Keep type compatibility with existing call sites:
# - tz accepts datetime.timezone or ZoneInfo (your code already passes ZoneInfo(company_tz))
# - If tz is None, we stay backward-compatible and default to UTC.
def resolve_posting_dt(
    posting_date_or_dt: datetime | date,
    *,
    created_at: Optional[datetime] = None,
    tz: Optional[dt_timezone | ZoneInfo] = None,
    treat_midnight_as_date: bool = True,
    bump_usec: Optional[int] = None,
) -> datetime:
    """
    ERP-style resolver for Posting Date/Time → returns a tz-aware datetime.

    Behavior (unchanged for callers):
      - If the caller gives a date only, we combine it with a realistic time-of-day
        using `created_at` (preferred) or `now(tz)` and add a tiny microsecond bump
        for deterministic ordering.
      - If the caller gives a datetime at 00:00:00 and `treat_midnight_as_date=True`,
        we "upgrade" it to a real time-of-day (same rule as above).
      - If the caller gives an aware datetime with a real time, we normalize it to `tz`.

    Implementation:
      - Delegates to `combine_local_posting_dt(...)` from the shared timezone module.
      - Defaults to UTC when `tz` is not provided (backward-compatible with your old code).
    """
    # Maintain previous default (UTC) if tz is not provided.
    tz_like = tz if tz is not None else dt_timezone.utc

    logger.info(
        "resolve_posting_dt: input=%s | created_at=%s | tz=%s | midnight_as_date=%s | bump_usec=%s",
        posting_date_or_dt,
        created_at,
        tz_like,
        treat_midnight_as_date,
        bump_usec,
    )

    resolved = combine_local_posting_dt(
        posting_date_or_dt,
        tz_like,
        created_at=created_at,
        treat_midnight_as_date=treat_midnight_as_date,
        bump_usec=bump_usec,
    )

    # Ensure aware (should already be, but safe to assert)
    resolved = _ensure_aware(resolved, tz_like)
    logger.info("resolve_posting_dt: resolved=%s (tz=%s)", resolved, resolved.tzinfo)
    return resolved


def resolve_company_posting_dt(
    session_or_engine,
    company_id: int,
    posting_date_or_dt: datetime | date,
    *,
    created_at: Optional[datetime] = None,
    treat_midnight_as_date: bool = True,
    bump_usec: Optional[int] = None,
) -> datetime:
    """
    Convenience wrapper for the common case: you have company_id and want a
    Posting Datetime in the company's timezone.

    Equivalent to:
        tz = get_company_timezone(session_or_engine, company_id)
        resolve_posting_dt(..., tz=tz, ...)
    """
    logger.info(
        "resolve_company_posting_dt: company_id=%s | input=%s | midnight_as_date=%s | bump_usec=%s",
        company_id,
        posting_date_or_dt,
        treat_midnight_as_date,
        bump_usec,
    )

    resolved = _company_posting_dt(
        session_or_engine,
        company_id,
        posting_date_or_dt,
        created_at=created_at,
        treat_midnight_as_date=treat_midnight_as_date,
        bump_usec=bump_usec,
    )
    logger.info(
        "resolve_company_posting_dt: resolved=%s (tz=%s)",
        resolved,
        resolved.tzinfo,
    )
    return resolved
