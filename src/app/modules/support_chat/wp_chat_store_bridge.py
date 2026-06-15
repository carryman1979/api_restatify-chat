from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WordPressBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WordPressBridgeConfig:
    php_executable: str
    wp_load_path: str
    store_option_key: str
    command_timeout_seconds: int


class WordPressChatStoreBridge:
    def __init__(self, config: WordPressBridgeConfig) -> None:
        self._config = config

    def load_store(self) -> dict[str, dict[str, Any]]:
        payload = self._run_bridge({"action": "load_store"})
        raw_store = payload.get("store", {})
        if not isinstance(raw_store, dict):
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for key, value in raw_store.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[key] = value

        return normalized

    def append_support_message(self, conversation_id: str, message: str) -> dict[str, str]:
        payload = self._run_bridge(
            {
                "action": "append_support_message",
                "conversation_id": conversation_id,
                "message": message,
            }
        )

        entry = payload.get("entry")
        if not isinstance(entry, dict):
            raise WordPressBridgeError("WordPress bridge returned invalid reply payload.")

        sender = str(entry.get("sender", "support"))
        text = str(entry.get("message", ""))
        time_gmt = str(entry.get("time_gmt", ""))

        return {
            "conversation_id": conversation_id,
            "sender": sender,
            "message": text,
            "time_gmt": time_gmt,
        }

    def validate_wp_credentials(self, email: str, password: str) -> dict[str, Any]:
        """Validates WordPress credentials, returns user info and capabilities."""
        return self._run_bridge(
            {
                "action": "validate_credentials",
                "email": email,
                "password": password,
            }
        )

    def generate_api_key(self, user_id: int, user_login: str) -> str:
        """Generates a random API key, stores it in WP options, returns the key."""
        payload = self._run_bridge(
            {
                "action": "generate_api_key",
                "user_id": user_id,
                "user_login": user_login,
            }
        )
        key = str(payload.get("api_key", ""))
        if not key:
            raise WordPressBridgeError("Bridge returned empty API key.")
        return key

    def load_api_keys(self) -> list[str]:
        """Returns list of active API keys from WP options."""
        payload = self._run_bridge({"action": "load_api_keys"})
        raw_keys = payload.get("keys", [])
        if not isinstance(raw_keys, list):
            return []
        return [str(k["key"]) for k in raw_keys if isinstance(k, dict) and k.get("key")]

    def _run_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        wp_load = Path(self._config.wp_load_path)
        if not wp_load.is_absolute():
            cwd_candidate = (Path.cwd() / wp_load).resolve()
            project_root = Path(__file__).resolve().parents[4]
            project_candidate = (project_root / wp_load).resolve()
            wp_load = cwd_candidate if cwd_candidate.exists() else project_candidate

        bridge_payload = {
            **payload,
            "wp_load_path": str(wp_load),
            "store_option_key": self._config.store_option_key,
        }

        script = r"""
        $payload = json_decode(getenv('RESTATIFY_WP_BRIDGE_PAYLOAD') ?: '{}', true);
        if (!is_array($payload)) {
            echo json_encode(['ok' => false, 'error' => 'Invalid bridge payload']);
            exit(0);
        }

        $wpLoadPath = (string)($payload['wp_load_path'] ?? '');
        if ($wpLoadPath === '' || !file_exists($wpLoadPath)) {
            echo json_encode(['ok' => false, 'error' => 'wp-load.php not found']);
            exit(0);
        }

        require_once $wpLoadPath;

        $optionKey = (string)($payload['store_option_key'] ?? 'restatify_ai_multichat_conversations');
        $action = (string)($payload['action'] ?? '');

        $store = get_option($optionKey, []);
        if (!is_array($store)) {
            $store = [];
        }

        if ($action === 'load_store') {
            echo json_encode(['ok' => true, 'store' => $store], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'append_support_message') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            $message = sanitize_textarea_field((string)($payload['message'] ?? ''));
            $message = trim($message);

            if ($conversationId === '' || $message === '') {
                echo json_encode(['ok' => false, 'error' => 'conversation_id and message are required']);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => false, 'error' => 'Conversation not found']);
                exit(0);
            }

            if (!isset($store[$conversationId]['messages']) || !is_array($store[$conversationId]['messages'])) {
                $store[$conversationId]['messages'] = [];
            }

            $entry = [
                'sender' => 'support',
                'message' => $message,
                'time_gmt' => gmdate('c'),
            ];

            $store[$conversationId]['messages'][] = $entry;
            $store[$conversationId]['updated_at_gmt'] = gmdate('c');
            $store[$conversationId]['messages'] = array_slice($store[$conversationId]['messages'], -80);

            uasort($store, static function ($a, $b): int {
                $aUpdated = is_array($a) ? (string)($a['updated_at_gmt'] ?? '') : '';
                $bUpdated = is_array($b) ? (string)($b['updated_at_gmt'] ?? '') : '';
                return strcmp($bUpdated, $aUpdated);
            });

            update_option($optionKey, $store, false);
            echo json_encode(['ok' => true, 'entry' => $entry], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'validate_credentials') {
                $email = sanitize_text_field((string)($payload['email'] ?? ''));
                $password = (string)($payload['password'] ?? '');

                if ($email === '' || $password === '') {
                    echo json_encode(['ok' => false, 'error' => 'email and password are required']);
                    exit(0);
                }

                $user = get_user_by('email', $email);
                if (!$user) {
                    $user = get_user_by('login', $email);
                }

                if (!$user) {
                    echo json_encode(['ok' => true, 'valid' => false]);
                    exit(0);
                }

                if (!wp_check_password($password, $user->user_pass, $user->ID)) {
                    echo json_encode(['ok' => true, 'valid' => false]);
                    exit(0);
                }

                $has_cap = user_can($user, 'restatify_mco_support_chat') || user_can($user, 'manage_options');
                echo json_encode([
                    'ok' => true,
                    'valid' => true,
                    'user_id' => $user->ID,
                    'user_login' => $user->user_login,
                    'has_capability' => $has_cap,
                ], JSON_UNESCAPED_UNICODE);
                exit(0);
        }

        if ($action === 'generate_api_key') {
                $user_id = (int)($payload['user_id'] ?? 0);
                $user_login = sanitize_user((string)($payload['user_login'] ?? ''));

                if ($user_id <= 0) {
                    echo json_encode(['ok' => false, 'error' => 'user_id is required']);
                    exit(0);
                }

                $keys_option = 'restatify_support_api_keys';
                $keys = get_option($keys_option, []);
                if (!is_array($keys)) { $keys = []; }

                $new_key = 'rsa-' . bin2hex(random_bytes(24));
                $keys[] = [
                    'key' => $new_key,
                    'user_id' => $user_id,
                    'user_login' => $user_login,
                    'created_at' => gmdate('c'),
                ];
                update_option($keys_option, $keys, false);
                echo json_encode(['ok' => true, 'api_key' => $new_key]);
                exit(0);
        }

        if ($action === 'load_api_keys') {
                $keys_option = 'restatify_support_api_keys';
                $keys = get_option($keys_option, []);
                if (!is_array($keys)) { $keys = []; }

                $valid = array_values(array_filter($keys, static function ($k) {
                    return is_array($k) && !empty($k['key']);
                }));
                echo json_encode(['ok' => true, 'keys' => $valid], JSON_UNESCAPED_UNICODE);
                exit(0);
        }

        echo json_encode(['ok' => false, 'error' => 'Unsupported action']);
        """

        env = os.environ.copy()
        env["RESTATIFY_WP_BRIDGE_PAYLOAD"] = json.dumps(bridge_payload)

        try:
            process = subprocess.run(
                [self._config.php_executable, "-r", script],
                capture_output=True,
                text=True,
                timeout=self._config.command_timeout_seconds,
                env=env,
            )
        except FileNotFoundError as exc:
            raise WordPressBridgeError(
                f"PHP executable not found: {self._config.php_executable}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise WordPressBridgeError(
                "WordPress bridge timed out while executing PHP script."
            ) from exc
        except subprocess.SubprocessError as exc:
            raise WordPressBridgeError("WordPress bridge process could not be started.") from exc

        if process.returncode != 0:
            stderr = process.stderr.strip()
            raise WordPressBridgeError(f"WordPress bridge process failed: {stderr}")

        output = process.stdout.strip()
        if not output:
            raise WordPressBridgeError("WordPress bridge returned empty output.")

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise WordPressBridgeError(f"Invalid WordPress bridge JSON output: {output}") from exc

        if not isinstance(parsed, dict):
            raise WordPressBridgeError("WordPress bridge returned invalid payload type.")

        if not parsed.get("ok"):
            error_message = str(parsed.get("error", "WordPress bridge error"))
            raise WordPressBridgeError(error_message)

        return parsed
