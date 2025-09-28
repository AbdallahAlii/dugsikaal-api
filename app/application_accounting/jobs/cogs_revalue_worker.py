# application_accounting/jobs/cogs_revalue_worker.py
from __future__ import annotations
"""
Optional: after stock replay/lcv, compute old vs new COGS per delivery
and post small GL 'diff' (Dr/Cr 5011/1141). Implementation depends on
how you store historical COGS snapshots. Stub left intentionally.
"""
