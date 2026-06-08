from datetime import UTC, datetime
import base64
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.security.api_key import require_api_key


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


_CONVERSATIONS: dict[str, ConversationSummary] = {}
_MESSAGES: dict[str, list[dict[str, str]]] = {}


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


def _seed_demo_data() -> None:
    if _CONVERSATIONS:
        return

    now = datetime.now(UTC).isoformat()
    demo = ConversationSummary(
        id="conv_demo_1",
        source_url="https://example.restatify.tech",
        updated_at_gmt=now,
        unread_count=1,
    )

    _CONVERSATIONS[demo.id] = demo
    _MESSAGES[demo.id] = [
        {
            "message_id": "msg_1",
            "conversation_id": demo.id,
            "sender": "visitor",
            "message": "Hi support team, I need help with booking sync.",
            "time_gmt": now,
        }
    ]


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    _seed_demo_data()
    return list(_CONVERSATIONS.values())


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
    _seed_demo_data()
    messages = _MESSAGES.get(conversation_id, [])
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
    _seed_demo_data()

    now = datetime.now(UTC).isoformat()
    reply = ReplyResponse(
        conversation_id=conversation_id,
        sender="support",
        message=payload.message,
        time_gmt=now,
    )

    items = _MESSAGES.setdefault(conversation_id, [])
    items.append(
        {
            "message_id": f"msg_{len(items) + 1}",
            "conversation_id": conversation_id,
            "sender": reply.sender,
            "message": reply.message,
            "time_gmt": reply.time_gmt,
        }
    )

    if conversation_id in _CONVERSATIONS:
        current = _CONVERSATIONS[conversation_id]
        _CONVERSATIONS[conversation_id] = ConversationSummary(
            id=current.id,
            source_url=current.source_url,
            updated_at_gmt=now,
            unread_count=current.unread_count,
        )

    return reply
