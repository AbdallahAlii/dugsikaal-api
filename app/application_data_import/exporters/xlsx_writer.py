# application_data_import/exporters/xlsx_writer.py
from __future__ import annotations
from typing import List, Dict, Any
import io


def write_xlsx(headers: List[str], rows: List[Dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
