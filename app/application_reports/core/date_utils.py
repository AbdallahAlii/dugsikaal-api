
# app/application_reports/core/date_utils.py
from __future__ import annotations
from datetime import datetime, date
from typing import Optional, Any

# Display format used in responses (matches your output)
DISPLAY_FMT = "%d-%m-%Y"

# Accept these inbound formats (order matters)
DATE_PARSE_PATTERNS = [
    "%Y-%m-%d",  # 2025-12-31 (ISO format)
    "%d-%m-%Y",  # 31-12-2025
    "%m/%d/%Y",  # 12/31/2025
    "%d/%m/%Y",  # 31/12/2025
    "%Y/%m/%d",  # 2025/12/31
    "%m-%d-%Y",  # 12-31-2025
]


def parse_date_flex(s: Any) -> Optional[date]:
    """Flexible date parser that handles multiple formats."""
    if s is None:
        return None

    # If it's already a date/datetime, return it
    if isinstance(s, date):
        return s
    if isinstance(s, datetime):
        return s.date()

    # Convert to string
    raw = str(s).strip()
    if not raw:
        return None

    # Try all patterns
    for fmt in DATE_PARSE_PATTERNS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Try ISO format
    try:
        # Handle ISO format with timezone
        if 'T' in raw or ' ' in raw:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).date()
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def format_date_for_display(d: date | datetime | None) -> Optional[str]:
    """Format date for display (output)."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(DISPLAY_FMT)