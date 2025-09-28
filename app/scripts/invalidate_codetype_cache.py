# app/scripts/invalidate_codetype_cache.py
from app.common.cache.cache import bump_version
from app.common.cache.cache_keys import detail_version_key
import sys

DEFAULT_PREFIXES = ("WH", "JE")

def invalidate(*prefixes: str):
    for p in prefixes:
        bump_version(detail_version_key("codetype", p))
        print(f"Invalidated codetype cache for prefix={p}")

if __name__ == "__main__":
    prefixes = sys.argv[1:] or list(DEFAULT_PREFIXES)
    invalidate(*prefixes)
