from fastapi.testclient import TestClient

from src.app.main import app
from src.app.modules.support_chat import router as support_chat_router


client = TestClient(app)


HEADERS = {"X-API-Key": support_chat_router.settings.api_key}


class _FakeBridge:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {
            "conv_test_1": {
                "id": "conv_test_1",
                "source_url": "https://example.test",
                "updated_at_gmt": "2026-06-15T10:00:00+00:00",
                "ai_mode": "both",
                "messages": [
                    {
                        "sender": "visitor",
                        "message": "Initial question",
                        "time_gmt": "2026-06-15T09:59:00+00:00",
                    }
                ],
            }
        }
        self.booking_overlay_available = True

    def load_store(self) -> dict[str, dict]:
        return self.store

    def append_support_message(self, conversation_id: str, message: str) -> dict[str, str]:
        conversation = self.store[conversation_id]
        entry = {
            "sender": "support",
            "message": message,
            "time_gmt": "2026-06-15T10:01:00+00:00" if "first" in message else "2026-06-15T10:02:00+00:00",
        }
        conversation.setdefault("messages", []).append(entry)
        conversation["updated_at_gmt"] = entry["time_gmt"]
        return {
            "conversation_id": conversation_id,
            "sender": entry["sender"],
            "message": entry["message"],
            "time_gmt": entry["time_gmt"],
        }

    def get_conversation_tools(self, conversation_id: str) -> dict[str, object]:
        if conversation_id not in self.store:
            raise support_chat_router.WordPressBridgeError("Conversation not found")

        return {
            "conversation_id": conversation_id,
            "ai_mode": self.store[conversation_id].get("ai_mode", "both"),
            "booking_overlay_available": self.booking_overlay_available,
        }

    def set_conversation_ai_mode(self, conversation_id: str, ai_mode: str) -> str:
        if conversation_id not in self.store:
            raise support_chat_router.WordPressBridgeError("Conversation not found")

        self.store[conversation_id]["ai_mode"] = ai_mode
        return ai_mode

    def delete_conversation(self, conversation_id: str) -> dict[str, bool]:
        if conversation_id not in self.store:
            return {"deleted": True, "already_gone": True}

        del self.store[conversation_id]
        return {"deleted": True, "already_gone": False}

    def trigger_booking_overlay(self, conversation_id: str) -> dict[str, str]:
        if conversation_id not in self.store:
            raise support_chat_router.WordPressBridgeError("Conversation not found")

        if not self.booking_overlay_available:
            raise support_chat_router.WordPressBridgeError("Booking overlay unavailable")

        entry = {
            "sender": "support",
            "message": "[[RESTATIFY_BOOKING_OPEN]] booking overlay open",
            "time_gmt": "2026-06-15T10:03:00+00:00",
        }
        self.store[conversation_id].setdefault("messages", []).append(entry)
        self.store[conversation_id]["updated_at_gmt"] = entry["time_gmt"]
        return {
            "conversation_id": conversation_id,
            "sender": entry["sender"],
            "message": entry["message"],
            "time_gmt": entry["time_gmt"],
        }


def _install_fake_bridge() -> object:
    original_bridge = support_chat_router.wp_bridge
    support_chat_router.wp_bridge = _FakeBridge()
    return original_bridge


def _restore_bridge(original_bridge: object) -> None:
    support_chat_router.wp_bridge = original_bridge


def test_support_messages_supports_pagination_and_order() -> None:
    original_bridge = _install_fake_bridge()
    try:
        reply_1 = client.post(
            "/v1/support/conversations/conv_test_1/reply",
            headers=HEADERS,
            json={"message": "first support reply"},
        )
        assert reply_1.status_code == 200

        reply_2 = client.post(
            "/v1/support/conversations/conv_test_1/reply",
            headers=HEADERS,
            json={"message": "second support reply"},
        )
        assert reply_2.status_code == 200

        desc = client.get(
            "/v1/support/conversations/conv_test_1/messages?order=desc&limit=1",
            headers=HEADERS,
        )
        assert desc.status_code == 200
        desc_page = desc.json()
        desc_items = desc_page["items"]
        assert len(desc_items) == 1
        assert desc_items[0]["message"] == "second support reply"
        assert desc_page["next_cursor"] is not None
        assert desc_page["has_more"] is True

        next_cursor = desc_page["next_cursor"]

        asc_offset = client.get(
            f"/v1/support/conversations/conv_test_1/messages?order=desc&limit=1&cursor={next_cursor}",
            headers=HEADERS,
        )
        assert asc_offset.status_code == 200
        asc_page = asc_offset.json()
        asc_items = asc_page["items"]
        assert len(asc_items) == 1
        assert asc_items[0]["message"] == "first support reply"

        tampered = client.get(
            f"/v1/support/conversations/conv_test_1/messages?order=desc&limit=1&cursor={next_cursor}x",
            headers=HEADERS,
        )
        assert tampered.status_code == 400
        assert tampered.json()["detail"]["code"] == "invalid_cursor"
    finally:
        _restore_bridge(original_bridge)


def test_support_messages_returns_cursor_expired_error() -> None:
    original_bridge = _install_fake_bridge()
    original_ttl = support_chat_router.settings.cursor_ttl_seconds
    try:
        client.post(
            "/v1/support/conversations/conv_test_1/reply",
            headers=HEADERS,
            json={"message": "first support reply"},
        )

        response = client.get(
            "/v1/support/conversations/conv_test_1/messages?order=desc&limit=1",
            headers=HEADERS,
        )
        assert response.status_code == 200
        cursor = response.json()["next_cursor"]
        assert cursor is not None

        support_chat_router.settings.cursor_ttl_seconds = -1
        expired = client.get(
            f"/v1/support/conversations/conv_test_1/messages?order=desc&limit=1&cursor={cursor}",
            headers=HEADERS,
        )

        assert expired.status_code == 410
        assert expired.json()["detail"]["code"] == "cursor_expired"
    finally:
        support_chat_router.settings.cursor_ttl_seconds = original_ttl
        _restore_bridge(original_bridge)


def test_conversation_tools_get_and_set_ai_mode() -> None:
    original_bridge = _install_fake_bridge()
    try:
        response = client.get(
            "/v1/support/conversations/conv_test_1/tools",
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["ai_mode"] == "both"

        update = client.put(
            "/v1/support/conversations/conv_test_1/ai-mode",
            headers=HEADERS,
            json={"ai_mode": "visitor"},
        )
        assert update.status_code == 200
        assert update.json()["ai_mode"] == "visitor"

        after = client.get(
            "/v1/support/conversations/conv_test_1/tools",
            headers=HEADERS,
        )
        assert after.status_code == 200
        assert after.json()["ai_mode"] == "visitor"
    finally:
        _restore_bridge(original_bridge)


def test_conversation_open_booking_overlay() -> None:
    original_bridge = _install_fake_bridge()
    try:
        response = client.post(
            "/v1/support/conversations/conv_test_1/open-booking-overlay",
            headers=HEADERS,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["sender"] == "support"
        assert "RESTATIFY_BOOKING_OPEN" in payload["message"]
    finally:
        _restore_bridge(original_bridge)


def test_conversation_delete_endpoint() -> None:
    original_bridge = _install_fake_bridge()
    try:
        response = client.delete(
            "/v1/support/conversations/conv_test_1",
            headers=HEADERS,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["deleted"] is True
        assert payload["already_gone"] is False

        second = client.delete(
            "/v1/support/conversations/conv_test_1",
            headers=HEADERS,
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["deleted"] is True
        assert second_payload["already_gone"] is True
    finally:
        _restore_bridge(original_bridge)
