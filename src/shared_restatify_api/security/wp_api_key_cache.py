from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_cache_lock = threading.Lock()
_cached_keys: frozenset[str] = frozenset()
_last_fetch: float = 0.0
_CACHE_TTL_SECONDS = 60


def invalidate_wp_api_keys_cache() -> None:
    global _cached_keys, _last_fetch
    with _cache_lock:
        _cached_keys = frozenset()
        _last_fetch = 0.0


def get_valid_wp_api_keys(force_refresh: bool = False) -> frozenset[str]:
    """Returns WP-stored API keys, refreshed at most every 60 seconds."""
    global _cached_keys, _last_fetch

    now = time.monotonic()
    with _cache_lock:
        if not force_refresh and now - _last_fetch < _CACHE_TTL_SECONDS:
            return _cached_keys

    try:
        # Import here to avoid circular dependency at module load time.
        from src.shared_restatify_api.config.settings import get_settings
        from src.app.modules.support_chat.wp_chat_store_bridge import (
            WordPressChatStoreBridge,
            build_wordpress_bridge_config,
        )

        cfg = get_settings()
        bridge = WordPressChatStoreBridge(build_wordpress_bridge_config(cfg))
        keys = bridge.load_api_keys()
        fresh: frozenset[str] = frozenset(keys)
    except Exception:  # noqa: BLE001
        fresh = frozenset()

    with _cache_lock:
        _cached_keys = fresh
        _last_fetch = time.monotonic()

    return fresh
