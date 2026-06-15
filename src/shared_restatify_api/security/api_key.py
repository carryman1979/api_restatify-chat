from secrets import compare_digest

from fastapi import Header

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.core.errors import unauthorized_error


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not x_api_key:
        raise unauthorized_error("Invalid API key")

    env_key = get_settings().api_key
    if compare_digest(x_api_key, env_key):
        return

    from src.shared_restatify_api.security.wp_api_key_cache import get_valid_wp_api_keys
    wp_keys = get_valid_wp_api_keys()
    if any(compare_digest(x_api_key, k) for k in wp_keys):
        return

    raise unauthorized_error("Invalid API key")
