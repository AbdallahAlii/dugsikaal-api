# application_data_import/exporters/csv_writer.py
from __future__ import annotations
import csv
import io
from typing import List, Dict, Any


def write_csv(headers: List[str], rows: List[Dict[str, Any]]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")
