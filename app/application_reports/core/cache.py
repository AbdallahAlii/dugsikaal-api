# app/application_reports/core/cache.py
from __future__ import annotations
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import hashlib
import json

log = logging.getLogger(__name__)


class ReportCache:
    def __init__(self, enabled: bool = True, default_ttl: int = 300, max_size: int = 1000):
        self.enabled = enabled
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}

    def get_cache_key(self, report_name: str, filters: Dict[str, Any]) -> str:
        filter_str = json.dumps(filters, sort_keys=True, default=str)
        key_data = f"{report_name}:{filter_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, report_name: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        cache_key = self.get_cache_key(report_name, filters)

        if cache_key not in self._cache:
            return None

        cached_entry = self._cache[cache_key]

        # Check if entry has expired
        if time.time() > cached_entry['expires_at']:
            del self._cache[cache_key]
            del self._access_times[cache_key]
            return None

        # Update access time for LRU
        self._access_times[cache_key] = time.time()

        log.debug(f"Cache hit for {report_name}")
        return cached_entry['data']

    def set(self, report_name: str, filters: Dict[str, Any], data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        if not self.enabled:
            return

        # Evict if cache is too large (LRU)
        if len(self._cache) >= self.max_size:
            self._evict_oldest()

        cache_key = self.get_cache_key(report_name, filters)
        expires_at = time.time() + (ttl or self.default_ttl)

        self._cache[cache_key] = {
            'data': data,
            'expires_at': expires_at,
            'created_at': time.time(),
            'report_name': report_name
        }

        self._access_times[cache_key] = time.time()

        log.debug(f"Cached result for {report_name}, expires in {ttl or self.default_ttl}s")

    def _evict_oldest(self) -> None:
        if not self._access_times:
            return

        # Find the least recently used key
        oldest_key = min(self._access_times.items(), key=lambda x: x[1])[0]

        del self._cache[oldest_key]
        del self._access_times[oldest_key]

        log.debug("Evicted oldest cache entry due to size limits")

    def invalidate_report(self, report_name: str) -> None:
        keys_to_remove = []

        for key, cached in self._cache.items():
            if cached.get('report_name') == report_name:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._cache[key]
            del self._access_times[key]

        log.info(f"Invalidated {len(keys_to_remove)} cache entries for {report_name}")

    def invalidate_pattern(self, pattern: str) -> None:
        keys_to_remove = []

        for key, cached in self._cache.items():
            if pattern in cached.get('report_name', ''):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._cache[key]
            del self._access_times[key]

        log.info(f"Invalidated {len(keys_to_remove)} cache entries matching pattern: {pattern}")

    def clear(self) -> None:
        cache_size = len(self._cache)
        self._cache.clear()
        self._access_times.clear()
        log.info(f"Report cache cleared ({cache_size} entries removed)")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "total_entries": len(self._cache),
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
            "reports_cached": len(set(entry.get('report_name') for entry in self._cache.values()))
        }