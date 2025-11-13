# application_data_import/utils/dates.py
from __future__ import annotations
from datetime import datetime

def now_ts() -> datetime:
    return datetime.utcnow()
