from fastapi.testclient import TestClient

from src.app.main import app
from src.app.modules.support_chat import router as support_chat_router


client = TestClient(app)


HEADERS = {"X-API-Key": "change-me"}


def test_support_messages_supports_pagination_and_order() -> None:
    reply_1 = client.post(
        "/v1/support/conversations/conv_demo_1/reply",
        headers=HEADERS,
        json={"message": "first support reply"},
    )
    assert reply_1.status_code == 200

    reply_2 = client.post(
        "/v1/support/conversations/conv_demo_1/reply",
        headers=HEADERS,
        json={"message": "second support reply"},
    )
    assert reply_2.status_code == 200

    desc = client.get(
        "/v1/support/conversations/conv_demo_1/messages?order=desc&limit=1",
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
        f"/v1/support/conversations/conv_demo_1/messages?order=desc&limit=1&cursor={next_cursor}",
        headers=HEADERS,
    )
    assert asc_offset.status_code == 200
    asc_page = asc_offset.json()
    asc_items = asc_page["items"]
    assert len(asc_items) == 1
    assert asc_items[0]["message"] == "first support reply"

    tampered = client.get(
        f"/v1/support/conversations/conv_demo_1/messages?order=desc&limit=1&cursor={next_cursor}x",
        headers=HEADERS,
    )
    assert tampered.status_code == 400
    assert tampered.json()["detail"]["code"] == "invalid_cursor"


def test_support_messages_returns_cursor_expired_error() -> None:
    response = client.get(
        "/v1/support/conversations/conv_demo_1/messages?order=desc&limit=1",
        headers=HEADERS,
    )
    assert response.status_code == 200
    cursor = response.json()["next_cursor"]
    assert cursor is not None

    original_ttl = support_chat_router.settings.cursor_ttl_seconds
    try:
        support_chat_router.settings.cursor_ttl_seconds = -1
        expired = client.get(
            f"/v1/support/conversations/conv_demo_1/messages?order=desc&limit=1&cursor={cursor}",
            headers=HEADERS,
        )
    finally:
        support_chat_router.settings.cursor_ttl_seconds = original_ttl

    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "cursor_expired"
