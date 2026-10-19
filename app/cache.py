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
    """
    Invalidate all cache entries for a specific user.

    Since cache keys are hashed (SHA-256), we maintain a tracking set
    of cache keys per user. This function deletes all tracked keys
    for the given user and cleans up the tracking set.
    """
    try:
        client = get_client()
        tracking_key = f"rag:user_keys:{user_id}"
        
        # Get all cache keys for this user
        cache_keys = client.smembers(tracking_key)
        
        if cache_keys:
            # Delete the actual cache entries
            client.delete(*cache_keys)
            # Delete the tracking set
            client.delete(tracking_key)
            log.info("Invalidated %d cache entries for user %s", len(cache_keys), user_id)
        else:
            log.info("No cache entries to invalidate for user %s", user_id)
    except Exception as exc:
        log.warning("Failed to invalidate user cache: %s", exc)


def track_cache_key(user_id: str, cache_key: str) -> None:
    """
    Track a cache key for a specific user to enable invalidation.

    Args:
        user_id: The user ID
        cache_key: The cache key to track
    """
    try:
        client = get_client()
        tracking_key = f"rag:user_keys:{user_id}"
        client.sadd(tracking_key, cache_key)
    except Exception as exc:
        log.warning("Failed to track cache key: %s", exc)
