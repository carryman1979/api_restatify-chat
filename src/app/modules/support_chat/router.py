from datetime import UTC, datetime
import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.security.api_key import require_api_key
from src.app.modules.support_chat.wp_chat_store_bridge import (
    WordPressBridgeConfig,
    WordPressBridgeError,
    WordPressChatStoreBridge,
)


router = APIRouter(dependencies=[Depends(require_api_key)])
settings = get_settings()


class ConversationSummary(BaseModel):
    id: str
    source_url: str
    updated_at_gmt: str
    unread_count: int


class ReplyRequest(BaseModel):
    message: str


class ReplyResponse(BaseModel):
    conversation_id: str
    sender: str
    message: str
    time_gmt: str


class ConversationMessage(BaseModel):
    message_id: str
    conversation_id: str
    sender: str
    message: str
    time_gmt: str


class ConversationMessagesPage(BaseModel):
    items: list[ConversationMessage]
    next_cursor: str | None
    has_more: bool


wp_bridge = WordPressChatStoreBridge(
    WordPressBridgeConfig(
        php_executable=settings.wp_php_executable,
        wp_load_path=settings.wp_load_path,
        store_option_key=settings.wp_chat_store_option_key,
        command_timeout_seconds=settings.wp_bridge_timeout_seconds,
    )
)


def _sign_payload(payload: str) -> str:
    digest = hmac.new(
        settings.cursor_signing_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def _encode_cursor(time_gmt: str, message_id: str) -> str:
    payload_json = json.dumps(
        {
            "t": time_gmt,
            "m": message_id,
            "iat": int(datetime.now(UTC).timestamp()),
        },
        separators=(",", ":"),
    )
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
    signature = _sign_payload(payload_b64)
    return f"{payload_b64}.{signature}"


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload_b64, signature = cursor.split(".", maxsplit=1)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_cursor", "message": "Invalid cursor format."},
        ) from exc

    expected = _sign_payload(payload_b64)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_cursor", "message": "Invalid cursor signature."},
        )

    try:
        payload_raw = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        payload = json.loads(payload_raw)
        issued_at = int(payload["iat"])
        now = int(datetime.now(UTC).timestamp())
        if now - issued_at > settings.cursor_ttl_seconds:
            raise HTTPException(
                status_code=410,
                detail={"code": "cursor_expired", "message": "Cursor expired."},
            )

        return str(payload["t"]), str(payload["m"])
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, HTTPException):
            raise

        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_cursor", "message": "Invalid cursor payload."},
        ) from exc


def _load_store_or_raise() -> dict[str, dict]:
    try:
        return wp_bridge.load_store()
    except WordPressBridgeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "wp_bridge_failed", "message": str(exc)},
        ) from exc


def _normalize_messages(conversation_id: str, conversation: dict) -> list[dict[str, str]]:
    raw_messages = conversation.get("messages")
    if not isinstance(raw_messages, list):
        return []

    normalized: list[dict[str, str]] = []
    for index, raw_item in enumerate(raw_messages, start=1):
        if not isinstance(raw_item, dict):
            continue

        sender = str(raw_item.get("sender", "visitor"))
        message = str(raw_item.get("message", ""))
        time_gmt = str(raw_item.get("time_gmt", ""))

        normalized.append(
            {
                "message_id": f"msg_{index}",
                "conversation_id": conversation_id,
                "sender": sender,
                "message": message,
                "time_gmt": time_gmt,
            }
        )

    return normalized


def _to_summary(conversation_id: str, conversation: dict) -> ConversationSummary:
    source_url = str(conversation.get("source_url", ""))
    updated_at_gmt = str(conversation.get("updated_at_gmt", ""))
    messages = conversation.get("messages")
    unread_count = 0
    if isinstance(messages, list):
        unread_count = sum(
            1
            for item in messages
            if isinstance(item, dict) and str(item.get("sender", "")) == "visitor"
        )

    return ConversationSummary(
        id=conversation_id,
        source_url=source_url,
        updated_at_gmt=updated_at_gmt,
        unread_count=unread_count,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    store = _load_store_or_raise()
    summaries = [_to_summary(conversation_id, conversation) for conversation_id, conversation in store.items()]
    return sorted(summaries, key=lambda item: item.updated_at_gmt, reverse=True)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesPage,
)
def list_messages(
    conversation_id: str = Path(..., min_length=3),
    cursor: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> ConversationMessagesPage:
    store = _load_store_or_raise()
    conversation = store.get(conversation_id, {})
    messages = _normalize_messages(conversation_id, conversation)
    reverse = order == "desc"
    sorted_messages = sorted(
        messages,
        key=lambda item: (item["time_gmt"], item["message_id"]),
        reverse=reverse,
    )

    if cursor:
        cursor_time, cursor_message_id = _decode_cursor(cursor)
        cursor_key = (cursor_time, cursor_message_id)
        if reverse:
            sorted_messages = [
                item
                for item in sorted_messages
                if (item["time_gmt"], item["message_id"]) < cursor_key
            ]
        else:
            sorted_messages = [
                item
                for item in sorted_messages
                if (item["time_gmt"], item["message_id"]) > cursor_key
            ]

    window = sorted_messages[:limit]
    has_more = len(sorted_messages) > len(window)
    next_cursor = None
    if has_more and window:
        next_cursor = _encode_cursor(window[-1]["time_gmt"], window[-1]["message_id"])

    return ConversationMessagesPage(
        items=[ConversationMessage(**item) for item in window],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/conversations/{conversation_id}/reply",
    response_model=ReplyResponse,
)
def send_reply(
    payload: ReplyRequest,
    conversation_id: str = Path(..., min_length=3),
) -> ReplyResponse:
    try:
        result = wp_bridge.append_support_message(conversation_id=conversation_id, message=payload.message)
    except WordPressBridgeError as exc:
        message = str(exc)
        if "Conversation not found" in message:
            raise HTTPException(
                status_code=404,
                detail={"code": "conversation_not_found", "message": message},
            ) from exc

        raise HTTPException(
            status_code=502,
            detail={"code": "wp_bridge_failed", "message": message},
        ) from exc

    return ReplyResponse(
        conversation_id=result["conversation_id"],
        sender=result["sender"],
        message=result["message"],
        time_gmt=result["time_gmt"],
    )
