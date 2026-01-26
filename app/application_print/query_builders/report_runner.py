# app/application_print/query_builders/report_runner.py
from __future__ import annotations

from typing import Dict, Any, List


def run_printable_report(name: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Placeholder for future 'printable reports' (Trial Balance, P&L, etc.).
    Not needed for single-document printing.
    """
    raise NotImplementedError(f"Printable report '{name}' is not implemented yet.")
