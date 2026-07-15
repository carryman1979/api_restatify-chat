from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class _Subscriber:
    conversation_id: str | None
    queue: asyncio.Queue[dict]


class SupportChatEventManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, _Subscriber] = {}
        self._lock = asyncio.Lock()

    async def register(self, conversation_id: str | None = None) -> tuple[str, asyncio.Queue[dict]]:
        client_id = uuid.uuid4().hex
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

        async with self._lock:
            self._subscribers[client_id] = _Subscriber(
                conversation_id=conversation_id,
                queue=queue,
            )

        await queue.put({"type": "connected"})
        return client_id, queue

    async def unregister(self, client_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(client_id, None)

    async def publish_message_added(
        self,
        conversation_id: str,
        sender: str,
        message: str,
        time_gmt: str,
    ) -> None:
        await self._publish(
            {
                "type": "message_added",
                "conversation_id": conversation_id,
                "sender": sender,
                "message": message,
                "time_gmt": time_gmt,
            }
        )

    async def publish_conversation_deleted(self, conversation_id: str) -> None:
        await self._publish(
            {
                "type": "conversation_deleted",
                "conversation_id": conversation_id,
            }
        )

    async def _publish(self, payload: dict) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.values())

        conversation_id = payload.get("conversation_id")
        for subscriber in subscribers:
            if (
                subscriber.conversation_id
                and conversation_id
                and subscriber.conversation_id != conversation_id
            ):
                continue

            if subscriber.queue.full():
                try:
                    subscriber.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                subscriber.queue.put_nowait(payload)
            except asyncio.QueueFull:
                continue


_event_manager = SupportChatEventManager()


def get_event_manager() -> SupportChatEventManager:
    return _event_manager
