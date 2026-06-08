from secrets import compare_digest

from fastapi import Header

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.core.errors import unauthorized_error


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not x_api_key or not compare_digest(x_api_key, expected):
        raise unauthorized_error("Invalid API key")
