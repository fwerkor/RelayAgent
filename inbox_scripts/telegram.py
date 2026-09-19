#!/usr/bin/env python3
"""Telegram Bot API connector for RelayAgent.

Configuration is read from RELAYAGENT_TELEGRAM_BOT_TOKEN or from
.secrets/telegram.json:

    {"bot_token": "123456:..."}

The connector deliberately does not decide whether a sender is the Owner.
That decision belongs to RelayAgent using owner.md.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATH = ROOT / ".secrets" / "telegram.json"
STATE_PATH = ROOT / ".telegram_state.json"


def _token() -> str | None:
    value = os.environ.get("RELAYAGENT_TELEGRAM_BOT_TOKEN")
    if value:
        return value.strip()
    if SECRET_PATH.exists():
        try:
            data = json.loads(SECRET_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = data.get("bot_token")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"offset": 0, "seen": [], "acked": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"offset": 0, "seen": [], "acked": []}
    return {
        "offset": int(data.get("offset", 0)),
        "seen": [int(x) for x in data.get("seen", [])],
        "acked": [int(x) for x in data.get("acked", [])],
    }


def _save_state(state: dict[str, Any]) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def _api(method: str, payload: dict[str, Any] | None = None) -> Any:
    token = _token()
    if not token:
        raise RuntimeError("Telegram is not configured")
    encoded = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=encoded,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Telegram API request failed: {exc}") from exc
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body.get('description', 'unknown error')}")
    return body.get("result")


def _message_from_update(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None

    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    text = message.get("text")
    if text is None:
        text = message.get("caption")
    if text is None:
        text = f"[Telegram message type without text: {sorted(k for k in message if k not in {'from', 'chat'})}]"

    sender_name = " ".join(
        str(x).strip()
        for x in (sender.get("first_name"), sender.get("last_name"))
        if x
    ).strip()
    if sender.get("username"):
        sender_name = f"{sender_name} (@{sender['username']})".strip()

    timestamp = None
    if isinstance(message.get("date"), int):
        timestamp = datetime.fromtimestamp(message["date"], tz=timezone.utc).isoformat()

    return {
        "id": str(update["update_id"]),
        "sender_id": str(sender.get("id", "")),
        "sender_name": sender_name,
        "chat_id": str(chat.get("id", "")),
        "message_id": str(message.get("message_id", "")),
        "timestamp": timestamp,
        "content": str(text),
    }


def fetch() -> list[dict[str, Any]]:
    if not _token():
        return []

    state = _state()
    updates = _api(
        "getUpdates",
        {
            "offset": state["offset"],
            "timeout": 0,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        },
    )
    if not isinstance(updates, list):
        return []

    seen = set(state["seen"])
    result: list[dict[str, Any]] = []
    for update in updates:
        if not isinstance(update, dict) or "update_id" not in update:
            continue
        update_id = int(update["update_id"])
        seen.add(update_id)
        normalized = _message_from_update(update)
        if normalized is not None:
            result.append(normalized)

    state["seen"] = sorted(seen)
    _save_state(state)
    return result


def ack(message_id: str) -> None:
    state = _state()
    update_id = int(message_id)
    seen = sorted(set(state["seen"]) | {update_id})
    acked = set(state["acked"])
    acked.add(update_id)

    current = int(state["offset"])
    remaining = [value for value in seen if value >= current and value not in acked]
    if remaining:
        new_offset = min(remaining)
    else:
        acknowledged_seen = [value for value in seen if value >= current]
        new_offset = max(acknowledged_seen) + 1 if acknowledged_seen else current

    state["offset"] = new_offset
    state["seen"] = [value for value in seen if value >= new_offset]
    state["acked"] = sorted(value for value in acked if value >= new_offset)
    _save_state(state)


def reply(message: dict[str, Any], text: str) -> None:
    chat_id = message.get("chat_id")
    if not chat_id:
        raise RuntimeError("Telegram message has no chat_id")
    payload: dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": text,
    }
    message_id = message.get("message_id")
    if message_id:
        payload["reply_parameters"] = json.dumps({"message_id": int(message_id)})
    _api("sendMessage", payload)
