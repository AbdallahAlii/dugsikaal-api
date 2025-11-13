# application_data_import/parsers/csv_reader.py
from __future__ import annotations
import csv
import io
from typing import List, Dict, Any


def read_csv_bytes(raw: bytes) -> (List[str], List[Dict[str, Any]]):
    text = raw.decode("utf-8-sig", errors="replace")
    buf = io.StringIO(text)
    r = csv.DictReader(buf)
    headers = r.fieldnames or []
    rows = [dict(row) for row in r]
    return headers, rows
