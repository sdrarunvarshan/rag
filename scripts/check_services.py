import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cache import ping as cache_ping
from app.config import DATABASE_URL, DATABASE_URL_FALLBACK, VALKEY_URL
from app.db import ensure_database, init_schema, ping as db_ping, resolve_database_url

print("DATABASE_URL", DATABASE_URL)
print("DATABASE_URL_FALLBACK", DATABASE_URL_FALLBACK)
print("VALKEY_URL", VALKEY_URL)
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
