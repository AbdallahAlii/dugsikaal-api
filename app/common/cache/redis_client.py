# app/common/cache/redis_client.py
from __future__ import annotations
import logging
import redis
from typing import Optional, Any
from config.settings import settings

log = logging.getLogger(__name__)

class SafeRedis:
    def __init__(self, url: str, *, decode_responses: bool = True):
        self.url = url
        self.decode_responses = decode_responses
        self._r: Optional[redis.Redis] = None

    def _client(self) -> redis.Redis:
        if self._r is None:
            self._r = redis.Redis.from_url(
                self.url,
                decode_responses=self.decode_responses,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                retry_on_timeout=False,
            )
        return self._r

    def ping(self) -> bool:
        try:
            return bool(self._client().ping())
        except Exception:
            return False

    # ---- KV ----
    def get(self, key: str) -> Optional[str]:
        try:
            return self._client().get(key)
        except Exception:
            return None

    def setex(self, key: str, ttl: int, value: str) -> bool:
        try:
            self._client().setex(key, ttl, value)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> int:
        try:
            return int(self._client().delete(key) or 0)
        except Exception:
            return 0

    def incr(self, key: str) -> int:
        try:
            return int(self._client().incr(key))
        except Exception:
            return 0

    # ---- HASH ----
    def hget(self, name: str, field: str) -> Optional[str]:
        try:
            return self._client().hget(name, field)
        except Exception:
            return None

    def hset(self, name: str, field: str, value: str) -> bool:
        try:
            self._client().hset(name, field, value)
            return True
        except Exception:
            return False

    def expire(self, name: str, ttl: int) -> bool:
        try:
            return bool(self._client().expire(name, ttl))
        except Exception:
            return False

    def hdel(self, name: str, field: str) -> int:
        try:
            return int(self._client().hdel(name, field) or 0)
        except Exception:
            return 0


redis_kv = SafeRedis(settings.REDIS_URL, decode_responses=True)
redis_raw = SafeRedis(settings.REDIS_URL, decode_responses=False)