from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "api_restatify-chat"
    app_env: str = "dev"
    api_key: str = "dev-support-api-key"
    cursor_signing_key: str = "change-me-cursor-signing-key"
    cursor_ttl_seconds: int = 900
    log_level: str = "INFO"
    wp_load_path: str = "../wp-load.php"
    wp_php_executable: str = "php"
    wp_chat_store_option_key: str = "restatify_ai_multichat_conversations"
    wp_bridge_timeout_seconds: int = 15
    wp_bridge_base_url: str = ""
    wp_bridge_api_key: str = ""
    wp_db_host_override: str = ""
    wp_db_user_override: str = ""
    wp_db_password_override: str = ""
    wp_db_name_override: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
