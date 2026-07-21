from __future__ import annotations

import httpx
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
    bridge_base_url: str = ""
    bridge_api_key: str = ""
    db_host_override: str = ""
    db_user_override: str = ""
    db_password_override: str = ""
    db_name_override: str = ""


def build_wordpress_bridge_config(settings: Any) -> WordPressBridgeConfig:
    return WordPressBridgeConfig(
        php_executable=settings.wp_php_executable,
        wp_load_path=settings.wp_load_path,
        store_option_key=settings.wp_chat_store_option_key,
        command_timeout_seconds=settings.wp_bridge_timeout_seconds,
        bridge_base_url=getattr(settings, "wp_bridge_base_url", ""),
        bridge_api_key=getattr(settings, "wp_bridge_api_key", ""),
        db_host_override=settings.wp_db_host_override,
        db_user_override=settings.wp_db_user_override,
        db_password_override=settings.wp_db_password_override,
        db_name_override=settings.wp_db_name_override,
    )


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

    def append_support_message(self, conversation_id: str, message: str) -> dict[str, Any]:
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

        ai_entry_raw = payload.get("ai_entry")
        ai_entry: dict[str, str] | None = None
        if isinstance(ai_entry_raw, dict):
            ai_entry = {
                "sender": str(ai_entry_raw.get("sender", "ai")),
                "message": str(ai_entry_raw.get("message", "")),
                "time_gmt": str(ai_entry_raw.get("time_gmt", "")),
            }

        sender = str(entry.get("sender", "support"))
        text = str(entry.get("message", ""))
        time_gmt = str(entry.get("time_gmt", ""))

        result: dict[str, Any] = {
            "conversation_id": conversation_id,
            "sender": sender,
            "message": text,
            "time_gmt": time_gmt,
        }
        if ai_entry is not None:
            result["ai_entry"] = ai_entry

        return result

    def get_conversation_tools(self, conversation_id: str) -> dict[str, Any]:
        payload = self._run_bridge(
            {
                "action": "get_conversation_tools",
                "conversation_id": conversation_id,
            }
        )

        ai_mode = str(payload.get("ai_mode", "both"))
        booking_overlay_available = bool(payload.get("booking_overlay_available", False))
        return {
            "conversation_id": conversation_id,
            "ai_mode": ai_mode,
            "booking_overlay_available": booking_overlay_available,
        }

    def set_conversation_ai_mode(self, conversation_id: str, ai_mode: str) -> str:
        payload = self._run_bridge(
            {
                "action": "set_conversation_ai_mode",
                "conversation_id": conversation_id,
                "ai_mode": ai_mode,
            }
        )
        return str(payload.get("ai_mode", "both"))

    def delete_conversation(self, conversation_id: str) -> dict[str, bool]:
        payload = self._run_bridge(
            {
                "action": "delete_conversation",
                "conversation_id": conversation_id,
            }
        )

        return {
            "deleted": bool(payload.get("deleted", False)),
            "already_gone": bool(payload.get("already_gone", False)),
        }

    def trigger_booking_overlay(self, conversation_id: str) -> dict[str, str]:
        payload = self._run_bridge(
            {
                "action": "trigger_booking_overlay",
                "conversation_id": conversation_id,
            }
        )

        entry = payload.get("entry")
        if not isinstance(entry, dict):
            raise WordPressBridgeError("WordPress bridge returned invalid booking trigger payload.")

        return {
            "conversation_id": conversation_id,
            "sender": str(entry.get("sender", "support")),
            "message": str(entry.get("message", "")),
            "time_gmt": str(entry.get("time_gmt", "")),
        }

    def validate_conversation_token(self, conversation_id: str, conversation_token: str) -> bool:
        payload = self._run_bridge(
            {
                "action": "validate_conversation_token",
                "conversation_id": conversation_id,
                "conversation_token": conversation_token,
            }
        )
        return bool(payload.get("valid", False))

    def validate_wp_credentials(self, username: str, password: str) -> dict[str, Any]:
        """Validates WordPress credentials, returns user info and capabilities."""
        return self._run_bridge(
            {
                "action": "validate_credentials",
                "username": username,
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
        if self._config.bridge_base_url.strip() != "":
            return self._run_http_bridge(payload)

        return self._run_local_bridge(payload)

    def _run_http_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = self._config.bridge_base_url.rstrip("/") + "/bridge"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._config.bridge_api_key.strip() != "":
            headers["X-Restatify-Bridge-Key"] = self._config.bridge_api_key.strip()

        bridge_payload = {
            **payload,
            "store_option_key": self._config.store_option_key,
        }

        try:
            response = httpx.post(
                endpoint,
                json=bridge_payload,
                headers=headers,
                timeout=self._config.command_timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise WordPressBridgeError(
                f"WordPress bridge request failed: {exc}"
            ) from exc

        try:
            parsed = response.json()
        except ValueError as exc:
            raise WordPressBridgeError(
                f"Invalid WordPress bridge JSON output: {response.text.strip()}"
            ) from exc

        if response.status_code >= 400:
            if isinstance(parsed, dict):
                message = str(parsed.get("message") or parsed.get("error") or parsed.get("detail") or "WordPress bridge request failed")
            else:
                message = "WordPress bridge request failed"
            raise WordPressBridgeError(message)

        if not isinstance(parsed, dict):
            raise WordPressBridgeError("WordPress bridge returned invalid payload type.")

        if not parsed.get("ok"):
            error_message = str(parsed.get("error", "WordPress bridge error"))
            raise WordPressBridgeError(error_message)

        return parsed

    def _run_local_bridge(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        error_reporting(E_ERROR | E_PARSE);
        ini_set('display_errors', '0');

        $payload = json_decode(getenv('RESTATIFY_WP_BRIDGE_PAYLOAD') ?: '{}', true);
        if (!is_array($payload)) {
            echo json_encode(['ok' => false, 'error' => 'Invalid bridge payload']);
            exit(0);
        }

        $dbHostOverride = (string)(getenv('RESTATIFY_WP_DB_HOST_OVERRIDE') ?: '');
        if ($dbHostOverride !== '' && !defined('DB_HOST')) {
            define('DB_HOST', $dbHostOverride);
        }

        $dbUserOverride = (string)(getenv('RESTATIFY_WP_DB_USER_OVERRIDE') ?: '');
        if ($dbUserOverride !== '' && !defined('DB_USER')) {
            define('DB_USER', $dbUserOverride);
        }

        $dbPasswordOverride = (string)(getenv('RESTATIFY_WP_DB_PASSWORD_OVERRIDE') ?: '');
        if ($dbPasswordOverride !== '' && !defined('DB_PASSWORD')) {
            define('DB_PASSWORD', $dbPasswordOverride);
        }

        $dbNameOverride = (string)(getenv('RESTATIFY_WP_DB_NAME_OVERRIDE') ?: '');
        if ($dbNameOverride !== '' && !defined('DB_NAME')) {
            define('DB_NAME', $dbNameOverride);
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

        if (!function_exists('restatify_bridge_get_support_runtime_instance')) {
            function restatify_bridge_get_support_runtime_instance() {
                if (!class_exists('Restatify_Ai_Multichat_Chat_Runtime', false)) {
                    return null;
                }

                return new Restatify_Ai_Multichat_Chat_Runtime();
            }
        }

        if (!function_exists('restatify_bridge_try_generate_support_ai_reply')) {
            function restatify_bridge_try_generate_support_ai_reply($runtime, array &$store, string $conversationId, string $message): void {
                if (!is_object($runtime)) {
                    return;
                }

                try {
                    $runner = \Closure::bind(
                        function (array &$storeArg, string $conversationIdArg, string $messageArg): void {
                            $options = $this->get_options();
                            if (empty($options['ai_enabled']) || !$this->should_ai_reply_for_sender($storeArg[$conversationIdArg], 'support')) {
                                return;
                            }

                            $lockTtl = $this->get_ai_lock_ttl_seconds($options);
                            $lockToken = $this->acquire_ai_generation_lock($conversationIdArg, $lockTtl);
                            if ($lockToken === '') {
                                $this->enqueue_pending_ai_message($conversationIdArg, 'support', $messageArg);
                                $this->log_ai_debug(!empty($options['ai_debug_enabled']), 'AI generation skipped due to active lock (api bridge)', [
                                    'conversation_id' => $conversationIdArg,
                                    'sender' => 'support',
                                ]);
                                return;
                            }

                            try {
                                $aiReply = $this->generate_ai_reply($options, $storeArg[$conversationIdArg], $messageArg);
                                $aiReply = $this->sanitize_chat_message_content($aiReply);
                                if ($aiReply !== '') {
                                    $storeArg[$conversationIdArg]['messages'][] = $this->format_chat_message('ai', $aiReply);
                                    $storeArg[$conversationIdArg]['updated_at_gmt'] = gmdate('c');
                                }

                                $storeArg[$conversationIdArg] = $this->process_pending_ai_messages_after_generation($options, $storeArg[$conversationIdArg]);
                            } finally {
                                $this->release_ai_generation_lock($conversationIdArg, $lockToken);
                            }
                        },
                        $runtime,
                        get_class($runtime)
                    );

                    if ($runner instanceof \Closure) {
                        $runner($store, $conversationId, $message);
                    }
                } catch (\Throwable $throwable) {
                    // Keep support send path resilient even when AI generation fails.
                }
            }
        }

        if ($action === 'load_store') {

            $optionsKey = 'restatify_ai_multichat_options';
            $options = get_option($optionsKey, []);
            if (!is_array($options)) {
                $options = [];
            }

            $maxAgeMinutes = max(0, (int) ($options['chat_reset_minutes'] ?? 0));
            if ($maxAgeMinutes > 0 && count($store) > 0) {
                $now = time();
                $maxAgeSeconds = $maxAgeMinutes * 60;
                $filtered = [];

                foreach ($store as $id => $conversation) {
                    if (!is_string($id) || !is_array($conversation)) {
                        continue;
                    }

                    $updatedRaw = (string) ($conversation['updated_at_gmt'] ?? '');
                    $createdRaw = (string) ($conversation['created_at_gmt'] ?? '');
                    $updatedTs = $updatedRaw !== '' ? strtotime($updatedRaw) : false;
                    $createdTs = $createdRaw !== '' ? strtotime($createdRaw) : false;
                    $referenceTs = $updatedTs !== false ? (int) $updatedTs : ($createdTs !== false ? (int) $createdTs : 0);

                    // Keep malformed timestamps to avoid accidental data loss.
                    if ($referenceTs <= 0 || ($now - $referenceTs) < $maxAgeSeconds) {
                        $filtered[$id] = $conversation;
                    }
                }

                if (count($filtered) !== count($store)) {
                    $store = $filtered;
                    update_option($optionKey, $store, false);
                }
            }

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

            $runtime = restatify_bridge_get_support_runtime_instance();
            if ($runtime !== null) {
                restatify_bridge_try_generate_support_ai_reply($runtime, $store, $conversationId, $message);
                if (!isset($store[$conversationId]['messages']) || !is_array($store[$conversationId]['messages'])) {
                    $store[$conversationId]['messages'] = [];
                }
                $store[$conversationId]['messages'] = array_slice($store[$conversationId]['messages'], -80);
            }

            uasort($store, static function ($a, $b): int {
                $aUpdated = is_array($a) ? (string)($a['updated_at_gmt'] ?? '') : '';
                $bUpdated = is_array($b) ? (string)($b['updated_at_gmt'] ?? '') : '';
                return strcmp($bUpdated, $aUpdated);
            });

            $aiEntry = null;
            if (isset($store[$conversationId]['messages']) && is_array($store[$conversationId]['messages']) && count($store[$conversationId]['messages']) > 0) {
                $lastMessage = end($store[$conversationId]['messages']);
                if (is_array($lastMessage) && (string) ($lastMessage['sender'] ?? '') === 'ai') {
                    $aiEntry = [
                        'sender' => 'ai',
                        'message' => (string) ($lastMessage['message'] ?? ''),
                        'time_gmt' => (string) ($lastMessage['time_gmt'] ?? ''),
                    ];
                }
                reset($store[$conversationId]['messages']);
            }

            update_option($optionKey, $store, false);
            echo json_encode(['ok' => true, 'entry' => $entry, 'ai_entry' => $aiEntry], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'get_conversation_tools') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            if ($conversationId === '') {
                echo json_encode(['ok' => false, 'error' => 'conversation_id is required']);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => false, 'error' => 'Conversation not found']);
                exit(0);
            }

            $allowed = ['off', 'visitor', 'support', 'both'];
            $mode = sanitize_key((string)($store[$conversationId]['ai_mode'] ?? 'both'));
            if (!in_array($mode, $allowed, true)) {
                $mode = 'both';
            }

            $booking_overlay_available = function_exists('restatify_booking_ai_handle_message') || shortcode_exists('restatify_booking_popup');

            echo json_encode([
                'ok' => true,
                'ai_mode' => $mode,
                'booking_overlay_available' => $booking_overlay_available,
            ], JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'set_conversation_ai_mode') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            $mode = sanitize_key((string)($payload['ai_mode'] ?? 'both'));

            if ($conversationId === '') {
                echo json_encode(['ok' => false, 'error' => 'conversation_id is required']);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => false, 'error' => 'Conversation not found']);
                exit(0);
            }

            $allowed = ['off', 'visitor', 'support', 'both'];
            if (!in_array($mode, $allowed, true)) {
                $mode = 'both';
            }

            $store[$conversationId]['ai_mode'] = $mode;
            $store[$conversationId]['updated_at_gmt'] = gmdate('c');
            update_option($optionKey, $store, false);

            echo json_encode(['ok' => true, 'ai_mode' => $mode], JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'delete_conversation') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            if ($conversationId === '') {
                echo json_encode(['ok' => false, 'error' => 'conversation_id is required']);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => true, 'deleted' => true, 'already_gone' => true], JSON_UNESCAPED_UNICODE);
                exit(0);
            }

            unset($store[$conversationId]);
            delete_option('restatify_mco_ai_pending_' . md5($conversationId));
            update_option($optionKey, $store, false);

            echo json_encode(['ok' => true, 'deleted' => true, 'already_gone' => false], JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'trigger_booking_overlay') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            if ($conversationId === '') {
                echo json_encode(['ok' => false, 'error' => 'conversation_id is required']);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => false, 'error' => 'Conversation not found']);
                exit(0);
            }

            $booking_overlay_available = function_exists('restatify_booking_ai_handle_message') || shortcode_exists('restatify_booking_popup');
            if (!$booking_overlay_available) {
                echo json_encode(['ok' => false, 'error' => 'Booking overlay unavailable']);
                exit(0);
            }

            $booking_open_token = defined('RESTATIFY_BOOKING_OPEN_TOKEN')
                ? (string) constant('RESTATIFY_BOOKING_OPEN_TOKEN')
                : '[[RESTATIFY_BOOKING_OPEN]]';
            $booking_message = 'Ich habe das Buchungstool fuer dich geoeffnet. Bitte waehle einen Termin und bestaetige deine Reservierung.';
            $composed = trim($booking_open_token . ' ' . $booking_message);

            if (!isset($store[$conversationId]['messages']) || !is_array($store[$conversationId]['messages'])) {
                $store[$conversationId]['messages'] = [];
            }

            $entry = [
                'sender' => 'support',
                'message' => $composed,
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

        if ($action === 'validate_conversation_token') {
            $conversationId = sanitize_text_field((string)($payload['conversation_id'] ?? ''));
            $conversationToken = sanitize_text_field((string)($payload['conversation_token'] ?? ''));

            if ($conversationId === '' || $conversationToken === '') {
                echo json_encode(['ok' => true, 'valid' => false], JSON_UNESCAPED_UNICODE);
                exit(0);
            }

            if (!isset($store[$conversationId]) || !is_array($store[$conversationId])) {
                echo json_encode(['ok' => true, 'valid' => false], JSON_UNESCAPED_UNICODE);
                exit(0);
            }

            $storedToken = (string) ($store[$conversationId]['token'] ?? '');
            $valid = $storedToken !== '' && hash_equals($storedToken, $conversationToken);

            echo json_encode(['ok' => true, 'valid' => $valid], JSON_UNESCAPED_UNICODE);
            exit(0);
        }

        if ($action === 'validate_credentials') {
                $username = sanitize_user((string)($payload['username'] ?? ''));
                $password = (string)($payload['password'] ?? '');

                if ($username === '' || $password === '') {
                    echo json_encode(['ok' => false, 'error' => 'username and password are required']);
                    exit(0);
                }

                $user = get_user_by('login', $username);

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

                $valid = array_values(array_filter($keys, static function ($k) {
                    return is_array($k) && !empty($k['key']);
                }));

                $same_user = static function (array $entry) use ($user_id, $user_login): bool {
                    $entry_user_id = (int)($entry['user_id'] ?? 0);
                    $entry_user_login = sanitize_user((string)($entry['user_login'] ?? ''));

                    if ($entry_user_id > 0 && $entry_user_id === $user_id) {
                        return true;
                    }

                    return $user_login !== '' && $entry_user_login !== '' && hash_equals($entry_user_login, $user_login);
                };

                $existing_for_user = [];
                foreach ($valid as $entry) {
                    if ($same_user($entry)) {
                        $existing_for_user[] = $entry;
                    }
                }

                if (count($existing_for_user) > 0) {
                    usort($existing_for_user, static function ($a, $b): int {
                        $a_created = strtotime((string)($a['created_at'] ?? '')) ?: 0;
                        $b_created = strtotime((string)($b['created_at'] ?? '')) ?: 0;
                        return $b_created <=> $a_created;
                    });

                    $selected = $existing_for_user[0];
                    $selected_key = (string)($selected['key'] ?? '');

                    // Keep exactly one key per user to prevent unbounded growth.
                    $deduped = [];
                    $kept_for_user = false;
                    foreach ($valid as $entry) {
                        if ($same_user($entry)) {
                            if (!$kept_for_user && hash_equals((string)($entry['key'] ?? ''), $selected_key)) {
                                $deduped[] = $entry;
                                $kept_for_user = true;
                            }
                            continue;
                        }
                        $deduped[] = $entry;
                    }

                    if (count($deduped) !== count($keys)) {
                        update_option($keys_option, $deduped, false);
                    }

                    echo json_encode(['ok' => true, 'api_key' => $selected_key]);
                    exit(0);
                }

                $new_key = 'rsa-' . bin2hex(random_bytes(24));
                $valid[] = [
                    'key' => $new_key,
                    'user_id' => $user_id,
                    'user_login' => $user_login,
                    'created_at' => gmdate('c'),
                ];

                update_option($keys_option, $valid, false);
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

                usort($valid, static function ($a, $b): int {
                    $a_created = strtotime((string)($a['created_at'] ?? '')) ?: 0;
                    $b_created = strtotime((string)($b['created_at'] ?? '')) ?: 0;
                    return $b_created <=> $a_created;
                });

                $deduped = [];
                $seen_users = [];
                foreach ($valid as $entry) {
                    $entry_user_id = (int)($entry['user_id'] ?? 0);
                    $entry_user_login = sanitize_user((string)($entry['user_login'] ?? ''));
                    $user_key = $entry_user_id > 0 ? ('uid:' . $entry_user_id) : ('uln:' . $entry_user_login);

                    if ($user_key === 'uln:') {
                        $deduped[] = $entry;
                        continue;
                    }

                    if (isset($seen_users[$user_key])) {
                        continue;
                    }

                    $seen_users[$user_key] = true;
                    $deduped[] = $entry;
                }

                if (count($deduped) !== count($keys)) {
                    update_option($keys_option, $deduped, false);
                }

                echo json_encode(['ok' => true, 'keys' => $deduped], JSON_UNESCAPED_UNICODE);
                exit(0);
        }

        echo json_encode(['ok' => false, 'error' => 'Unsupported action']);
        """

        env = os.environ.copy()
        env["RESTATIFY_WP_BRIDGE_PAYLOAD"] = json.dumps(bridge_payload)
        env["RESTATIFY_WP_DB_HOST_OVERRIDE"] = self._config.db_host_override
        env["RESTATIFY_WP_DB_USER_OVERRIDE"] = self._config.db_user_override
        env["RESTATIFY_WP_DB_PASSWORD_OVERRIDE"] = self._config.db_password_override
        env["RESTATIFY_WP_DB_NAME_OVERRIDE"] = self._config.db_name_override

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
