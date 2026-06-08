from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "api_restatify-chat"
    app_env: str = "dev"
    api_key: str = "change-me"
    cursor_signing_key: str = "change-me-cursor-signing-key"
    cursor_ttl_seconds: int = 900
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
