# application_data_import/runner/jobs.py
from __future__ import annotations
from typing import Any, Optional

from ..runner.pipeline import run_import
from config.redis_config import get_redis_raw

def enqueue_import_job(data_import_id: int) -> Any:
    try:
        # Try RQ
        from rq import Queue
        q = Queue("data-imports", connection=get_redis_raw())
        job = q.enqueue(run_import, data_import_id, job_timeout=60 * 60)
        return job
    except Exception:
        # Fallback: run inline (still OK for dev)
        class _InlineJob:
            id = "inline"
        run_import(data_import_id)
        return _InlineJob()
