# app/common/pydantic_utils.py
from __future__ import annotations

from typing import List
from pydantic import ValidationError


def humanize_pydantic_error(err: ValidationError) -> str:
    """
    Convert Pydantic ValidationError to a short ERP-style message.

    Examples:
      - "Missing required field: name"
      - "start_date: Field required; end_date: Field required"
      - "working_days: Invalid weekday: FOO"
    """
    msgs: List[str] = []

    for e in err.errors():
        loc = e.get("loc", ())
        # loc can be ("body","name") or ("name",)
        # remove noisy prefixes
        loc_parts = [str(x) for x in loc if str(x) not in {"body", "__root__"}]
        field = ".".join(loc_parts).strip()

        typ = (e.get("type") or "").lower()
        msg = (e.get("msg") or "Invalid value").strip()

        if "missing" in typ:
            if field:
                msgs.append(f"Missing required field: {field}")
            else:
                msgs.append("Missing required field.")
        else:
            if field:
                msgs.append(f"{field}: {msg}")
            else:
                msgs.append(msg)

    # de-duplicate while preserving order
    seen = set()
    out = []
    for m in msgs:
        if m not in seen:
            out.append(m)
            seen.add(m)

    return "; ".join(out) if out else "Invalid request body."
