from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.common.cache.redis_client import redis_kv

log = logging.getLogger(__name__)


# ----------------- helpers -----------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "report"


def _clean_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    volatile = {"nocache", "_ts", "cache", "export_format"}

    def _ser(v: Any) -> Any:
        if hasattr(v, "isoformat"):
            try:
                return v.isoformat()
            except Exception:
                return str(v)
        return v

    return {k: _ser(v) for k, v in (filters or {}).items() if k not in volatile}


def _hash_obj(o: Any) -> str:
    s = json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ver_key(report_slug: str, company_id: int) -> str:
    return f"v:rpt:{report_slug}:co{int(company_id)}"


def _get_ver(report_slug: str, company_id: int) -> int:
    """
    Best-effort. If Redis is down -> returns 0 (acts like cache miss / base version).
    """
    v = redis_kv.get(_ver_key(report_slug, company_id))
    try:
        return int(v or 0)
    except Exception:
        return 0


# ----------------- cache -----------------

class ReportCache:
    """
    Redis cache for report payloads with versioned keys.

    Key:
      rpt:<report-slug>:co<company_id>:v<version>:<hash(filters)>
    """

    def __init__(self, *, enabled: bool = True, default_ttl: int = 30, max_size: int = 10000):
        self.enabled = bool(enabled)
        self.default_ttl = int(default_ttl)
        self.max_size = int(max_size)  # kept for parity (not enforced here)

    # ---------- key building ----------

    def _key(self, report_name: str, filters: Dict[str, Any]) -> str:
        rep = _slug(report_name)

        # Keep compatibility with your existing filters shape:
        # you used filters["company"] previously
        co = int((filters or {}).get("company") or (filters or {}).get("company_id") or 0)

        ver = _get_ver(rep, co)
        h = _hash_obj(_clean_filters(filters))
        return f"rpt:{rep}:co{co}:v{ver}:{h}"

    def _prefix_report(self, report_name: str) -> str:
        return f"rpt:{_slug(report_name)}:"

    def _prefix_report_company(self, report_name: str, company_id: int) -> str:
        return f"rpt:{_slug(report_name)}:co{int(company_id)}:"

    # ---------- read/write ----------

    def get(self, report_name: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        key = self._key(report_name, filters)
        try:
            raw = redis_kv.get(key)
            if not raw:
                return None
            result = json.loads(raw)
            log.debug("✅ Report cache HIT: %s", key)
            return result
        except Exception as e:
            # SafeRedis.get already returns None on redis errors,
            # but keep this defensive for JSON errors etc.
            log.warning("ReportCache.get failed key=%s err=%s", key, e)
            return None

    def set(self, report_name: str, filters: Dict[str, Any], value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        if not self.enabled:
            return

        key = self._key(report_name, filters)
        try:
            payload = json.dumps(value, default=str)
            if len(payload) > 1_000_000:  # ~1MB guard
                log.warning("Report too large for caching: %s (%s bytes)", key, len(payload))
                return

            ok = redis_kv.setex(key, int(ttl or self.default_ttl), payload)
            if ok:
                log.debug("💾 Report cache SET: %s", key)
        except Exception as e:
            log.warning("ReportCache.set failed key=%s err=%s", key, e)

    # ---------- invalidation (two modes) ----------

    def bump_company(self, report_name: str, company_id: int) -> int:
        """
        O(1) version bump. Leaves old keys to expire naturally.
        Best-effort: if Redis down -> returns 0.
        """
        rep = _slug(report_name)
        v = int(redis_kv.incr(_ver_key(rep, int(company_id))) or 0)
        log.info("🔥 BUMP report cache %s company=%s -> v%s", rep, company_id, v)
        return v

    # NOTE: Aggressive invalidation uses scan_iter.
    # SafeRedis doesn't expose scan_iter, so we call the raw client defensively.

    def _scan_delete(self, pattern: str, *, count: int = 500) -> int:
        """
        Best-effort delete by SCAN pattern. If Redis down -> returns 0.
        """
        cnt = 0
        try:
            # If redis is down, this will throw and we return 0.
            client = redis_kv._client()  # noqa: SLF001 (intentional internal access)
            for k in client.scan_iter(match=pattern, count=count):
                try:
                    cnt += int(client.delete(k) or 0)
                except Exception:
                    continue
        except Exception as e:
            log.warning("ReportCache scan/delete failed pattern=%s err=%s", pattern, e)
        return cnt

    def invalidate_report(self, report_name: str) -> int:
        """Aggressive: delete all cached variants of a report (all companies)."""
        pref = self._prefix_report(report_name)
        cnt = self._scan_delete(pref + "*", count=500)
        if cnt:
            log.info("🧹 ReportCache invalidated report=%s keys=%s", report_name, cnt)
        return cnt

    def invalidate_company(self, report_name: str, company_id: int) -> int:
        """Aggressive: delete a report's keys for one company."""
        pref = self._prefix_report_company(report_name, company_id)
        cnt = self._scan_delete(pref + "*", count=500)
        if cnt:
            log.info("🧹 ReportCache invalidated report=%s company=%s keys=%s", report_name, company_id, cnt)
        return cnt

    def invalidate_company_all_reports(self, company_id: int) -> int:
        """Aggressive: delete ALL reports for a company."""
        pattern = f"rpt:*:co{int(company_id)}:*"
        cnt = self._scan_delete(pattern, count=1000)
        if cnt:
            log.info("💥 ReportCache invalidated ALL reports for company=%s keys=%s", company_id, cnt)
        return cnt

    def clear(self) -> int:
        """Aggressive: delete all report cache keys."""
        cnt = self._scan_delete("rpt:*", count=1000)
        if cnt:
            log.info("🧨 ReportCache cleared all keys=%s", cnt)
        return cnt

    def get_stats(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "default_ttl": self.default_ttl,
            "max_size": self.max_size,
            "timestamp": datetime.utcnow().isoformat(),
            "redis_healthy": bool(redis_kv.ping()),
        }