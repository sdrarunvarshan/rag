from __future__ import annotations

import json
import logging
from typing import Any

import valkey

from app.config import CACHE_TTL_SECONDS, VALKEY_URL

log = logging.getLogger(__name__)

_client: valkey.Valkey | None = None


def get_client() -> valkey.Valkey:
    global _client
    if _client is None:
        _client = valkey.Valkey.from_url(
            VALKEY_URL,
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _client


def ping() -> bool:
    try:
        return bool(get_client().ping())
    except Exception as exc:
        log.warning("Valkey ping failed: %s", exc)
        return False


def get_json(key: str) -> Any | None:
    try:
        raw = get_client().get(key)
    except Exception as exc:
        log.warning("Valkey get failed: %s", exc)
        return None
    if not raw:
        return None
    return json.loads(raw)


def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    try:
        get_client().setex(key, ttl or CACHE_TTL_SECONDS, json.dumps(value))
    except Exception as exc:
        log.warning("Valkey set failed: %s", exc)


def invalidate_user_cache(user_id: str) -> None:
    """Invalidate all cache entries for a specific user."""
    try:
        client = get_client()
        # Use SCAN to find all keys matching the user's cache pattern
        pattern = f"*{user_id}*"
        cursor = 0
        keys_to_delete = []
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            keys_to_delete.extend(keys)
            if cursor == 0:
                break
        if keys_to_delete:
            client.delete(*keys_to_delete)
            log.info("Invalidated %d cache entries for user %s", len(keys_to_delete), user_id)
    except Exception as exc:
        log.warning("Failed to invalidate user cache: %s", exc)
