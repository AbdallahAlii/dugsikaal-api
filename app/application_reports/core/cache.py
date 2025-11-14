# # app/application_reports/core/cache.py

from __future__ import annotations
import hashlib, json, logging, re
from typing import Any, Dict, Optional
from datetime import datetime

from config.redis_config import get_redis_kv

log = logging.getLogger(__name__)
r = get_redis_kv()

# ----------------- helpers -----------------
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "report"

def _clean_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    volatile = {"nocache", "_ts", "cache", "export_format"}
    # normalize dates to string to keep key stable
    def _ser(v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v
    return {k: _ser(v) for k, v in (filters or {}).items() if k not in volatile}

def _hash_obj(o: Any) -> str:
    s = json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _ver_key(report_slug: str, company_id: int) -> str:
    return f"v:rpt:{report_slug}:co{int(company_id)}"

def _get_ver(report_slug: str, company_id: int) -> int:
    v = r.get(_ver_key(report_slug, company_id))
    try:
        return int(v or 0)
    except Exception:
        return 0

# ----------------- cache -----------------
class ReportCache:
    """
    Redis cache for report payloads with versioned keys.
    Key: rpt:<report-slug>:co<company_id>:v<version>:<hash(filters)>
    """
    def __init__(self, *, enabled: bool = True, default_ttl: int = 30, max_size: int = 10000):
        self.enabled = bool(enabled)
        self.default_ttl = int(default_ttl)
        self.max_size = int(max_size)  # not used by Redis but kept for parity

    # ---------- key building ----------
    def _key(self, report_name: str, filters: Dict[str, Any]) -> str:
        rep = _slug(report_name)
        co = int((filters or {}).get("company") or 0)
        ver = _get_ver(rep, co)  # <---- include bumped version!
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
            raw = r.get(key)
            if not raw:
                return None
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            result = json.loads(raw)
            log.debug("✅ Report cache HIT: %s", key)
            return result
        except Exception as e:
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
            r.setex(key, int(ttl or self.default_ttl), payload)
            log.debug("💾 Report cache SET: %s", key)
        except Exception as e:
            log.warning("ReportCache.set failed key=%s err=%s", key, e)

    # ---------- invalidation (two modes) ----------
    def bump_company(self, report_name: str, company_id: int) -> int:
        """O(1) version bump. Leaves old keys to expire naturally."""
        rep = _slug(report_name)
        v = int(r.incr(_ver_key(rep, int(company_id))))
        log.info("🔥 BUMP report cache %s company=%s -> v%s", rep, company_id, v)
        return v

    def invalidate_report(self, report_name: str) -> int:
        """Aggressive: delete all cached variants of a report (all companies)."""
        pref = self._prefix_report(report_name)
        cnt = 0
        try:
            for k in r.scan_iter(match=pref + "*", count=500):
                cnt += int(r.delete(k) or 0)
            log.info("🧹 ReportCache invalidated report=%s keys=%s", report_name, cnt)
        except Exception as e:
            log.error("ReportCache.invalidate_report failed: %s", e)
        return cnt

    def invalidate_company(self, report_name: str, company_id: int) -> int:
        """Aggressive: delete a report's keys for one company."""
        pref = self._prefix_report_company(report_name, company_id)
        cnt = 0
        try:
            for k in r.scan_iter(match=pref + "*", count=500):
                cnt += int(r.delete(k) or 0)
            log.info("🧹 ReportCache invalidated report=%s company=%s keys=%s",
                     report_name, company_id, cnt)
        except Exception as e:
            log.error("ReportCache.invalidate_company failed: %s", e)
        return cnt

    def invalidate_company_all_reports(self, company_id: int) -> int:
        """Aggressive: delete ALL reports for a company."""
        cnt = 0
        try:
            for k in r.scan_iter(match=f"rpt:*:co{int(company_id)}:*", count=1000):
                cnt += int(r.delete(k) or 0)
            log.info("💥 ReportCache invalidated ALL reports for company=%s keys=%s", company_id, cnt)
        except Exception as e:
            log.error("ReportCache.invalidate_company_all_reports failed: %s", e)
        return cnt

    def clear(self) -> int:
        cnt = 0
        try:
            for k in r.scan_iter(match="rpt:*", count=1000):
                cnt += int(r.delete(k) or 0)
            log.info("🧨 ReportCache cleared all keys=%s", cnt)
        except Exception as e:
            log.error("ReportCache.clear failed: %s", e)
        return cnt

    def get_stats(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "default_ttl": self.default_ttl,
            "max_size": self.max_size,
            "timestamp": datetime.utcnow().isoformat()
        }
