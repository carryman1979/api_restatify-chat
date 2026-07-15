from datetime import UTC, datetime
import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.security.wp_api_key_cache import invalidate_wp_api_keys_cache
from src.app.modules.support_chat.wp_chat_store_bridge import (
    WordPressBridgeConfig,
    WordPressBridgeError,
    WordPressChatStoreBridge,
)

router = APIRouter()
settings = get_settings()

_wp_bridge = WordPressChatStoreBridge(
    WordPressBridgeConfig(
        php_executable=settings.wp_php_executable,
        wp_load_path=settings.wp_load_path,
        store_option_key=settings.wp_chat_store_option_key,
        command_timeout_seconds=settings.wp_bridge_timeout_seconds,
        db_host_override=settings.wp_db_host_override,
        db_user_override=settings.wp_db_user_override,
        db_password_override=settings.wp_db_password_override,
        db_name_override=settings.wp_db_name_override,
    )
)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    mfa_required: bool = False


class GenerateApiKeyResponse(BaseModel):
    api_key: str


def _encode_session_token(user_id: int, user_login: str) -> str:
    payload_json = json.dumps(
        {
            "uid": user_id,
            "uln": user_login,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int(datetime.now(UTC).timestamp()) + 86400,
        },
        separators=(",", ":"),
    )
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()
    signature = hmac.new(
        settings.cursor_signing_key.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def _decode_session_token(token: str) -> dict:
    try:
        payload_b64, signature = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Invalid token format."}) from exc

    expected = hmac.new(
        settings.cursor_signing_key.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Invalid token signature."})

    try:
        payload_raw = base64.urlsafe_b64decode(payload_b64.encode()).decode("utf-8")
        payload = json.loads(payload_raw)
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise HTTPException(status_code=401, detail={"code": "token_expired", "message": "Session token expired."})
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Invalid token payload."}) from exc


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    try:
        result = _wp_bridge.validate_wp_credentials(payload.username, payload.password)
    except WordPressBridgeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "wp_bridge_failed", "message": str(exc)},
        ) from exc

    if not result.get("valid"):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Ungültiger Benutzername oder Passwort."},
        )

    if not result.get("has_capability"):
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_permissions", "message": "Kein Zugriff auf den Support-Chat."},
        )

    user_id = int(result["user_id"])
    user_login = str(result["user_login"])
    access_token = _encode_session_token(user_id, user_login)

    return LoginResponse(
        access_token=access_token,
        refresh_token="",
        mfa_required=False,
    )


@router.post("/generate-api-key", response_model=GenerateApiKeyResponse)
def generate_api_key(authorization: str | None = Header(default=None)) -> GenerateApiKeyResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "bearer_required", "message": "Bearer token required."})

    token = authorization[len("Bearer "):]
    session = _decode_session_token(token)
    user_id = int(session["uid"])
    user_login = str(session["uln"])

    try:
        api_key = _wp_bridge.generate_api_key(user_id, user_login)
        invalidate_wp_api_keys_cache()
    except WordPressBridgeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "wp_bridge_failed", "message": str(exc)},
        ) from exc

    return GenerateApiKeyResponse(api_key=api_key)
