# application_accounting/engine/events.py
from __future__ import annotations

POST = "POST"
CANCEL = "CANCEL"

def make_entry_type(is_auto: bool = True, for_reversal: bool = False) -> str:
    if is_auto and not for_reversal:
        return "AUTO"
    if is_auto and for_reversal:
        return "AUTO"
        # return "AUTO_REVERSAL"
    return "GENERAL"
