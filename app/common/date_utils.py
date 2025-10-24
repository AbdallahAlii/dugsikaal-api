# from __future__ import annotations
# from datetime import datetime, date
# from typing import Optional
# import logging
#
# log = logging.getLogger(__name__)
#
# # Display format everywhere in API responses (filters, not data rows):
# _DISPLAY_FMT = "%m/%d/%Y"
#
# # Accept these inputs for inbound filters:
# _DATE_PARSE_PATTERNS = [
#     "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y",
# ]
#
# def parse_date_flex(s: str) -> date | None:
#     """Flexible date parser that handles multiple formats"""
#     s = (s or "").strip()
#     if not s:
#         return None
#     # Try parsing date with the patterns
#     for fmt in _DATE_PARSE_PATTERNS:
#         try:
#             return datetime.strptime(s, fmt).date()
#         except Exception:
#             continue
#     # Final attempt: raw ISO date
#     try:
#         return datetime.fromisoformat(s).date()
#     except Exception:
#         return None
#
# def format_date_out(d: date | datetime | None) -> str | None:
#     """Format date for API responses"""
#     if d is None:
#         return None
#     if isinstance(d, datetime):
#         d = d.date()
#     return d.strftime(_DISPLAY_FMT)
#
from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any

# Display format used in responses (if/when you need to format dates)
DISPLAY_FMT = "%m/%d/%Y"

# Accept these inbound formats (order matters)
DATE_PARSE_PATTERNS = [
    "%m/%d/%Y",  # 10/16/2025
    "%d/%m/%Y",  # 16/10/2025
    "%Y/%m/%d",  # 2025/10/16
    "%Y-%m-%d",  # 2025-10-16
    "%d-%m-%Y",  # 16-10-2025
    "%m-%d-%Y",  # 10-16-2025
]

ACCEPTED_FORMATS_HUMAN = "mm/dd/YYYY, dd/mm/YYYY, YYYY/mm/dd, YYYY-mm-dd, dd-mm-YYYY, mm-dd-YYYY"


def _extract_value(x: Any) -> str:
    """
    Accepts:
      - "10/16/2025"
      - ["=", "10/16/2025"]
      - {"op": "=", "value": "10/16/2025"}
      - other → coerces to str
    Returns a string suitable for date parsing (or "").
    """
    if isinstance(x, (list, tuple)):
        if len(x) >= 2:
            return str(x[1] if x[1] is not None else "")
        if len(x) == 1:
            return str(x[0] if x[0] is not None else "")
        return ""
    if isinstance(x, dict):
        for k in ("value", "val", "v"):
            if k in x and x[k] is not None:
                return str(x[k])
        # last resort: try first non-null value
        for v in x.values():
            if v is not None:
                return str(v)
        return ""
    if x is None:
        return ""
    return str(x)


def parse_date_flex(s: Any) -> Optional[date]:
    """Flexible date parser that handles multiple formats and shapes (string/array/dict)."""
    raw = _extract_value(s).strip()
    if not raw:
        return None
    for fmt in DATE_PARSE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    # last resort: ISO-ish
    try:
        return datetime.fromisoformat(raw).date()
    except Exception:
        return None


def format_date_out(d: date | datetime | None) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(DISPLAY_FMT)
