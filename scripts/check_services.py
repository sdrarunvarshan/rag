import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cache import ping as cache_ping
from app.config import (
    DATABASE_URL,
    DATABASE_URL_FALLBACK,
    GARAGE_BUCKET,
    GARAGE_ENDPOINT,
    VALKEY_URL,
)
from app.repositories import ensure_database, init_schema, ping as db_ping, resolve_database_url
from app.garage_client import ensure_bucket, ping as garage_ping

print("DATABASE_URL", DATABASE_URL)
print("DATABASE_URL_FALLBACK", DATABASE_URL_FALLBACK)
print("VALKEY_URL", VALKEY_URL)
print("GARAGE_ENDPOINT", GARAGE_ENDPOINT)
print("GARAGE_BUCKET", GARAGE_BUCKET)
try:
    active = resolve_database_url()
    print("active_url", active)
except Exception as exc:
    print("resolve_database_url: FAIL", type(exc).__name__, exc)
try:
    ensure_database()
    print("ensure_database: ok")
except Exception as exc:
    print("ensure_database: FAIL", type(exc).__name__, exc)
print("postgres ping", db_ping())
try:
    init_schema()
    print("init_schema: ok")
except Exception as exc:
    print("init_schema: FAIL", type(exc).__name__, exc)
print("valkey ping", cache_ping())
try:
    ensure_bucket()
    print("ensure_bucket: ok")
except Exception as exc:
    print("ensure_bucket: FAIL", type(exc).__name__, exc)
print("garage ping", garage_ping())
