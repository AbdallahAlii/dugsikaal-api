# app/application_reports/scripts/_cursor_utils.py
from __future__ import annotations
import json
from base64 import urlsafe_b64encode, urlsafe_b64decode
from typing import Dict, Any

def encode_keyset_cursor(key_pairs: Dict[str, Any]) -> str:
    """
    key_pairs example: { "posting_date": "2025-10-09", "voucher_no": "PINV-2025-00021" }
    """
    payload = {"gt": [[k, str(v) if v is not None else None] for k, v in key_pairs.items()]}
    return urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

def decode_keyset_cursor(cursor: str) -> Dict[str, str]:
    """
    Returns dict like {"posting_date": "2025-10-09", "voucher_no": "PINV-..."}
    """
    try:
        obj = json.loads(urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8"))
        pairs = obj.get("gt") or []
        return {k: v for k, v in pairs}
    except Exception:
        return {}
