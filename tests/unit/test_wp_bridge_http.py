import httpx

from src.app.modules.support_chat.wp_chat_store_bridge import (
    WordPressBridgeConfig,
    WordPressBridgeError,
    WordPressChatStoreBridge,
)


def test_http_bridge_posts_expected_payload_and_header(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict, headers: dict, timeout: int):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(200, json={"ok": True, "store": {}})

    monkeypatch.setattr(httpx, "post", fake_post)

    bridge = WordPressChatStoreBridge(
        WordPressBridgeConfig(
            php_executable="php",
            wp_load_path="../wp-load.php",
            store_option_key="restatify_ai_multichat_conversations",
            command_timeout_seconds=9,
            bridge_base_url="https://web.example.test/wp-json/restatify-support/v1",
            bridge_api_key="bridge-secret",
        )
    )

    assert bridge.load_store() == {}
    assert captured["url"] == "https://web.example.test/wp-json/restatify-support/v1/bridge"
    assert captured["json"] == {
        "action": "load_store",
        "store_option_key": "restatify_ai_multichat_conversations",
    }
    assert captured["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Restatify-Bridge-Key": "bridge-secret",
    }
    assert captured["timeout"] == 9


def test_http_bridge_raises_wordpress_bridge_error_on_http_failure(monkeypatch) -> None:
    def fake_post(url: str, *, json: dict, headers: dict, timeout: int):
        return httpx.Response(403, json={"message": "Unauthorized bridge request."})

    monkeypatch.setattr(httpx, "post", fake_post)

    bridge = WordPressChatStoreBridge(
        WordPressBridgeConfig(
            php_executable="php",
            wp_load_path="../wp-load.php",
            store_option_key="restatify_ai_multichat_conversations",
            command_timeout_seconds=9,
            bridge_base_url="https://web.example.test/wp-json/restatify-support/v1",
            bridge_api_key="wrong-key",
        )
    )

    try:
        bridge.load_store()
    except WordPressBridgeError as exc:
        assert str(exc) == "Unauthorized bridge request."
    else:
        raise AssertionError("Expected WordPressBridgeError for failed bridge response")