from secrets import compare_digest

from fastapi import Header

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.core.errors import unauthorized_error


def is_valid_api_key(x_api_key: str | None) -> bool:
    if not x_api_key:
        return False

    env_key = get_settings().api_key
    if compare_digest(x_api_key, env_key):
        return True

    from src.shared_restatify_api.security.wp_api_key_cache import get_valid_wp_api_keys
    wp_keys = get_valid_wp_api_keys()
    if any(compare_digest(x_api_key, k) for k in wp_keys):
        return True

    # Retry once with forced refresh to avoid false negatives from a still-warm cache
    # right after a new key was generated.
    wp_keys = get_valid_wp_api_keys(force_refresh=True)
    if any(compare_digest(x_api_key, k) for k in wp_keys):
        return True

    return False


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not is_valid_api_key(x_api_key):
        raise unauthorized_error("Invalid API key")
