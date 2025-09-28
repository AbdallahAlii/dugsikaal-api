# configs/redis_config.py
import redis
from typing import Optional
from .settings import settings

__redis_kv: Optional[redis.Redis] = None     # decode strings
__redis_raw: Optional[redis.Redis] = None    # raw bytes for Flask-Session

def get_redis_kv() -> redis.Redis:
    global __redis_kv
    if __redis_kv is None:
        __redis_kv = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return __redis_kv

def get_redis_raw() -> redis.Redis:
    global __redis_raw
    if __redis_raw is None:
        __redis_raw = redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)
    return __redis_raw

def ping_redis() -> bool:
    try:
        return bool(get_redis_kv().ping())
    except Exception:
        return False
