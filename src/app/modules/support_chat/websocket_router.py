from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect

from src.app.modules.support_chat.events import get_event_manager
from src.app.modules.support_chat.wp_chat_store_bridge import (
    WordPressBridgeConfig,
    WordPressChatStoreBridge,
)
from src.shared_restatify_api.config.settings import get_settings
from src.shared_restatify_api.security.api_key import is_valid_api_key


router = APIRouter()
logger = logging.getLogger(__name__)

settings = get_settings()
visitor_wp_bridge = WordPressChatStoreBridge(
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

_store_watcher_task: asyncio.Task[None] | None = None
_store_watcher_lock = asyncio.Lock()


def _extract_latest_message(conversation: dict) -> tuple[str, str, str, int] | None:
    raw_messages = conversation.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None

    latest_raw = raw_messages[-1]
    if not isinstance(latest_raw, dict):
        return None

    sender = str(latest_raw.get("sender", "")).strip()
    message = str(latest_raw.get("message", "")).strip()
    time_gmt = str(latest_raw.get("time_gmt", "")).strip()
    return sender, message, time_gmt, len(raw_messages)


async def _publish_store_deltas_loop() -> None:
    """Publishes visitor-originated message updates from WP store to websocket event manager."""
    previous_signatures: dict[str, tuple[str, str, str, int]] = {}
    event_manager = get_event_manager()

    while True:
        try:
            store = await asyncio.to_thread(visitor_wp_bridge.load_store)
            current_ids: set[str] = set()

            for conversation_id, conversation in store.items():
                if not isinstance(conversation_id, str) or not isinstance(conversation, dict):
                    continue
                current_ids.add(conversation_id)

                latest = _extract_latest_message(conversation)
                if latest is None:
                    continue

                previous = previous_signatures.get(conversation_id)
                previous_signatures[conversation_id] = latest
                if previous == latest:
                    continue

                sender, message, time_gmt, _ = latest
                # Support messages are already published directly by API endpoints.
                if sender.lower() == "support":
                    continue

                await event_manager.publish_message_added(
                    conversation_id=conversation_id,
                    sender=sender or "visitor",
                    message=message,
                    time_gmt=time_gmt,
                )

            removed_conversation_ids = set(previous_signatures.keys()) - current_ids
            for removed_conversation_id in removed_conversation_ids:
                previous_signatures.pop(removed_conversation_id, None)
                await event_manager.publish_conversation_deleted(removed_conversation_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("Support store watcher failed: %s", exc)

        await asyncio.sleep(1.5)


async def _ensure_store_watcher_running() -> None:
    global _store_watcher_task

    async with _store_watcher_lock:
        if _store_watcher_task is not None and not _store_watcher_task.done():
            return

        _store_watcher_task = asyncio.create_task(_publish_store_deltas_loop(), name="support-store-watcher")


@router.websocket("/ws/updates")
async def support_updates(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
) -> None:
    await _ensure_store_watcher_running()

    header_key = websocket.headers.get("x-api-key")
    effective_key = (api_key or header_key or "").strip()
    if not is_valid_api_key(effective_key):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    event_manager = get_event_manager()
    client_id, queue = await event_manager.register(conversation_id=conversation_id)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await event_manager.unregister(client_id)


@router.websocket("/ws/visitor-updates")
async def visitor_updates(
    websocket: WebSocket,
    conversation_id: str | None = Query(default=None),
    conversation_token: str | None = Query(default=None),
) -> None:
    await _ensure_store_watcher_running()

    effective_conversation_id = (conversation_id or "").strip()
    effective_token = (conversation_token or "").strip()
    if not effective_conversation_id or not effective_token:
        await websocket.close(code=1008)
        return

    if not visitor_wp_bridge.validate_conversation_token(effective_conversation_id, effective_token):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    event_manager = get_event_manager()
    client_id, queue = await event_manager.register(conversation_id=effective_conversation_id)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await event_manager.unregister(client_id)
