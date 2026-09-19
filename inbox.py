#!/usr/bin/env python3
"""RelayAgent inbox aggregator.

Connector modules live in inbox_scripts/*.py and may expose:

    fetch() -> list[dict]
    ack(message_id: str) -> None

Each fetched message must contain a stable "id". The aggregator persists
pending messages before printing them, so an interrupted Agent execution can
see them again on the next run. Messages are removed only after --ack.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "inbox_scripts"
STATE_PATH = ROOT / ".inbox_state.json"


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"pending": {}, "acked": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read {STATE_PATH}: {exc}") from exc
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("pending", {}), dict)
        or not isinstance(state.get("acked", {}), dict)
    ):
        raise RuntimeError(f"invalid inbox state in {STATE_PATH}")
    state.setdefault("pending", {})
    state.setdefault("acked", {})
    return state


def save_state(state: dict[str, Any]) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(STATE_PATH)


def discover_connectors() -> dict[str, Path]:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    connectors: dict[str, Path] = {}
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        connectors[path.stem] = path
    return connectors


def load_connector(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(f"relayagent_inbox_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load connector {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(v) for v in value]
        return str(value)


def collect(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    pending: dict[str, Any] = state["pending"]
    acked: dict[str, Any] = state["acked"]

    for source, path in discover_connectors().items():
        try:
            connector = load_connector(source, path)
            fetch = getattr(connector, "fetch", None)
            if not callable(fetch):
                errors.append(f"{source}: missing fetch()")
                continue

            messages = fetch()
            if messages is None:
                continue
            if not isinstance(messages, list):
                raise TypeError("fetch() must return a list")

            for message in messages:
                if not isinstance(message, dict):
                    raise TypeError("each message must be a dict")
                external_id = message.get("id")
                if external_id is None or str(external_id) == "":
                    raise ValueError("each message must have a stable non-empty id")

                external_id = str(external_id)
                canonical_id = f"{source}:{external_id}"
                if canonical_id in acked:
                    continue

                normalized = json_safe(dict(message))
                normalized["id"] = canonical_id
                normalized.setdefault("source", source)

                pending.setdefault(
                    canonical_id,
                    {
                        "source": source,
                        "external_id": external_id,
                        "message": normalized,
                    },
                )
        except Exception as exc:
            errors.append(f"{source}: {exc}")

    save_state(state)
    return errors


def acknowledge(state: dict[str, Any], canonical_id: str) -> None:
    pending: dict[str, Any] = state["pending"]
    item = pending.get(canonical_id)
    if item is None:
        raise RuntimeError(f"unknown pending message: {canonical_id}")

    source = item["source"]
    path = discover_connectors().get(source)
    if path is None:
        raise RuntimeError(f"connector no longer exists: {source}")

    connector = load_connector(source, path)
    ack = getattr(connector, "ack", None)
    if callable(ack):
        ack(item["external_id"])

    del pending[canonical_id]
    state["acked"][canonical_id] = True
    save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect RelayAgent inbox messages")
    parser.add_argument("--ack", metavar="MESSAGE_ID", help="acknowledge one pending message")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    state = load_state()

    if args.ack:
        acknowledge(state, args.ack)
        if args.json:
            print(json.dumps({"acked": args.ack}, ensure_ascii=False))
        else:
            print(f"acked {args.ack}")
        return 0

    errors = collect(state)
    messages = [item["message"] for item in state["pending"].values()]

    if args.json:
        print(json.dumps({"messages": messages, "errors": errors}, ensure_ascii=False, indent=2))
    else:
        if messages:
            print(json.dumps(messages, ensure_ascii=False, indent=2))
        else:
            print("[]")
        for error in errors:
            print(f"inbox warning: {error}", file=sys.stderr)

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
